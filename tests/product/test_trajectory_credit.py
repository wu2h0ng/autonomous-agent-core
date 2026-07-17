from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    CreditAssignment,
    CreditMethod,
    CreditUncertainty,
    CreditUncertaintyKind,
    TaskEventDraft,
    TaskEventType,
)
from agent_os_core.errors import (
    DuplicateEventError,
    EventStreamError,
    ScopeMismatchError,
)
from agent_os_core.event_store import InMemoryTaskEventStore
from agent_os_core.trajectory import CreditLedger, TrajectoryProjector


NOW = datetime(2026, 7, 17, tzinfo=timezone.utc)


def _append(
    store: InMemoryTaskEventStore,
    event_type: TaskEventType,
    payload: dict[str, object],
    *,
    event_id: str,
    task_id: str = "task-1",
    correlation_id: str = "run-1",
) -> None:
    sequence = len(store.read(task_id))
    store.append(
        task_id,
        expected_sequence=sequence,
        drafts=(
            TaskEventDraft.build(
                event_id=event_id,
                task_id=task_id,
                event_type=event_type,
                payload=payload,
                occurred_at=NOW,
                correlation_id=correlation_id,
            ),
        ),
    )


def _event_store() -> InMemoryTaskEventStore:
    store = InMemoryTaskEventStore()
    _append(
        store,
        TaskEventType.TASK_CREATED,
        {"goal": {"goal_id": "goal-1"}},
        event_id="event-1",
        correlation_id="task-1",
    )
    _append(
        store,
        TaskEventType.TASK_COMMITTED,
        {
            "workflow_digest": "a" * 64,
            "workflow": {"workflow_id": "workflow-1", "version": 1},
        },
        event_id="event-2",
        correlation_id="task-1",
    )
    _append(
        store,
        TaskEventType.RUN_STARTED,
        {
            "run": {
                "run_id": "run-1",
                "task_id": "task-1",
                "tenant_id": "tenant-1",
                "workspace_id": "workspace-1",
                "workflow_id": "workflow-1",
                "workflow_version": 1,
                "workflow_digest": "a" * 64,
                "provider_profile_id": "profile-1",
                "policy_version": "policy-1",
            }
        },
        event_id="event-3",
        correlation_id="task-1",
    )
    _append(
        store,
        TaskEventType.PROVIDER_RESPONDED,
        {"node_id": "reason", "provider_output": {"text": "candidate"}},
        event_id="event-4",
    )
    _append(
        store,
        TaskEventType.NODE_FAILED,
        {"node_id": "tool", "error": "TimeoutError"},
        event_id="event-5",
    )
    return store


def test_projector_is_deterministic_and_includes_failure_events() -> None:
    store = _event_store()
    first = TrajectoryProjector().project(store, "task-1", "run-1")
    second = TrajectoryProjector().project(store, "task-1", "run-1")

    assert first.trajectory_digest == second.trajectory_digest
    assert tuple(step.event_type for step in first.steps)[-1] == "NODE_FAILED"
    assert first.steps[-1].event_digest != first.steps[-2].event_digest

    changed = _event_store()
    _append(
        changed,
        TaskEventType.RUN_FAILED,
        {"error": "late failure"},
        event_id="event-6",
    )
    changed_episode = TrajectoryProjector().project(changed, "task-1", "run-1")
    assert changed_episode.trajectory_digest != first.trajectory_digest
    assert changed_episode.steps[: len(first.steps)] == first.steps


def test_projector_records_missing_bindings_as_gaps_without_fabrication() -> None:
    episode = TrajectoryProjector().project(_event_store(), "task-1", "run-1")

    assert episode.manifest.workflow_digest == "a" * 64
    assert episode.manifest.policy_version == "policy-1"
    assert episode.manifest.correction_epoch_status.value == "MISSING"
    assert episode.manifest.working_set_ref.status.value == "MISSING"
    invocation = episode.steps[3].model_invocation
    assert invocation is not None
    assert invocation.provider_profile_id == "profile-1"
    assert invocation.provider_id is None
    assert "provider_id" in invocation.missing_fields
    assert "model_id" in invocation.missing_fields
    assert "provider_profile_digest" in invocation.missing_fields
    assert "model_revision_digest" in invocation.missing_fields


@pytest.mark.parametrize(
    ("field", "value"),
    (("tenant_id", "tenant-2"), ("workspace_id", "workspace-2"), ("run_id", "run-2")),
)
def test_projector_rejects_scope_confusion(field: str, value: str) -> None:
    store = _event_store()
    payload: dict[str, object] = {
        "outcome": {
            "observed_outcome_id": "outcome-1",
            "task_id": "task-1",
            "run_id": "run-1",
            "tenant_id": "tenant-1",
            "workspace_id": "workspace-1",
            "status": "NOT_MET",
        }
    }
    outcome = payload["outcome"]
    assert isinstance(outcome, dict)
    outcome[field] = value
    _append(store, TaskEventType.OUTCOME_OBSERVED, payload, event_id="event-6")

    with pytest.raises(ScopeMismatchError):
        TrajectoryProjector().project(store, "task-1", "run-1")


def test_projector_rejects_correction_epoch_confusion() -> None:
    store = _event_store()
    _append(
        store,
        TaskEventType.CORRECTION_WRITTEN,
        {
            "correction": {
                "correction_id": "correction-1",
                "task_id": "task-1",
                "run_id": "run-1",
                "tenant_id": "tenant-1",
                "workspace_id": "workspace-1",
                "epoch": 2,
            }
        },
        event_id="event-6",
    )
    _append(
        store,
        TaskEventType.ACTION_PROPOSED,
        {
            "action": {
                "task_id": "task-1",
                "run_id": "run-1",
                "tenant_id": "tenant-1",
                "workspace_id": "workspace-1",
                "observed_correction_epochs": {
                    "task_epoch": 1,
                    "run_epoch": 0,
                    "capability_epoch": 0,
                },
            }
        },
        event_id="event-7",
    )

    with pytest.raises(ScopeMismatchError, match="correction epoch"):
        TrajectoryProjector().project(store, "task-1", "run-1")


def test_projector_reads_the_existing_flat_correction_event_shape() -> None:
    store = _event_store()
    _append(
        store,
        TaskEventType.CORRECTION_WRITTEN,
        {
            "scope": "TASK",
            "epoch": 2,
            "halted": False,
            "reason": "resume",
            "written_by": "principal-1",
        },
        event_id="event-6",
    )

    episode = TrajectoryProjector().project(store, "task-1", "run-1")
    assert episode.manifest.correction_epoch == 2
    assert episode.correction_links[0].epoch == 2
    assert episode.correction_links[0].correction_id == "correction:event-6"


def test_delayed_outcome_appends_link_without_mutating_prior_steps() -> None:
    store = _event_store()
    before = TrajectoryProjector().project(store, "task-1", "run-1")
    _append(
        store,
        TaskEventType.OUTCOME_OBSERVED,
        {
            "outcome": {
                "observed_outcome_id": "outcome-late",
                "task_id": "task-1",
                "run_id": "run-1",
                "tenant_id": "tenant-1",
                "workspace_id": "workspace-1",
                "status": "NOT_MET",
                "evidence_refs": ["evidence-1"],
            }
        },
        event_id="event-6",
    )
    after = TrajectoryProjector().project(store, "task-1", "run-1")

    assert after.steps[: len(before.steps)] == before.steps
    assert after.outcome_links[0].source_event_id == "event-6"
    assert after.outcome_links[0].linked_step_ids == tuple(
        step.step_id for step in before.steps
    )


def test_capability_projection_exposes_missing_tool_and_receipt_bindings() -> None:
    store = _event_store()
    _append(
        store,
        TaskEventType.ACTION_PROPOSED,
        {
            "action": {
                "task_id": "task-1",
                "run_id": "run-1",
                "tenant_id": "tenant-1",
                "workspace_id": "workspace-1",
                "capability_id": "workspace.patch",
                "action_id": "action-1",
            }
        },
        event_id="event-6",
    )

    episode = TrajectoryProjector().project(store, "task-1", "run-1")
    invocation = episode.steps[-1].capability_invocation
    assert invocation is not None
    assert invocation.capability_id == "workspace.patch"
    assert invocation.policy_version == "policy-1"
    assert invocation.policy_digest is None
    assert "capability_version" in invocation.missing_fields
    assert "capability_spec_digest" in invocation.missing_fields
    assert "policy_digest" in invocation.missing_fields
    assert "receipt_id" in invocation.missing_fields
    assert invocation.receipt_digest is None


def test_manifest_marks_workflow_and_policy_gaps_instead_of_using_defaults() -> None:
    store = InMemoryTaskEventStore()
    _append(
        store,
        TaskEventType.RUN_STARTED,
        {
            "run": {
                "run_id": "run-1",
                "task_id": "task-1",
                "tenant_id": "tenant-1",
                "workspace_id": "workspace-1",
            }
        },
        event_id="event-1",
        correlation_id="task-1",
    )

    episode = TrajectoryProjector().project(store, "task-1", "run-1")
    assert episode.manifest.workflow_status.value == "MISSING"
    assert episode.manifest.policy_status.value == "MISSING"
    assert "workflow_digest" in episode.manifest.missing_bindings
    assert "policy_version" in episode.manifest.missing_bindings


def test_policy_version_alone_does_not_fabricate_a_policy_digest() -> None:
    episode = TrajectoryProjector().project(_event_store(), "task-1", "run-1")

    assert episode.manifest.policy_version == "policy-1"
    assert episode.manifest.policy_digest is None
    assert episode.manifest.policy_status.value == "MISSING"
    assert "policy_digest" in episode.manifest.missing_bindings


def test_credit_requires_causal_evidence_for_deterministic_claim() -> None:
    uncertainty = CreditUncertainty(
        kind=CreditUncertaintyKind.NONE,
        confidence=1.0,
        reasons=(),
    )
    with pytest.raises(ValidationError, match="causal evidence"):
        CreditAssignment(
            credit_id="credit-1",
            episode_digest="a" * 64,
            tenant_id="tenant-1",
            workspace_id="workspace-1",
            task_id="task-1",
            run_id="run-1",
            correction_epoch=0,
            target_step_ids=("step-1",),
            method=CreditMethod.COUNTERFACTUAL,
            value=1.0,
            evidence_refs=(),
            uncertainty=uncertainty,
            assigned_at=NOW,
        )


def _credit(credit_id: str = "credit-1") -> CreditAssignment:
    return CreditAssignment(
        credit_id=credit_id,
        episode_digest="a" * 64,
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        task_id="task-1",
        run_id="run-1",
        correction_epoch=0,
        target_step_ids=("step-1",),
        method=CreditMethod.ASSOCIATIONAL,
        value=0.2,
        evidence_refs=("outcome-1",),
        uncertainty=CreditUncertainty(
            kind=CreditUncertaintyKind.HIGH,
            confidence=0.2,
            reasons=("no intervention",),
        ),
        assigned_at=NOW,
    )


def test_credit_ledger_is_append_only_and_rejects_replay_or_overwrite() -> None:
    ledger = CreditLedger()
    recorded = ledger.append(_credit())
    assert ledger.read("credit-1") == recorded

    with pytest.raises(DuplicateEventError):
        ledger.append(_credit())
    with pytest.raises(DuplicateEventError):
        ledger.append(_credit().model_copy(update={"value": 0.9}))


def test_credit_ledger_detects_storage_overwrite_on_read() -> None:
    ledger = CreditLedger()
    ledger.append(_credit())
    ledger._db.execute(
        "UPDATE credit_assignments SET assignment_json = ? WHERE credit_id = ?",
        (_credit().model_copy(update={"value": 0.9}).model_dump_json(), "credit-1"),
    )
    ledger._db.commit()

    with pytest.raises(EventStreamError, match="digest mismatch"):
        ledger.read("credit-1")


def test_credit_has_no_authority_fields_or_mutation_methods() -> None:
    with pytest.raises(ValidationError):
        CreditAssignment.model_validate(
            {
                **_credit().model_dump(mode="json"),
                "policy_version": "attacker-policy",
                "capability_grant_id": "attacker-grant",
                "evaluator_version": "attacker-evaluator",
                "task_status": "COMPLETED",
            }
        )
    ledger = CreditLedger()
    assert not hasattr(ledger, "update")
    assert not hasattr(ledger, "delete")
