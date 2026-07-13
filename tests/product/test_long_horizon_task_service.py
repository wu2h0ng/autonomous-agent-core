from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from agent_os_contracts import (
    Commitment,
    EdgeSpec,
    ExpectedOutcome,
    ExternalSignal,
    Goal,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    ResourceBudget,
    RunStatus,
    TaskEventType,
    TaskStatus,
    WorkflowGraph,
)
from agent_os_core import (
    CommitmentExpiredError,
    InMemoryTaskEventStore,
    ReplanRejectedError,
    SignalMismatchError,
    TaskService,
    WaitExpiredError,
)


NOW = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)


class DeterministicIdFactory:
    def __init__(self) -> None:
        self._counts: defaultdict[str, int] = defaultdict(int)

    def __call__(self, kind: str) -> str:
        self._counts[kind] += 1
        return f"{kind}-{self._counts[kind]}"


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class SecondReadHookStore(InMemoryTaskEventStore):
    def __init__(self) -> None:
        super().__init__()
        self.read_count = 0
        self.on_second_read: object | None = None

    def read(self, task_id: str):  # type: ignore[no-untyped-def]
        self.read_count += 1
        if self.read_count == 2 and callable(self.on_second_read):
            hook = self.on_second_read
            self.on_second_read = None
            hook()
        return super().read(task_id)


def _goal() -> Goal:
    return Goal(
        goal_id="goal:long",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=NOW,
        statement="wait for a build and continue",
    )


def _commitment(task_id: str, *, expires_at: datetime | None = None) -> Commitment:
    return Commitment(
        commitment_id="commitment:long",
        task_id=task_id,
        goal_id="goal:long",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        accepted_by="user:local",
        accepted_at=NOW,
        deliverables=("verified change",),
        acceptance_criteria=("pytest passes",),
        authority_scopes=("workspace:read", "workspace:write"),
        budget=ResourceBudget(
            max_cost_usd=Decimal("1"),
            max_duration_seconds=3600,
            max_provider_tokens=1000,
            max_tool_calls=10,
        ),
        risk_tier=1,
        exit_conditions=("verified",),
        expires_at=expires_at or NOW + timedelta(hours=1),
    )


def _wait_node(*, timeout_seconds: int = 120) -> NodeSpec:
    return NodeSpec(
        node_id="wait",
        kind=NodeKind.WAIT_EVENT,
        wait_signal_name="build.finished",
        wait_correlation_key="build:7",
        timeout_seconds=timeout_seconds,
    )


def _workflow(
    *, version: int = 1, max_replans: int = 1, wait_timeout_seconds: int = 120
) -> WorkflowGraph:
    read = NodeSpec(
        node_id="read",
        kind=NodeKind.TOOL,
        capability="workspace.read",
        idempotency=IdempotencyMode.IDEMPOTENT,
    )
    wait = _wait_node(timeout_seconds=wait_timeout_seconds)
    done = NodeSpec(node_id="done", kind=NodeKind.TERMINAL)
    return WorkflowGraph(
        workflow_id="workflow:long",
        version=version,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=(read, wait, done),
        edges=(
            EdgeSpec(source="read", target="wait"),
            EdgeSpec(source="wait", target="done"),
        ),
        max_replans=max_replans,
    )


def _replanned_workflow(*, version: int = 2, max_replans: int = 1) -> WorkflowGraph:
    read = NodeSpec(
        node_id="read",
        kind=NodeKind.TOOL,
        capability="workspace.read",
        idempotency=IdempotencyMode.IDEMPOTENT,
    )
    inspect = NodeSpec(node_id="inspect", kind=NodeKind.TRANSFORM)
    done = NodeSpec(node_id="done", kind=NodeKind.TERMINAL)
    return WorkflowGraph(
        workflow_id="workflow:long",
        version=version,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=(read, inspect, done),
        edges=(
            EdgeSpec(source="read", target="inspect"),
            EdgeSpec(source="inspect", target="done"),
        ),
        max_replans=max_replans,
    )


def _expected(task_id: str) -> ExpectedOutcome:
    return ExpectedOutcome(
        expected_outcome_id="expected:long",
        task_id=task_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("non-zero exit",),
        threshold=1.0,
        observation_window_seconds=60,
        frozen_at=NOW,
    )


def _signal(task_id: str, run_id: str, **changes: object) -> ExternalSignal:
    values: dict[str, object] = {
        "signal_id": "signal:7",
        "task_id": task_id,
        "run_id": run_id,
        "tenant_id": "tenant:local",
        "workspace_id": "workspace:local",
        "signal_name": "build.finished",
        "correlation_key": "build:7",
        "payload_json": '{"status":"passed"}',
        "evidence_refs": ("artifact:build-7",),
        "occurred_at": NOW + timedelta(seconds=10),
    }
    values.update(changes)
    return ExternalSignal.model_validate(values)


def _running_service(
    *,
    clock: MutableClock | None = None,
    expires_at: datetime | None = None,
    wait_timeout_seconds: int = 120,
) -> tuple[TaskService, InMemoryTaskEventStore, str]:
    store = InMemoryTaskEventStore()
    service = TaskService(
        store,
        id_factory=DeterministicIdFactory(),
        clock=clock or MutableClock(NOW),
    )
    task = service.create_task(_goal())
    service.commit_task(
        task.task_id,
        _commitment(task.task_id, expires_at=expires_at),
        _workflow(wait_timeout_seconds=wait_timeout_seconds),
        _expected(task.task_id),
    )
    service.start_run(task.task_id)
    service.update_run_status(
        task.task_id,
        RunStatus.RUNNING,
        event_type=TaskEventType.RUN_QUEUED,
    )
    return service, store, task.task_id


def test_register_wait_sets_task_and_run_waiting() -> None:
    service, store, task_id = _running_service()

    result = service.register_wait(task_id, _wait_node())

    assert result.status is TaskStatus.WAITING
    assert result.run is not None
    assert result.run.status is RunStatus.WAITING_EVENT
    assert result.run.wait_condition is not None
    assert result.run.wait_condition.deadline == NOW + timedelta(seconds=120)
    assert store.read(task_id)[-1].event_type is TaskEventType.WAIT_REGISTERED


def test_wait_deadline_is_capped_by_immutable_commitment_expiry() -> None:
    service, _, task_id = _running_service(expires_at=NOW + timedelta(seconds=30))

    result = service.register_wait(task_id, _wait_node(timeout_seconds=120))

    assert result.run is not None
    assert result.run.wait_condition is not None
    assert result.run.wait_condition.deadline == NOW + timedelta(seconds=30)


def test_record_signal_atomically_satisfies_wait_and_completes_node() -> None:
    service, store, task_id = _running_service()
    waiting = service.register_wait(task_id, _wait_node())
    assert waiting.run is not None

    result = service.record_signal(task_id, _signal(task_id, waiting.run.run_id))

    assert result.status is TaskStatus.RUNNING
    assert result.run is not None
    assert result.run.status is RunStatus.RUNNING
    assert result.run.wait_condition is None
    assert [event.event_type for event in store.read(task_id)][-3:] == [
        TaskEventType.EXTERNAL_SIGNAL_RECORDED,
        TaskEventType.WAIT_SATISFIED,
        TaskEventType.NODE_COMPLETED,
    ]


def test_duplicate_signal_is_idempotent_after_wait_is_satisfied() -> None:
    service, _, task_id = _running_service()
    waiting = service.register_wait(task_id, _wait_node())
    assert waiting.run is not None
    signal = _signal(task_id, waiting.run.run_id)

    first = service.record_signal(task_id, signal)
    second = service.record_signal(task_id, signal)

    assert second.sequence == first.sequence


def test_wrong_signal_fails_without_persistence() -> None:
    service, store, task_id = _running_service()
    waiting = service.register_wait(task_id, _wait_node())
    assert waiting.run is not None
    before = len(store.read(task_id))

    with pytest.raises(SignalMismatchError, match="correlation"):
        service.record_signal(
            task_id,
            _signal(task_id, waiting.run.run_id, correlation_key="build:other"),
        )

    assert len(store.read(task_id)) == before


def test_late_signal_records_timeout_and_cannot_revive_wait() -> None:
    clock = MutableClock(NOW)
    service, store, task_id = _running_service(clock=clock, wait_timeout_seconds=10)
    waiting = service.register_wait(task_id, _wait_node(timeout_seconds=10))
    assert waiting.run is not None
    clock.value = NOW + timedelta(seconds=11)

    with pytest.raises(WaitExpiredError):
        service.record_signal(task_id, _signal(task_id, waiting.run.run_id))

    result = service.get_task(task_id)
    assert result.status is TaskStatus.FAILED
    assert result.run is not None
    assert result.run.status is RunStatus.FAILED
    assert store.read(task_id)[-1].event_type is TaskEventType.WAIT_TIMED_OUT


def test_expired_commitment_cannot_start_run() -> None:
    clock = MutableClock(NOW)
    store = InMemoryTaskEventStore()
    service = TaskService(store, id_factory=DeterministicIdFactory(), clock=clock)
    task = service.create_task(_goal())
    service.commit_task(
        task.task_id,
        _commitment(task.task_id, expires_at=NOW + timedelta(seconds=5)),
        _workflow(),
        _expected(task.task_id),
    )
    clock.value = NOW + timedelta(seconds=6)

    with pytest.raises(CommitmentExpiredError):
        service.start_run(task.task_id)

    assert len(store.read(task.task_id)) == 2


def test_replan_rebinds_only_uncompleted_suffix() -> None:
    service, store, task_id = _running_service()
    service.append_event(
        task_id,
        TaskEventType.NODE_COMPLETED,
        {"node_id": "read", "output": {"path": "fixture.txt"}},
    )
    service.register_wait(task_id, _wait_node())

    result = service.replan_task(
        task_id,
        _replanned_workflow(),
        requested_by="user:local",
        reason="replace the blocked suffix",
    )

    assert result.status is TaskStatus.PAUSED
    assert result.workflow is not None
    assert result.workflow.version == 2
    assert result.run is not None
    assert result.run.status is RunStatus.PAUSED
    assert result.run.replan_count == 1
    assert result.run.wait_condition is None
    assert store.read(task_id)[-1].event_type is TaskEventType.RUN_PLAN_REBOUND


def test_replan_rejects_completed_node_change() -> None:
    service, _, task_id = _running_service()
    service.append_event(task_id, TaskEventType.NODE_COMPLETED, {"node_id": "read"})
    service.register_wait(task_id, _wait_node())
    changed = _replanned_workflow().model_copy(
        update={
            "nodes": (
                NodeSpec(
                    node_id="read",
                    kind=NodeKind.TOOL,
                    capability="artifact.write",
                    idempotency=IdempotencyMode.IDEMPOTENT,
                ),
                NodeSpec(node_id="inspect", kind=NodeKind.TRANSFORM),
                NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
            )
        }
    )

    with pytest.raises(ReplanRejectedError, match="completed node"):
        service.replan_task(
            task_id,
            changed,
            requested_by="user:local",
            reason="unsafe rewrite",
        )


def test_replan_cannot_raise_budget_or_run_twice() -> None:
    service, _, task_id = _running_service()
    service.append_event(task_id, TaskEventType.NODE_COMPLETED, {"node_id": "read"})
    service.register_wait(task_id, _wait_node())

    with pytest.raises(ReplanRejectedError, match="max_replans"):
        service.replan_task(
            task_id,
            _replanned_workflow(max_replans=2),
            requested_by="user:local",
            reason="raise the budget",
        )

    service.replan_task(
        task_id,
        _replanned_workflow(),
        requested_by="user:local",
        reason="one allowed replan",
    )
    with pytest.raises(ReplanRejectedError, match="budget exhausted"):
        service.replan_task(
            task_id,
            _replanned_workflow(version=3),
            requested_by="user:local",
            reason="second replan",
        )


def test_status_update_cannot_append_stale_run_after_concurrent_rebind() -> None:
    store = SecondReadHookStore()
    service = TaskService(
        store,
        id_factory=DeterministicIdFactory(),
        clock=MutableClock(NOW),
    )
    task = service.create_task(_goal())
    service.commit_task(
        task.task_id,
        _commitment(task.task_id),
        _workflow(),
        _expected(task.task_id),
    )
    service.start_run(task.task_id)
    service.update_run_status(
        task.task_id,
        RunStatus.RUNNING,
        event_type=TaskEventType.RUN_QUEUED,
    )
    service.register_wait(task.task_id, _wait_node())
    store.read_count = 0
    store.on_second_read = lambda: service.replan_task(
        task.task_id,
        _replanned_workflow(),
        requested_by="user:local",
        reason="concurrent authorized rebind",
    )

    result = service.update_run_status(
        task.task_id,
        RunStatus.PAUSED,
        event_type=TaskEventType.RUN_PAUSED,
    )

    assert result.workflow is not None
    assert result.run is not None
    assert result.workflow.version == 2
    assert result.run.workflow_version == result.workflow.version
    assert result.run.workflow_digest == result.workflow.canonical_digest()
