"""AWL-4 minimal adaptive-loop contracts (design section 5, plan section 5).

Contracts only: no Runtime consumption, no state updater, no evaluation
runner, no persistence seams. Each contract must round-trip, digest
deterministically, reject schema-version drift and enforce its named
fail-closed behavior.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    EdgeSpec,
    EnvironmentModelSnapshot,
    EvaluationBaseline,
    EvaluationContract,
    EvaluatorIdentity,
    HiddenSetManifest,
    NodeKind,
    NodeSpec,
    BeliefPatch,
    BeliefPatchOperation,
    BeliefRecord,
    BeliefStatus,
    OutcomeAttributionCandidate,
    OutcomeAttributionStatus,
    ProcedureCandidate,
    RollbackEffectReconciliation,
    RollbackReceipt,
    Uncertainty,
    WorkflowGraph,
    content_digest,
    procedure_candidate_digest,
    rollback_receipt_digest,
)


NOW = datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=1)

D1 = "1" * 64
D2 = "2" * 64
D3 = "3" * 64
D4 = "4" * 64
D5 = "5" * 64
D6 = "6" * 64
D7 = "7" * 64
D8 = "8" * 64


def _round_trip(model: object) -> object:
    payload = json.loads(
        json.dumps(
            model.model_dump(mode="json"),  # type: ignore[attr-defined]
            sort_keys=True,
        )
    )
    return type(model).model_validate(payload)  # type: ignore[attr-defined]


def _assert_version_drift_rejected(model: object) -> None:
    payload = model.model_dump(mode="json")  # type: ignore[attr-defined]
    payload["schema_version"] = "2.0"
    with pytest.raises(ValidationError):
        type(model).model_validate(payload)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# EnvironmentModelSnapshot
# ---------------------------------------------------------------------------


def _environment_snapshot(**overrides: object) -> EnvironmentModelSnapshot:
    from agent_os_contracts import (
        EnvironmentDynamic,
        EnvironmentEntity,
        EnvironmentRelation,
        EnvironmentSourceCoverage,
    )

    base: dict[str, object] = {
        "snapshot_id": "env-snap-1",
        "snapshot_version": 1,
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "task_id": "task-1",
        "entities": (
            EnvironmentEntity(
                entity_id="entity-1",
                entity_kind="service",
                state_digest=D1,
                observed_at=NOW,
            ),
            EnvironmentEntity(
                entity_id="entity-2",
                entity_kind="queue",
                state_digest=D2,
                observed_at=NOW,
            ),
        ),
        "relations": (
            EnvironmentRelation(
                subject_entity_id="entity-1",
                predicate="writes-to",
                object_entity_id="entity-2",
            ),
        ),
        "dynamics": (
            EnvironmentDynamic(
                dynamic_id="dyn-1",
                subject_entity_id="entity-2",
                change_kind="depth-growth",
                observed_at=NOW,
            ),
        ),
        "sources": (
            EnvironmentSourceCoverage(
                source_id="src-1",
                source_ref="probe://workspace",
                covered_entity_ids=("entity-1", "entity-2"),
                observed_at=NOW,
            ),
        ),
        "uncertainty": Uncertainty(confidence=0.5, reasons=("partial coverage",)),
        "captured_at": NOW,
        "valid_until": LATER,
    }
    base.update(overrides)
    return EnvironmentModelSnapshot(**base)  # type: ignore[arg-type]


def test_environment_model_snapshot_round_trip() -> None:
    snapshot = _environment_snapshot()
    assert _round_trip(snapshot) == snapshot


def test_environment_model_snapshot_digest_deterministic() -> None:
    snapshot = _environment_snapshot()
    assert snapshot.canonical_digest() == content_digest(snapshot)
    assert _round_trip(snapshot).canonical_digest() == snapshot.canonical_digest()  # type: ignore[attr-defined]


def test_environment_model_snapshot_rejects_version_drift() -> None:
    _assert_version_drift_rejected(_environment_snapshot())


def test_environment_model_snapshot_requires_fields() -> None:
    payload = _environment_snapshot().model_dump(mode="json")
    for field in ("snapshot_id", "entities", "sources", "valid_until"):
        missing = {key: value for key, value in payload.items() if key != field}
        with pytest.raises(ValidationError):
            EnvironmentModelSnapshot.model_validate(missing)


def test_environment_model_snapshot_rejects_stale_validity_window() -> None:
    with pytest.raises(ValidationError):
        _environment_snapshot(valid_until=NOW)


def test_environment_model_snapshot_rejects_unknown_relation_endpoint() -> None:
    from agent_os_contracts import EnvironmentRelation

    with pytest.raises(ValidationError):
        _environment_snapshot(
            relations=(
                EnvironmentRelation(
                    subject_entity_id="entity-1",
                    predicate="writes-to",
                    object_entity_id="ghost",
                ),
            )
        )


def test_environment_model_snapshot_rejects_unknown_provenance_coverage() -> None:
    from agent_os_contracts import EnvironmentSourceCoverage

    with pytest.raises(ValidationError):
        _environment_snapshot(
            sources=(
                EnvironmentSourceCoverage(
                    source_id="src-1",
                    source_ref="probe://workspace",
                    covered_entity_ids=("ghost",),
                    observed_at=NOW,
                ),
            )
        )


# ---------------------------------------------------------------------------
# BeliefRecord / BeliefPatch
# ---------------------------------------------------------------------------


def _belief_record(**overrides: object) -> BeliefRecord:
    base: dict[str, object] = {
        "belief_id": "belief-1",
        "belief_version": 1,
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "proposition": "queue depth grows under load",
        "confidence": 0.6,
        "provenance_refs": ("probe://run-1",),
        "valid_from": NOW,
        "recorded_at": NOW,
    }
    base.update(overrides)
    return BeliefRecord(**base)  # type: ignore[arg-type]


def test_belief_record_round_trip() -> None:
    record = _belief_record(status=BeliefStatus.CONTESTED, conflicting_belief_ids=("belief-2",))
    assert _round_trip(record) == record


def test_belief_record_digest_deterministic() -> None:
    record = _belief_record()
    assert content_digest(record) == content_digest(_round_trip(record))


def test_belief_record_rejects_version_drift() -> None:
    _assert_version_drift_rejected(_belief_record())


def test_belief_record_requires_fields() -> None:
    payload = _belief_record().model_dump(mode="json")
    for field in ("belief_id", "proposition", "confidence", "provenance_refs"):
        missing = {key: value for key, value in payload.items() if key != field}
        with pytest.raises(ValidationError):
            BeliefRecord.model_validate(missing)


def test_belief_record_never_converts_to_authority() -> None:
    payload = _belief_record().model_dump(mode="json")
    payload["authority"] = "EXECUTE"
    with pytest.raises(ValidationError):
        BeliefRecord.model_validate(payload)


def test_belief_record_contested_requires_preserved_conflict() -> None:
    with pytest.raises(ValidationError):
        _belief_record(status=BeliefStatus.CONTESTED)


def test_belief_record_rejects_inverted_validity_interval() -> None:
    with pytest.raises(ValidationError):
        _belief_record(valid_from=LATER, valid_until=NOW)


def _belief_patch(**overrides: object) -> BeliefPatch:
    base: dict[str, object] = {
        "patch_id": "patch-1",
        "base_snapshot_digest": D3,
        "base_snapshot_version": 4,
        "operations": (
            BeliefPatchOperation(
                operation_id="op-1",
                operation="ADD",
                belief=_belief_record(),
                grounding_refs=("evidence://run-2",),
            ),
            BeliefPatchOperation(
                operation_id="op-2",
                operation="INVALIDATE",
                target_belief_id="belief-0",
                target_belief_version=2,
                reason="superseded by newer probe",
                grounding_refs=("evidence://run-2",),
            ),
        ),
        "proposed_by": "state-updater-1",
        "proposed_at": NOW,
    }
    base.update(overrides)
    return BeliefPatch(**base)  # type: ignore[arg-type]


def test_belief_patch_round_trip() -> None:
    patch = _belief_patch()
    assert _round_trip(patch) == patch


def test_belief_patch_digest_deterministic() -> None:
    patch = _belief_patch()
    assert patch.canonical_digest() == content_digest(patch)
    assert _round_trip(patch).canonical_digest() == patch.canonical_digest()  # type: ignore[attr-defined]


def test_belief_patch_rejects_version_drift() -> None:
    _assert_version_drift_rejected(_belief_patch())


def test_belief_patch_requires_fields() -> None:
    payload = _belief_patch().model_dump(mode="json")
    for field in ("patch_id", "base_snapshot_digest", "base_snapshot_version", "operations"):
        missing = {key: value for key, value in payload.items() if key != field}
        with pytest.raises(ValidationError):
            BeliefPatch.model_validate(missing)


def test_belief_patch_rejects_ungrounded_mutation() -> None:
    with pytest.raises(ValidationError):
        BeliefPatchOperation(
            operation_id="op-x",
            operation="ADD",
            belief=_belief_record(),
            grounding_refs=(),
        )


def test_belief_patch_revise_requires_version_continuity() -> None:
    with pytest.raises(ValidationError):
        BeliefPatchOperation(
            operation_id="op-1",
            operation="REVISE",
            belief=_belief_record(belief_version=3),
            target_belief_id="belief-1",
            target_belief_version=1,
            reason="new evidence",
            grounding_refs=("evidence://run-3",),
        )


def test_belief_patch_invalidate_requires_reason_and_target() -> None:
    with pytest.raises(ValidationError):
        BeliefPatchOperation(
            operation_id="op-1",
            operation="INVALIDATE",
            target_belief_id="belief-1",
            target_belief_version=1,
            grounding_refs=("evidence://run-3",),
        )


def test_belief_patch_rejects_duplicate_operation_ids() -> None:
    operation = BeliefPatchOperation(
        operation_id="op-1",
        operation="ADD",
        belief=_belief_record(),
        grounding_refs=("evidence://run-2",),
    )
    with pytest.raises(ValidationError):
        _belief_patch(operations=(operation, operation))


# ---------------------------------------------------------------------------
# EvaluationContract
# ---------------------------------------------------------------------------


def _evaluator_identity() -> EvaluatorIdentity:
    return EvaluatorIdentity(
        evaluator_id="evaluator-1",
        principal_id="principal-eval",
        implementation_id="impl-1",
        implementation_version="1.0.0",
        config_artifact_ref="artifact://config",
        config_digest=D1,
        provider_id="provider-1",
        model_id="model-1",
        prompt_artifact_ref="artifact://prompt",
        prompt_digest=D2,
        checkpoint_artifact_ref="artifact://checkpoint",
        checkpoint_digest=D3,
    )


def _evaluation_contract(**overrides: object) -> EvaluationContract:
    base: dict[str, object] = {
        "contract_id": "eval-contract-1",
        "contract_version": 1,
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "case_set_ref": "artifact://case-set",
        "case_set_digest": D4,
        "metric_ids": ("accuracy", "regret"),
        "baselines": (
            EvaluationBaseline(
                baseline_id="baseline-1",
                artifact_ref="artifact://baseline-1",
                baseline_digest=D5,
            ),
        ),
        "oracle_boundary": "oracle sees hidden labels only; never candidate internals",
        "evaluator_identity": _evaluator_identity(),
        "hidden_set": HiddenSetManifest(
            manifest_id="hidden-1",
            manifest_version="1",
            artifact_ref="artifact://hidden",
            content_digest=D6,
            item_count=10,
        ),
        "frozen_at": NOW,
    }
    base.update(overrides)
    return EvaluationContract(**base)  # type: ignore[arg-type]


def test_evaluation_contract_round_trip() -> None:
    contract = _evaluation_contract()
    assert _round_trip(contract) == contract


def test_evaluation_contract_digest_deterministic() -> None:
    contract = _evaluation_contract()
    assert contract.canonical_digest() == content_digest(contract)
    assert _round_trip(contract).canonical_digest() == contract.canonical_digest()  # type: ignore[attr-defined]


def test_evaluation_contract_rejects_version_drift() -> None:
    _assert_version_drift_rejected(_evaluation_contract())


def test_evaluation_contract_requires_fields() -> None:
    payload = _evaluation_contract().model_dump(mode="json")
    for field in (
        "contract_id",
        "case_set_digest",
        "metric_ids",
        "baselines",
        "oracle_boundary",
        "evaluator_identity",
        "hidden_set",
    ):
        missing = {key: value for key, value in payload.items() if key != field}
        with pytest.raises(ValidationError):
            EvaluationContract.model_validate(missing)


def test_evaluation_contract_rejects_duplicate_baselines() -> None:
    baseline = EvaluationBaseline(
        baseline_id="baseline-1",
        artifact_ref="artifact://baseline-1",
        baseline_digest=D5,
    )
    with pytest.raises(ValidationError):
        _evaluation_contract(baselines=(baseline, baseline))


# ---------------------------------------------------------------------------
# OutcomeAttributionCandidate
# ---------------------------------------------------------------------------


def _attribution_candidate(**overrides: object) -> OutcomeAttributionCandidate:
    base: dict[str, object] = {
        "attribution_id": "attr-1",
        "attribution_version": 1,
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "task_id": "task-1",
        "run_id": "run-1",
        "observed_outcome_id": "outcome-1",
        "status": OutcomeAttributionStatus.IDENTIFIED,
        "subject_kind": "ACTION",
        "subject_ref": "step:patch",
        "hypothesis": "the patch step caused the verified outcome",
        "confidence": 0.4,
        "evidence_refs": ("evidence://trace-1",),
        "proposed_by": "evaluator-1",
        "proposed_at": NOW,
    }
    base.update(overrides)
    return OutcomeAttributionCandidate(**base)  # type: ignore[arg-type]


def test_outcome_attribution_candidate_round_trip() -> None:
    candidate = _attribution_candidate()
    assert _round_trip(candidate) == candidate


def test_outcome_attribution_candidate_digest_deterministic() -> None:
    candidate = _attribution_candidate()
    assert content_digest(candidate) == content_digest(_round_trip(candidate))


def test_outcome_attribution_candidate_rejects_version_drift() -> None:
    _assert_version_drift_rejected(_attribution_candidate())


def test_outcome_attribution_candidate_requires_fields() -> None:
    payload = _attribution_candidate().model_dump(mode="json")
    for field in ("attribution_id", "observed_outcome_id", "status", "run_id"):
        missing = {key: value for key, value in payload.items() if key != field}
        with pytest.raises(ValidationError):
            OutcomeAttributionCandidate.model_validate(missing)


def test_outcome_attribution_candidate_allows_unidentifiable() -> None:
    candidate = _attribution_candidate(
        status=OutcomeAttributionStatus.UNIDENTIFIABLE,
        subject_kind=None,
        subject_ref=None,
        hypothesis=None,
        confidence=0.0,
        evidence_refs=(),
        unidentifiable_reasons=("confounded changes in window",),
    )
    assert candidate.status is OutcomeAttributionStatus.UNIDENTIFIABLE


def test_outcome_attribution_candidate_unidentifiable_forbids_subject() -> None:
    with pytest.raises(ValidationError):
        _attribution_candidate(
            status=OutcomeAttributionStatus.UNIDENTIFIABLE,
            unidentifiable_reasons=("confounded changes",),
        )


def test_outcome_attribution_candidate_identified_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        _attribution_candidate(evidence_refs=())


def test_outcome_attribution_candidate_never_mutates_production_state() -> None:
    payload = _attribution_candidate().model_dump(mode="json")
    payload["production_mutation_authorized"] = True
    with pytest.raises(ValidationError):
        OutcomeAttributionCandidate.model_validate(payload)


# ---------------------------------------------------------------------------
# ProcedureCandidate
# ---------------------------------------------------------------------------


def _workflow() -> WorkflowGraph:
    return WorkflowGraph(
        workflow_id="workflow-1",
        version=2,
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        created_by="user-1",
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator-1",),
        nodes=(
            NodeSpec(node_id="verify", kind=NodeKind.EVALUATION),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(EdgeSpec(source="verify", target="done"),),
    )


def _procedure_candidate(**overrides: object) -> ProcedureCandidate:
    workflow = _workflow()
    base: dict[str, object] = {
        "candidate_id": "proc-candidate-1",
        "candidate_version": 1,
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "base_workflow_digest": D7,
        "proposed_workflow": workflow,
        "proposed_workflow_digest": workflow.canonical_digest(),
        "rationale": "add verification step before terminal",
        "evidence_refs": ("evidence://run-9",),
        "generating_task_id": "task-9",
        "generating_run_id": "run-9",
        "sealed_by": "candidate-sealer-1",
        "sealed_at": NOW,
    }
    base.update(overrides)
    draft = ProcedureCandidate.model_construct(**base)  # type: ignore[arg-type]
    digest = procedure_candidate_digest(
        draft.model_dump(mode="json", exclude={"candidate_digest"})
    )
    return ProcedureCandidate(**base, candidate_digest=digest)  # type: ignore[arg-type]


def test_procedure_candidate_round_trip() -> None:
    candidate = _procedure_candidate()
    assert _round_trip(candidate) == candidate


def test_procedure_candidate_digest_deterministic() -> None:
    candidate = _procedure_candidate()
    assert _round_trip(candidate).candidate_digest == candidate.candidate_digest  # type: ignore[attr-defined]


def test_procedure_candidate_rejects_version_drift() -> None:
    _assert_version_drift_rejected(_procedure_candidate())


def test_procedure_candidate_requires_fields() -> None:
    payload = _procedure_candidate().model_dump(mode="json")
    for field in (
        "candidate_id",
        "proposed_workflow",
        "proposed_workflow_digest",
        "generating_run_id",
        "sealed_by",
        "candidate_digest",
    ):
        missing = {key: value for key, value in payload.items() if key != field}
        with pytest.raises(ValidationError):
            ProcedureCandidate.model_validate(missing)


def test_procedure_candidate_rejects_workflow_digest_mismatch() -> None:
    with pytest.raises(ValidationError):
        _procedure_candidate(proposed_workflow_digest=D8)


def test_procedure_candidate_forbids_same_run_consumption() -> None:
    payload = _procedure_candidate().model_dump(mode="json")
    payload["same_run_consumption"] = "ALLOWED"
    with pytest.raises(ValidationError):
        ProcedureCandidate.model_validate(payload)


def test_procedure_candidate_rejects_scope_mismatched_workflow() -> None:
    workflow = _workflow().model_copy(update={"tenant_id": "tenant-2"})
    with pytest.raises(ValidationError):
        _procedure_candidate(
            proposed_workflow=workflow,
            proposed_workflow_digest=workflow.canonical_digest(),
        )


# ---------------------------------------------------------------------------
# RollbackReceipt
# ---------------------------------------------------------------------------


def _rollback_receipt(**overrides: object) -> RollbackReceipt:
    base: dict[str, object] = {
        "rollback_id": "rollback-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "candidate_digest": D7,
        "promotion_digest": D8,
        "action_ref": "action://disable-candidate",
        "action_digest": D1,
        "effects": (
            RollbackEffectReconciliation(
                effect_ref="effect-1",
                status="RESOLVED",
                detail="prior version restored",
            ),
        ),
        "resulting_candidate_state": "DISABLED",
        "executed_by": "operator-1",
        "executed_at": NOW,
    }
    base.update(overrides)
    draft = RollbackReceipt.model_construct(**base)  # type: ignore[arg-type]
    digest = rollback_receipt_digest(
        draft.model_dump(mode="json", exclude={"rollback_digest"})
    )
    return RollbackReceipt(**base, rollback_digest=digest)  # type: ignore[arg-type]


def test_rollback_receipt_round_trip() -> None:
    receipt = _rollback_receipt()
    assert _round_trip(receipt) == receipt


def test_rollback_receipt_digest_deterministic() -> None:
    receipt = _rollback_receipt()
    assert _round_trip(receipt).rollback_digest == receipt.rollback_digest  # type: ignore[attr-defined]


def test_rollback_receipt_rejects_version_drift() -> None:
    _assert_version_drift_rejected(_rollback_receipt())


def test_rollback_receipt_requires_fields() -> None:
    payload = _rollback_receipt().model_dump(mode="json")
    for field in (
        "rollback_id",
        "candidate_digest",
        "promotion_digest",
        "action_digest",
        "effects",
        "resulting_candidate_state",
        "rollback_digest",
    ):
        missing = {key: value for key, value in payload.items() if key != field}
        with pytest.raises(ValidationError):
            RollbackReceipt.model_validate(missing)


def test_rollback_receipt_unresolved_effects_keep_candidate_disabled() -> None:
    with pytest.raises(ValidationError):
        _rollback_receipt(
            effects=(
                RollbackEffectReconciliation(
                    effect_ref="effect-1",
                    status="UNRESOLVED",
                    detail="workspace file still mutated",
                ),
            ),
            resulting_candidate_state="ACTIVE",
        )


def test_rollback_receipt_rejects_duplicate_effects() -> None:
    effect = RollbackEffectReconciliation(
        effect_ref="effect-1",
        status="RESOLVED",
        detail="restored",
    )
    with pytest.raises(ValidationError):
        _rollback_receipt(effects=(effect, effect))


# ---------------------------------------------------------------------------
# Boundary: os_core must not import AWL-4 loop contracts
# ---------------------------------------------------------------------------

AWL4_CONTRACT_NAMES = (
    "EnvironmentModelSnapshot",
    "BeliefRecord",
    "BeliefPatch",
    "EvaluationContract",
    "OutcomeAttributionCandidate",
    "ProcedureCandidate",
    "RollbackReceipt",
)


def test_os_core_does_not_import_awl4_loop_contracts() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    os_core_src = repo_root / "packages" / "os_core" / "src"
    offenders: list[str] = []
    for path in sorted(os_core_src.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for name in AWL4_CONTRACT_NAMES:
            if name in text:
                offenders.append(f"{path.relative_to(repo_root)}: {name}")
    assert not offenders, "os_core must not reference AWL-4 loop contracts"
