from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from agent_os_contracts import (
    CandidateEvaluationDisposition,
    CandidateEvaluationDraft,
    CandidateEvaluationReceipt,
    CandidateEvaluatorIdentity,
    CandidateEvaluatorKind,
    CandidateProvenance,
    CandidatePromotionDisposition,
    CandidateWriteChannel,
    CorrectionEpochVector,
    DomainCandidate,
    DomainCandidateDraft,
    MaterializationOutcome,
    RepresentationPatch,
    RepresentationPatchOperation,
    RepresentationRelationClass,
    candidate_evaluation_receipt_digest,
    content_digest,
    domain_candidate_digest,
)
from agent_os_core.materialization_promotion_policy import (
    PROMOTION_POLICY_V1_DIGEST,
    PROMOTION_POLICY_V1_SPEC,
    PromotionPolicyRegistry,
    PromotionPolicyV1,
)


NOW = datetime(2026, 7, 15, 14, 30, tzinfo=timezone.utc)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64


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


def _receipt(
    index: int,
    disposition: CandidateEvaluationDisposition,
    *,
    parent_digest: str | None = None,
    evaluator_id: str | None = None,
    evidence_ref: str | None = None,
) -> CandidateEvaluationReceipt:
    decisive = disposition in {
        CandidateEvaluationDisposition.EVALUATOR_PASS,
        CandidateEvaluationDisposition.EVALUATOR_FAIL,
    }
    draft = CandidateEvaluationDraft(
        candidate_digest=_candidate().candidate_digest,
        candidate_task_id="task:candidate",
        evaluation_task_id=f"task:evaluation:{index}",
        evaluation_run_id=f"run:evaluation:{index}",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        evaluator=CandidateEvaluatorIdentity(
            evaluator_id=evaluator_id or f"principal:evaluator:{index}",
            evaluator_kind=CandidateEvaluatorKind.PROGRAMMATIC,
            evaluator_type="contract-check",
            evaluator_version=str(index),
            implementation_digest=content_digest({"implementation": index}),
            configuration_digest=content_digest({"configuration": index}),
        ),
        evidence_bundle_digest=content_digest({"evidence": index}),
        evidence_refs=(evidence_ref or f"artifact:credible-proof:{index}",),
        disposition=disposition,
        score=0.9 if decisive else None,
        confidence=0.9,
        unresolved_gaps=("gap:unknown",)
        if disposition is CandidateEvaluationDisposition.UNRESOLVED
        else (),
        invalidity_reasons=("invalid:input",)
        if disposition is CandidateEvaluationDisposition.INVALID
        else (),
        parent_evaluation_digest=parent_digest,
        submitted_at=NOW + timedelta(seconds=index),
    )
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "evaluation_id": f"candidate-evaluation:{index}",
        "evaluation_version": index,
        "payload_digest": content_digest({"draft": draft, "index": index}),
        "idempotency_key": content_digest({"receipt": index}),
        "recorded_by": f"principal:recorder:{index}",
        "recorded_at": NOW + timedelta(seconds=index),
        "observed_correction_epochs": CorrectionEpochVector(
            task_epoch=index,
            run_epoch=index,
            capability_epoch=index,
        ),
        "evaluation_contract_digest": DIGEST_D,
        "draft": draft,
    }
    return CandidateEvaluationReceipt(
        **payload,
        evaluation_digest=candidate_evaluation_receipt_digest(payload),
    )


def _chain(
    dispositions: tuple[CandidateEvaluationDisposition, ...],
) -> tuple[CandidateEvaluationReceipt, ...]:
    receipts: list[CandidateEvaluationReceipt] = []
    parent: str | None = None
    for index, disposition in enumerate(dispositions, start=1):
        receipt = _receipt(index, disposition, parent_digest=parent)
        receipts.append(receipt)
        parent = receipt.evaluation_digest
    return tuple(receipts)


@pytest.mark.parametrize(
    "dispositions",
    tuple(itertools.product(tuple(CandidateEvaluationDisposition), repeat=3)),
)
def test_v1_never_promotes_current_adm_p2_receipts(
    dispositions: tuple[CandidateEvaluationDisposition, ...],
) -> None:
    reduction = PromotionPolicyV1().reduce(_candidate(), _chain(dispositions))
    assert reduction.disposition is CandidatePromotionDisposition.DEFER


@pytest.mark.parametrize(
    ("dispositions", "observations"),
    (
        ((), ("NO_EVALUATION_RECEIPTS",)),
        ((CandidateEvaluationDisposition.EVALUATOR_PASS,), ()),
        (
            (CandidateEvaluationDisposition.EVALUATOR_FAIL,),
            ("RECORDED_EVALUATOR_FAIL_UNADJUDICATED",),
        ),
        (
            (CandidateEvaluationDisposition.INVALID,),
            ("EVALUATION_INVALID",),
        ),
        (
            (CandidateEvaluationDisposition.UNRESOLVED,),
            ("EVALUATION_UNRESOLVED",),
        ),
    ),
)
def test_v1_reason_grammar_is_fixed_and_deterministic(
    dispositions: tuple[CandidateEvaluationDisposition, ...],
    observations: tuple[str, ...],
) -> None:
    reduction = PromotionPolicyV1().reduce(_candidate(), _chain(dispositions))
    assert reduction.reason_codes == observations + (
        "EVIDENCE_BYTES_CUSTODY_UNPROVEN",
        "EVALUATOR_INDEPENDENCE_UNPROVEN",
        "PROMOTION_PROOFS_UNAVAILABLE_IN_ADM_P2",
    )
    assert reduction == PromotionPolicyV1().reduce(_candidate(), _chain(dispositions))


def test_distinct_identity_labels_and_credible_refs_do_not_upgrade_authority() -> None:
    first = _receipt(
        1,
        CandidateEvaluationDisposition.EVALUATOR_PASS,
        evaluator_id="principal:independent-a",
        evidence_ref="artifact:sha256-custodied-proof-a",
    )
    second = _receipt(
        2,
        CandidateEvaluationDisposition.EVALUATOR_PASS,
        parent_digest=first.evaluation_digest,
        evaluator_id="principal:independent-b",
        evidence_ref="artifact:sha256-custodied-proof-b",
    )
    reduction = PromotionPolicyV1().reduce(_candidate(), (first, second))
    assert reduction.disposition is CandidatePromotionDisposition.DEFER
    assert "EVIDENCE_BYTES_CUSTODY_UNPROVEN" in reduction.reason_codes
    assert "EVALUATOR_INDEPENDENCE_UNPROVEN" in reduction.reason_codes


def test_v1_spec_digest_and_registry_are_exact_and_immutable() -> None:
    policy = PromotionPolicyV1()
    assert policy.version == "ADM-P3-POLICY-V1"
    assert policy.digest == PROMOTION_POLICY_V1_DIGEST
    assert policy.digest == content_digest(PROMOTION_POLICY_V1_SPEC)

    registry = PromotionPolicyRegistry((policy,))
    assert registry.resolve(policy.version, policy.digest) is policy
    with pytest.raises(KeyError, match="not registered"):
        registry.resolve("unknown", policy.digest)
    with pytest.raises(KeyError, match="digest"):
        registry.resolve(policy.version, DIGEST_A)


def test_registry_rejects_duplicate_version_or_mutable_policy_identity() -> None:
    policy = PromotionPolicyV1()
    with pytest.raises(ValueError, match="duplicate"):
        PromotionPolicyRegistry((policy, PromotionPolicyV1()))

    class MutableIdentityPolicy:
        version = "test-mutable"
        digest = DIGEST_A

        def reduce(
            self,
            candidate: DomainCandidate,
            receipts: tuple[CandidateEvaluationReceipt, ...],
        ):  # type: ignore[no-untyped-def]
            del candidate, receipts
            return policy.reduce(_candidate(), ())

    mutable = MutableIdentityPolicy()
    registry = PromotionPolicyRegistry((mutable,))
    mutable.digest = DIGEST_B
    with pytest.raises(KeyError, match="digest"):
        registry.resolve("test-mutable", DIGEST_B)
