from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

import pytest

from agent_os_contracts import (
    Commitment,
    EdgeSpec,
    ExpectedOutcome,
    Goal,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    TaskStatus,
    WorkflowGraph,
)
from agent_os_core import (
    InMemoryTaskEventStore,
    InvalidTransitionError,
    ScopeMismatchError,
    TaskNotFoundError,
    TaskService,
)


NOW = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)


class DeterministicIdFactory:
    def __init__(self) -> None:
        self._counts: defaultdict[str, int] = defaultdict(int)

    def __call__(self, kind: str) -> str:
        self._counts[kind] += 1
        return f"{kind}-{self._counts[kind]}"


def _goal() -> Goal:
    return Goal(
        goal_id="goal-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        created_by="user-1",
        created_at=NOW,
        statement="Ship a verified patch",
    )


def _commitment(task_id: str) -> Commitment:
    return Commitment(
        commitment_id="commitment-1",
        task_id=task_id,
        goal_id="goal-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        accepted_by="user-1",
        accepted_at=NOW,
        deliverables=("patch",),
        acceptance_criteria=("tests pass",),
        authority_scopes=("repo:read", "repo:write"),
    )


def _workflow() -> WorkflowGraph:
    return WorkflowGraph(
        workflow_id="workflow-1",
        version=1,
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        created_by="user-1",
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=(
            NodeSpec(
                node_id="inspect",
                kind=NodeKind.TOOL,
                capability="workspace.read",
                idempotency=IdempotencyMode.IDEMPOTENT,
            ),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(EdgeSpec(source="inspect", target="done"),),
    )


def _expected(task_id: str) -> ExpectedOutcome:
    return ExpectedOutcome(
        expected_outcome_id="expected-1",
        task_id=task_id,
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        threshold=1.0,
        observation_window_seconds=60,
        frozen_at=NOW,
    )


def _service(
    store: InMemoryTaskEventStore,
    ids: DeterministicIdFactory,
) -> TaskService:
    return TaskService(store, id_factory=ids, clock=lambda: NOW)


def test_service_rehydrates_across_service_instances() -> None:
    store = InMemoryTaskEventStore()
    ids = DeterministicIdFactory()
    first = _service(store, ids)

    created = first.create_task(_goal())
    committed = first.commit_task(
        created.task_id,
        _commitment(created.task_id),
        _workflow(),
        _expected(created.task_id),
    )

    restarted = _service(store, ids)
    running = restarted.start_run(created.task_id)

    events = store.read(created.task_id)
    assert created.status is TaskStatus.DRAFT
    assert committed.status is TaskStatus.COMMITTED
    assert running.status is TaskStatus.RUNNING
    assert running.run is not None
    assert running.workflow is not None
    assert running.run.workflow_digest == running.workflow.canonical_digest()
    assert [event.sequence for event in events] == [1, 2, 3]
    assert events[1].causation_id == events[0].event_id
    assert events[2].causation_id == events[1].event_id


def test_get_task_rejects_missing_stream() -> None:
    service = _service(InMemoryTaskEventStore(), DeterministicIdFactory())

    with pytest.raises(TaskNotFoundError, match="missing"):
        service.get_task("missing")


def test_start_before_commit_fails_without_writing_event() -> None:
    store = InMemoryTaskEventStore()
    service = _service(store, DeterministicIdFactory())
    created = service.create_task(_goal())

    with pytest.raises(InvalidTransitionError, match="DRAFT"):
        service.start_run(created.task_id)

    assert len(store.read(created.task_id)) == 1


def test_commit_scope_mismatch_fails_without_writing_event() -> None:
    store = InMemoryTaskEventStore()
    service = _service(store, DeterministicIdFactory())
    created = service.create_task(_goal())
    wrong_task = _commitment("task-other")

    with pytest.raises(ScopeMismatchError, match="task"):
        service.commit_task(
            created.task_id,
            wrong_task,
            _workflow(),
            _expected(created.task_id),
        )

    assert len(store.read(created.task_id)) == 1
