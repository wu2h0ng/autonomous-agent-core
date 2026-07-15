from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from agent_os_contracts import (
    CapabilityGrant,
    CapabilityGrantStatus,
    Commitment,
    CorrectionEpochVector,
    EdgeSpec,
    ExpectedOutcome,
    Goal,
    NodeKind,
    NodeSpec,
    ProviderProfile,
    ResourceBudget,
    RunStatus,
    TaskConfigurationSnapshot,
    TaskConfigurationSnapshotCommand,
    TaskEventType,
    TaskStatus,
    WorkflowGraph,
    content_digest,
    task_configuration_grants_digest,
    task_configuration_seal_request_digest,
    task_configuration_snapshot_digest,
)
from agent_os_core import (
    POLICY_KERNEL_V1_DIGEST,
    InMemoryTaskEventStore,
    InvalidTransitionError,
    TaskService,
)


NOW = datetime(2026, 7, 15, 19, 0, tzinfo=timezone.utc)


def _budget() -> ResourceBudget:
    return ResourceBudget(
        max_cost_usd=Decimal("1"),
        max_duration_seconds=300,
        max_provider_tokens=0,
        max_tool_calls=10,
    )


def _service() -> TaskService:
    counters: dict[str, int] = {}

    def next_id(kind: str) -> str:
        counters[kind] = counters.get(kind, 0) + 1
        return f"{kind}:{counters[kind]}"

    return TaskService(
        InMemoryTaskEventStore(),
        id_factory=next_id,
        clock=lambda: NOW,
    )


def _committed_task(service: TaskService):  # type: ignore[no-untyped-def]
    goal = Goal(
        goal_id="goal:consumer",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        created_by="principal:consumer",
        created_at=NOW,
        statement="consume an immutable configuration",
    )
    created = service.create_task(goal)
    workflow = WorkflowGraph(
        workflow_id="workflow:consumer",
        version=1,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        created_by=goal.created_by,
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=(
            NodeSpec(
                node_id="read",
                kind=NodeKind.TOOL,
                capability="workspace.read",
            ),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(EdgeSpec(source="read", target="done"),),
    )
    commitment = Commitment(
        commitment_id="commitment:consumer",
        task_id=created.task_id,
        goal_id=goal.goal_id,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        accepted_by=goal.created_by,
        accepted_at=NOW,
        deliverables=("result",),
        acceptance_criteria=("verified",),
        authority_scopes=("task.configuration.snapshot", "workspace.read"),
        budget=_budget(),
        risk_tier=1,
        exit_conditions=("done",),
        expires_at=NOW + timedelta(hours=1),
    )
    expected = ExpectedOutcome(
        expected_outcome_id="outcome:consumer",
        task_id=created.task_id,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("NOT_MET",),
        threshold=1.0,
        observation_window_seconds=300,
        frozen_at=NOW,
    )
    return service.commit_task(created.task_id, commitment, workflow, expected)


def _snapshot(task) -> TaskConfigurationSnapshot:  # type: ignore[no-untyped-def]
    assert task.workflow is not None
    assert task.expected_outcome is not None
    assert task.commitment is not None
    provider = ProviderProfile(
        profile_id="provider-profile:consumer",
        provider_id="deterministic",
        model_id="deterministic-v1",
        endpoint_class="test",
        credential_ref_id="credential:none",
        capabilities=("chat",),
        max_context_tokens=16_000,
        request_timeout_seconds=60,
        created_at=NOW,
    )
    grant = CapabilityGrant(
        grant_id="grant:workspace.read",
        principal_id="principal:consumer",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        capability_id="workspace.read",
        capability_version="1",
        max_risk_tier=1,
        budget_limit=_budget(),
        status=CapabilityGrantStatus.ACTIVE,
        granted_by="system",
        granted_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )
    grants = (grant,)
    command = TaskConfigurationSnapshotCommand()
    payload = {
        "snapshot_id": "task-configuration:consumer",
        "snapshot_version": 1,
        "seal_request_digest": task_configuration_seal_request_digest(
            task.task_id, command
        ),
        "consumer_task_id": task.task_id,
        "reserved_run_id": "run:reserved",
        "commitment_id": task.commitment.commitment_id,
        "tenant_id": task.commitment.tenant_id,
        "workspace_id": task.commitment.workspace_id,
        "principal_id": "principal:consumer",
        "workflow": task.workflow,
        "workflow_digest": task.workflow.canonical_digest(),
        "policy_version": task.workflow.policy_version,
        "policy_digest": POLICY_KERNEL_V1_DIGEST,
        "provider_profile": provider,
        "provider_profile_digest": content_digest(provider),
        "execution_grants": grants,
        "execution_grants_digest": task_configuration_grants_digest(grants),
        "expected_outcome": task.expected_outcome,
        "expected_outcome_digest": content_digest(task.expected_outcome),
        "observed_correction_epochs": CorrectionEpochVector(
            task_epoch=0,
            run_epoch=0,
            capability_epoch=0,
        ),
        "optional_prior": None,
        "sealed_by": "system:task-configuration-sealer:v1",
        "sealed_at": NOW,
        "state": "SEALED",
        "prior_consumption_mode": "REFERENCE_ONLY",
    }
    return TaskConfigurationSnapshot(
        **payload,
        snapshot_digest=task_configuration_snapshot_digest(payload),
    )


def test_snapshot_event_keeps_task_committed_and_rehydrates_exact_bytes() -> None:
    service = _service()
    committed = _committed_task(service)
    snapshot = _snapshot(committed)

    sealed = service.seal_configuration_snapshot(committed.task_id, snapshot)

    assert sealed.status is TaskStatus.COMMITTED
    assert sealed.configuration_snapshot == snapshot
    assert service._event_store.read(committed.task_id)[-1].event_type is (
        TaskEventType.TASK_CONFIGURATION_SNAPSHOT_SEALED
    )
    assert service.get_task(committed.task_id).configuration_snapshot == snapshot


def test_snapshot_bound_run_requires_exact_id_and_uses_reserved_run() -> None:
    service = _service()
    committed = _committed_task(service)
    snapshot = _snapshot(committed)
    service.seal_configuration_snapshot(committed.task_id, snapshot)

    with pytest.raises(InvalidTransitionError, match="configuration snapshot"):
        service.start_run(committed.task_id)
    with pytest.raises(InvalidTransitionError, match="configuration snapshot"):
        service.start_run(
            committed.task_id,
            configuration_snapshot_id="task-configuration:wrong",
        )

    started = service.start_run(
        committed.task_id,
        configuration_snapshot_id=snapshot.snapshot_id,
    )

    assert started.run is not None
    assert started.run.run_id == snapshot.reserved_run_id
    assert started.run.configuration_snapshot_id == snapshot.snapshot_id
    assert started.run.configuration_snapshot_digest == snapshot.snapshot_digest
    assert started.run.status is RunStatus.QUEUED


def test_snapshot_cannot_be_sealed_after_run_start() -> None:
    service = _service()
    committed = _committed_task(service)
    snapshot = _snapshot(committed)
    service.start_run(committed.task_id)

    with pytest.raises(InvalidTransitionError):
        service.seal_configuration_snapshot(committed.task_id, snapshot)
