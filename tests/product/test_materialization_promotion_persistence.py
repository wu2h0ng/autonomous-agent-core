from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from agent_os_contracts import (
    CandidateEvaluationDisposition,
    CandidateEvaluationDraft,
    CandidateEvaluatorIdentity,
    CandidateEvaluatorKind,
    CandidateProvenance,
    CandidatePromotionCommand,
    CandidatePromotionDisposition,
    CandidateWriteChannel,
    CorrectionEpochVector,
    DomainCandidate,
    DomainCandidateDraft,
    MaterializationOutcome,
    RepresentationPatch,
    RepresentationPatchOperation,
    RepresentationRelationClass,
    content_digest,
    domain_candidate_digest,
)
from agent_os_core import CandidateConcurrentWrite, CandidateIdempotencyConflict
from agent_os_core.materialization_evaluation_persistence import (
    CandidateEvaluationRecordRequest,
    SQLiteCandidateEvaluationStore,
    candidate_evaluation_idempotency_key,
    candidate_evaluation_payload_digest,
)
from agent_os_core.materialization_ledger import SQLiteAdaptationLedger
from agent_os_core.materialization_promotion_persistence import (
    CandidatePromotionRecordRequest,
    SQLiteCandidatePromotionStore,
    candidate_promotion_idempotency_key,
    candidate_promotion_payload_digest,
    candidate_receipt_chain_digest,
)
from agent_os_core.materialization_promotion_policy import (
    PromotionPolicyRegistry,
    PromotionPolicyV1,
    PromotionReduction,
)


NOW = datetime(2026, 7, 15, 15, 0, tzinfo=timezone.utc)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64


class TestPromotePolicy:
    version = "TEST-ONLY-PROMOTE-V1"
    digest = content_digest(
        {"schema": "ADM-P3-TEST-POLICY-V1", "result": "PROMOTE_IF_NONEMPTY"}
    )

    def reduce(
        self, candidate: DomainCandidate, receipts: tuple[Any, ...]
    ) -> PromotionReduction:
        del candidate
        return PromotionReduction(
            disposition=(
                CandidatePromotionDisposition.PROMOTE
                if receipts
                else CandidatePromotionDisposition.DEFER
            ),
            reason_codes=("TEST_ONLY_PROOF_COMPLETE",)
            if receipts
            else ("TEST_ONLY_EMPTY",),
        )


class TestRejectPolicy:
    version = "TEST-ONLY-REJECT-V1"
    digest = content_digest({"schema": "ADM-P3-TEST-POLICY-V1", "result": "REJECT"})

    def reduce(
        self, candidate: DomainCandidate, receipts: tuple[Any, ...]
    ) -> PromotionReduction:
        del candidate, receipts
        return PromotionReduction(
            disposition=CandidatePromotionDisposition.REJECT,
            reason_codes=("TEST_ONLY_REJECT",),
        )


class BrokenEmptyPromotePolicy:
    version = "TEST-ONLY-BROKEN-EMPTY-PROMOTE-V1"
    digest = content_digest(
        {"schema": "ADM-P3-TEST-POLICY-V1", "result": "BROKEN_EMPTY_PROMOTE"}
    )

    def reduce(
        self, candidate: DomainCandidate, receipts: tuple[Any, ...]
    ) -> PromotionReduction:
        del candidate, receipts
        return PromotionReduction(
            disposition=CandidatePromotionDisposition.PROMOTE,
            reason_codes=("TEST_ONLY_BROKEN",),
        )


POLICIES = PromotionPolicyRegistry(
    (
        PromotionPolicyV1(),
        TestPromotePolicy(),
        TestRejectPolicy(),
        BrokenEmptyPromotePolicy(),
    )
)


def _candidate() -> DomainCandidate:
    patch = RepresentationPatch(
        operations=(
            RepresentationPatchOperation(
                operation_id="op:1",
                operation="UPSERT",
                assertion_id="assertion:1",
                subject_ref="entity:acme",
                predicate="rdf:type",
                object_ref="type:Company",
                relation_class=RepresentationRelationClass.ASSERTED,
                evidence_refs=("artifact:filing",),
            ),
        )
    )
    provenance = CandidateProvenance(
        source_id="source:filing",
        source_ref="artifact:filing",
        source_type="regulatory-filing",
        source_digest=DIGEST_A,
        accessed_at=NOW,
        effective_at=NOW - timedelta(days=1),
        license_or_terms_id="terms:public",
        permitted_use="analysis",
        redistribution_allowed=False,
        output_patch_digest=patch.patch_digest(),
        expires_at=NOW + timedelta(days=1),
    )
    draft = DomainCandidateDraft(
        task_id="task:candidate",
        materialization_run_id="run:candidate",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        submitted_by="principal:builder",
        mechanism_digest=DIGEST_B,
        source_snapshot_digest=DIGEST_C,
        requested_channel=CandidateWriteChannel.R,
        outcome=MaterializationOutcome.CANDIDATE,
        representation_patch=patch,
        provenance=(provenance,),
        submitted_at=NOW,
    )
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "candidate_id": "domain-candidate:1",
        "candidate_version": 1,
        "payload_digest": content_digest(draft),
        "idempotency_key": content_digest({"candidate": "1"}),
        "sealed_by": "system:domain-candidate-sealer:v1",
        "sealed_at": NOW,
        "observed_correction_epochs": CorrectionEpochVector(
            task_epoch=1,
            run_epoch=1,
            capability_epoch=1,
        ),
        "draft": draft,
    }
    return DomainCandidate(
        **payload,
        candidate_digest=domain_candidate_digest(payload),
    )


def _append_receipt(
    store: SQLiteCandidateEvaluationStore,
    candidate: DomainCandidate,
    index: int,
    *,
    disposition: CandidateEvaluationDisposition = (
        CandidateEvaluationDisposition.EVALUATOR_PASS
    ),
) -> Any:
    latest = store.latest(
        candidate.draft.tenant_id,
        candidate.draft.workspace_id,
        candidate.candidate_digest,
    )
    decisive = disposition in {
        CandidateEvaluationDisposition.EVALUATOR_PASS,
        CandidateEvaluationDisposition.EVALUATOR_FAIL,
    }
    draft = CandidateEvaluationDraft(
        candidate_digest=candidate.candidate_digest,
        candidate_task_id=candidate.draft.task_id,
        evaluation_task_id=f"task:evaluation:{index}",
        evaluation_run_id=f"run:evaluation:{index}",
        tenant_id=candidate.draft.tenant_id,
        workspace_id=candidate.draft.workspace_id,
        evaluator=CandidateEvaluatorIdentity(
            evaluator_id=f"principal:evaluator:{index}",
            evaluator_kind=CandidateEvaluatorKind.PROGRAMMATIC,
            evaluator_type="contract-check",
            evaluator_version=str(index),
            implementation_digest=content_digest({"implementation": index}),
            configuration_digest=content_digest({"configuration": index}),
        ),
        evidence_bundle_digest=content_digest({"evidence": index}),
        evidence_refs=(f"artifact:evidence:{index}",),
        disposition=disposition,
        score=0.9 if decisive else None,
        confidence=0.8,
        unresolved_gaps=("gap:unknown",)
        if disposition is CandidateEvaluationDisposition.UNRESOLVED
        else (),
        invalidity_reasons=("invalid:input",)
        if disposition is CandidateEvaluationDisposition.INVALID
        else (),
        parent_evaluation_digest=(
            latest.evaluation_digest if latest is not None else None
        ),
        submitted_at=NOW + timedelta(seconds=index),
    )
    contract_digest = content_digest({"contract": "ADM-P2", "version": 1})
    recorded_by = f"principal:recorder:{index}"
    request = CandidateEvaluationRecordRequest(
        evaluation_id=f"candidate-evaluation:{index}",
        tenant_id=draft.tenant_id,
        workspace_id=draft.workspace_id,
        candidate_digest=draft.candidate_digest,
        idempotency_key=candidate_evaluation_idempotency_key(
            draft, contract_digest, recorded_by
        ),
        payload_digest=candidate_evaluation_payload_digest(
            draft, contract_digest, recorded_by
        ),
        recorded_by=recorded_by,
        recorded_at=NOW + timedelta(seconds=index),
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=index,
            run_epoch=index,
            capability_epoch=index,
        ),
        evaluation_contract_digest=contract_digest,
        draft=draft,
    )
    return store.append(
        request,
        expected_parent_digest=latest.evaluation_digest if latest is not None else None,
    )


def _promotion_request(
    candidate: DomainCandidate,
    receipts: tuple[Any, ...],
    policy: Any,
    *,
    parent: str | None = None,
    expected_head: str | None = None,
    task_suffix: str = "1",
) -> CandidatePromotionRecordRequest:
    head = (
        expected_head
        if expected_head is not None
        else (receipts[-1].evaluation_digest if receipts else None)
    )
    command = CandidatePromotionCommand(
        candidate_digest=candidate.candidate_digest,
        candidate_task_id=candidate.draft.task_id,
        promotion_task_id=f"task:promotion:{task_suffix}",
        promotion_run_id=f"run:promotion:{task_suffix}",
        tenant_id=candidate.draft.tenant_id,
        workspace_id=candidate.draft.workspace_id,
        expected_evaluation_head_digest=head,
        expected_parent_promotion_digest=parent,
    )
    chain_digest = candidate_receipt_chain_digest(
        candidate.candidate_digest,
        receipts,
    )
    reduction = policy.reduce(candidate, receipts)
    decided_by = "principal:promoter"
    return CandidatePromotionRecordRequest(
        command=command,
        candidate=candidate,
        receipt_chain_digest=chain_digest,
        policy_version=policy.version,
        policy_digest=policy.digest,
        reduction=reduction,
        payload_digest=candidate_promotion_payload_digest(
            command,
            candidate,
            chain_digest,
            policy.version,
            policy.digest,
            reduction,
            decided_by,
        ),
        idempotency_key=candidate_promotion_idempotency_key(
            command,
            policy.version,
            policy.digest,
            decided_by,
        ),
        decided_by=decided_by,
        decided_at=NOW + timedelta(minutes=1),
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=4,
            run_epoch=5,
            capability_epoch=6,
        ),
    )


@dataclass
class Harness:
    ledger: SQLiteAdaptationLedger
    evaluations: SQLiteCandidateEvaluationStore
    promotions: SQLiteCandidatePromotionStore
    candidate: DomainCandidate


@pytest.fixture
def harness() -> Iterator[Harness]:
    ledger = SQLiteAdaptationLedger()
    evaluations = SQLiteCandidateEvaluationStore(ledger=ledger)
    promotions = SQLiteCandidatePromotionStore(ledger, POLICIES)
    value = Harness(ledger, evaluations, promotions, _candidate())
    yield value
    promotions.close()
    evaluations.close()
    ledger.close()


def test_borrower_close_does_not_close_shared_ledger(harness: Harness) -> None:
    harness.promotions.close()
    harness.evaluations.close()
    receipt = _append_receipt(harness.evaluations, harness.candidate, 1)
    assert receipt.evaluation_version == 1
    assert harness.ledger.connection.execute("SELECT 1").fetchone()[0] == 1


def test_store_rejects_receipt_subset_even_when_subset_head_is_valid(
    harness: Harness,
) -> None:
    first = _append_receipt(harness.evaluations, harness.candidate, 1)
    _append_receipt(harness.evaluations, harness.candidate, 2)
    request = _promotion_request(
        harness.candidate,
        (first,),
        PromotionPolicyV1(),
    )
    with pytest.raises(CandidateConcurrentWrite, match="head|chain"):
        harness.promotions.append(request)


def test_store_rejects_stale_latest_evaluation_head(harness: Harness) -> None:
    receipt = _append_receipt(harness.evaluations, harness.candidate, 1)
    request = _promotion_request(
        harness.candidate,
        (receipt,),
        PromotionPolicyV1(),
        expected_head=DIGEST_A,
    )
    with pytest.raises(CandidateConcurrentWrite, match="head"):
        harness.promotions.append(request)


@pytest.mark.parametrize(
    "mutation",
    (
        "UPDATE candidate_evaluations SET evaluation_version = 3 "
        "WHERE evaluation_version = 2",
        "UPDATE candidate_evaluations SET parent_evaluation_digest = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' "
        "WHERE evaluation_version = 2",
        "UPDATE candidate_evaluations SET tenant_id = 'tenant:other' "
        "WHERE evaluation_version = 2",
    ),
)
def test_store_rejects_gap_parent_break_and_cross_scope_receipt(
    harness: Harness,
    mutation: str,
) -> None:
    _append_receipt(harness.evaluations, harness.candidate, 1)
    _append_receipt(harness.evaluations, harness.candidate, 2)
    receipts = harness.evaluations.list_for_candidate(
        "tenant:1", "workspace:1", harness.candidate.candidate_digest
    )
    request = _promotion_request(
        harness.candidate,
        receipts,
        PromotionPolicyV1(),
    )
    harness.ledger.connection.execute(mutation)
    harness.ledger.connection.commit()
    with pytest.raises(
        CandidateConcurrentWrite, match="chain|head|scope|version|parent"
    ):
        harness.promotions.append(request)


def test_exact_old_replay_returns_original_before_parent_cas(harness: Harness) -> None:
    first = _append_receipt(harness.evaluations, harness.candidate, 1)
    request = _promotion_request(
        harness.candidate,
        (first,),
        PromotionPolicyV1(),
    )
    original = harness.promotions.append(request)
    _append_receipt(harness.evaluations, harness.candidate, 2)
    assert harness.promotions.append(request) == original


def test_same_derived_key_with_changed_payload_conflicts(harness: Harness) -> None:
    first = _append_receipt(harness.evaluations, harness.candidate, 1)
    request = _promotion_request(
        harness.candidate,
        (first,),
        PromotionPolicyV1(),
    )
    harness.promotions.append(request)
    with pytest.raises(CandidateIdempotencyConflict, match="payload"):
        harness.promotions.append(replace(request, payload_digest=DIGEST_A))


def test_new_decision_requires_latest_parent_and_new_receipt_head(
    harness: Harness,
) -> None:
    first_receipt = _append_receipt(harness.evaluations, harness.candidate, 1)
    first_request = _promotion_request(
        harness.candidate,
        (first_receipt,),
        PromotionPolicyV1(),
    )
    first = harness.promotions.append(first_request).decision

    same_head = _promotion_request(
        harness.candidate,
        (first_receipt,),
        PromotionPolicyV1(),
        parent=first.promotion_digest,
        task_suffix="same-head",
    )
    with pytest.raises(CandidateConcurrentWrite, match="new receipt head"):
        harness.promotions.append(same_head)

    _append_receipt(harness.evaluations, harness.candidate, 2)
    receipts = harness.evaluations.list_for_candidate(
        "tenant:1", "workspace:1", harness.candidate.candidate_digest
    )
    wrong_parent = _promotion_request(
        harness.candidate,
        receipts,
        PromotionPolicyV1(),
        task_suffix="wrong-parent",
    )
    with pytest.raises(CandidateConcurrentWrite, match="parent"):
        harness.promotions.append(wrong_parent)

    correct = _promotion_request(
        harness.candidate,
        receipts,
        PromotionPolicyV1(),
        parent=first.promotion_digest,
        task_suffix="2",
    )
    assert harness.promotions.append(correct).decision.promotion_version == 2


def test_reject_and_defer_never_insert_prior(harness: Harness) -> None:
    first = _append_receipt(harness.evaluations, harness.candidate, 1)
    deferred = harness.promotions.append(
        _promotion_request(
            harness.candidate,
            (first,),
            PromotionPolicyV1(),
        )
    )
    assert deferred.prior is None

    _append_receipt(harness.evaluations, harness.candidate, 2)
    receipts = harness.evaluations.list_for_candidate(
        "tenant:1", "workspace:1", harness.candidate.candidate_digest
    )
    rejected = harness.promotions.append(
        _promotion_request(
            harness.candidate,
            receipts,
            TestRejectPolicy(),
            parent=deferred.decision.promotion_digest,
            task_suffix="2",
        )
    )
    assert rejected.decision.disposition is CandidatePromotionDisposition.REJECT
    assert rejected.prior is None
    assert (
        harness.promotions.list_priors(
            "tenant:1", "workspace:1", harness.candidate.candidate_digest
        )
        == ()
    )


def test_registered_test_promote_policy_inserts_decision_and_prior_atomically(
    harness: Harness,
) -> None:
    receipt = _append_receipt(harness.evaluations, harness.candidate, 1)
    result = harness.promotions.append(
        _promotion_request(
            harness.candidate,
            (receipt,),
            TestPromotePolicy(),
        )
    )
    assert result.decision.disposition is CandidatePromotionDisposition.PROMOTE
    assert result.prior is not None
    assert result.prior.state == "INERT"
    assert result.prior.activation_authority == "NONE"
    assert harness.promotions.list_decisions(
        "tenant:1", "workspace:1", harness.candidate.candidate_digest
    ) == (result.decision,)
    assert harness.promotions.list_priors(
        "tenant:1", "workspace:1", harness.candidate.candidate_digest
    ) == (result.prior,)


def test_store_forbids_empty_chain_promote_even_for_defective_policy(
    harness: Harness,
) -> None:
    request = _promotion_request(
        harness.candidate,
        (),
        BrokenEmptyPromotePolicy(),
    )
    with pytest.raises(CandidateConcurrentWrite, match="empty receipt chain"):
        harness.promotions.append(request)
    assert (
        harness.promotions.list_decisions(
            "tenant:1", "workspace:1", harness.candidate.candidate_digest
        )
        == ()
    )


def test_sqlite_abort_on_prior_insert_rolls_back_promote_decision(
    harness: Harness,
) -> None:
    receipt = _append_receipt(harness.evaluations, harness.candidate, 1)
    harness.ledger.connection.execute(
        "CREATE TRIGGER abort_test_prior BEFORE INSERT ON domain_prior_artifacts "
        "BEGIN SELECT RAISE(ABORT, 'test prior abort'); END"
    )
    harness.ledger.connection.commit()

    with pytest.raises(CandidateConcurrentWrite, match="promotion append"):
        harness.promotions.append(
            _promotion_request(
                harness.candidate,
                (receipt,),
                TestPromotePolicy(),
            )
        )
    assert (
        harness.promotions.list_decisions(
            "tenant:1", "workspace:1", harness.candidate.candidate_digest
        )
        == ()
    )
    assert (
        harness.promotions.list_priors(
            "tenant:1", "workspace:1", harness.candidate.candidate_digest
        )
        == ()
    )


def test_restart_preserves_decision_prior_and_digests(tmp_path: Path) -> None:
    database = tmp_path / "adaptation.sqlite3"
    first_ledger = SQLiteAdaptationLedger(database)
    evaluations = SQLiteCandidateEvaluationStore(ledger=first_ledger)
    promotions = SQLiteCandidatePromotionStore(first_ledger, POLICIES)
    candidate = _candidate()
    receipt = _append_receipt(evaluations, candidate, 1)
    result = promotions.append(
        _promotion_request(candidate, (receipt,), TestPromotePolicy())
    )
    promotions.close()
    evaluations.close()
    first_ledger.close()

    second_ledger = SQLiteAdaptationLedger(database)
    reopened = SQLiteCandidatePromotionStore(second_ledger, POLICIES)
    try:
        assert reopened.list_decisions(
            "tenant:1", "workspace:1", candidate.candidate_digest
        ) == (result.decision,)
        assert reopened.list_priors(
            "tenant:1", "workspace:1", candidate.candidate_digest
        ) == (result.prior,)
    finally:
        reopened.close()
        second_ledger.close()
