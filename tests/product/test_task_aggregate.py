from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from agent_os_contracts import (
    AgentRun,
    Commitment,
    EdgeSpec,
    ExpectedOutcome,
    Goal,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    RunStatus,
    ResourceBudget,
    TaskEvent,
    TaskEventDraft,
    TaskStatus,
    WorkflowGraph,
)
from agent_os_core import EventStreamError, InvalidTransitionError, ScopeMismatchError
from agent_os_core.task_aggregate import TaskAggregate


NOW = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)


def _goal() -> Goal:
    return Goal(
        goal_id="goal-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        created_by="user-1",
        created_at=NOW,
        statement="Ship a verified patch",
    )


def _commitment(*, tenant_id: str = "tenant-1") -> Commitment:
    return Commitment(
        commitment_id="commitment-1",
        task_id="task-1",
        goal_id="goal-1",
        tenant_id=tenant_id,
        workspace_id="workspace-1",
        accepted_by="user-1",
        accepted_at=NOW,
        deliverables=("patch",),
        acceptance_criteria=("tests pass",),
        authority_scopes=("repo:read", "repo:write"),
        budget=ResourceBudget(
            max_cost_usd=Decimal("1.00"),
            max_duration_seconds=300,
            max_provider_tokens=1_000,
            max_tool_calls=4,
        ),
        risk_tier=1,
        exit_conditions=("tests verified",),
        expires_at=NOW + timedelta(hours=1),
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


def _expected() -> ExpectedOutcome:
    return ExpectedOutcome(
        expected_outcome_id="expected-1",
        task_id="task-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("tests fail",),
        threshold=1.0,
        observation_window_seconds=60,
        frozen_at=NOW,
    )


def _run(*, workflow_digest: str | None = None) -> AgentRun:
    workflow = _workflow()
    return AgentRun(
        run_id="run-1",
        task_id="task-1",
        commitment_id="commitment-1",
        workflow_id=workflow.workflow_id,
        workflow_version=workflow.version,
        workflow_digest=workflow_digest or workflow.canonical_digest(),
        expected_outcome_id="expected-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        status=RunStatus.RUNNING,
        created_at=NOW,
    )


def _persist(draft: TaskEventDraft, sequence: int) -> TaskEvent:
    return TaskEvent(**draft.model_dump(), sequence=sequence)


def _draft_aggregate() -> tuple[TaskAggregate, tuple[TaskEvent, ...]]:
    created_draft = TaskAggregate.create_task(
        task_id="task-1",
        goal=_goal(),
        event_id="event-created",
        occurred_at=NOW,
    )
    events = (_persist(created_draft, 1),)
    return TaskAggregate.rehydrate(events), events


def _committed_aggregate() -> tuple[TaskAggregate, tuple[TaskEvent, ...]]:
    draft, events = _draft_aggregate()
    committed_draft = draft.commit(
        _commitment(),
        _workflow(),
        _expected(),
        event_id="event-committed",
        occurred_at=NOW,
    )
    committed_events = (*events, _persist(committed_draft, 2))
    return TaskAggregate.rehydrate(committed_events), committed_events


def test_rehydrate_create_commit_start() -> None:
    committed, events = _committed_aggregate()
    started_draft = committed.start(
        _run(),
        event_id="event-started",
        occurred_at=NOW,
    )

    running = TaskAggregate.rehydrate((*events, _persist(started_draft, 3)))

    assert running.status is TaskStatus.RUNNING
    assert running.sequence == 3
    assert running.run is not None
    assert running.workflow is not None
    assert running.run.workflow_digest == running.workflow.canonical_digest()


def test_start_before_commit_fails() -> None:
    draft, _ = _draft_aggregate()

    with pytest.raises(InvalidTransitionError, match="DRAFT"):
        draft.start(_run(), event_id="event-started", occurred_at=NOW)


def test_commit_rejects_cross_tenant_scope() -> None:
    draft, _ = _draft_aggregate()

    with pytest.raises(ScopeMismatchError, match="tenant"):
        draft.commit(
            _commitment(tenant_id="tenant-2"),
            _workflow(),
            _expected(),
            event_id="event-committed",
            occurred_at=NOW,
        )


def test_start_rejects_workflow_digest_mismatch() -> None:
    committed, _ = _committed_aggregate()

    with pytest.raises(ScopeMismatchError, match="workflow digest"):
        committed.start(
            _run(workflow_digest="0" * 64),
            event_id="event-started",
            occurred_at=NOW,
        )


def test_rehydrate_rejects_committed_workflow_digest_tampering() -> None:
    _, events = _committed_aggregate()
    committed_event = events[1]
    payload = committed_event.decoded_payload()
    payload["workflow_digest"] = "0" * 64
    tampered_draft = TaskEventDraft.build(
        event_id=committed_event.event_id,
        task_id=committed_event.task_id,
        event_type=committed_event.event_type,
        payload=payload,
        occurred_at=committed_event.occurred_at,
        correlation_id=committed_event.correlation_id,
        causation_id=committed_event.causation_id,
    )
    tampered_event = _persist(tampered_draft, committed_event.sequence)

    with pytest.raises(EventStreamError, match="workflow digest mismatch"):
        TaskAggregate.rehydrate((events[0], tampered_event))


def test_rehydrate_rejects_sequence_gap() -> None:
    created_draft = TaskAggregate.create_task(
        task_id="task-1",
        goal=_goal(),
        event_id="event-created",
        occurred_at=NOW,
    )

    with pytest.raises(EventStreamError, match="sequence"):
        TaskAggregate.rehydrate((_persist(created_draft, 2),))


def test_rehydrate_rejects_second_creation_event() -> None:
    created_draft = TaskAggregate.create_task(
        task_id="task-1",
        goal=_goal(),
        event_id="event-created",
        occurred_at=NOW,
    )
    duplicate = created_draft.model_copy(update={"event_id": "event-created-2"})

    with pytest.raises(EventStreamError, match="TASK_CREATED"):
        TaskAggregate.rehydrate(
            (_persist(created_draft, 1), _persist(duplicate, 2))
        )
