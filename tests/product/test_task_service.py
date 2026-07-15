from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from agent_os_contracts import (
    Commitment,
    EdgeSpec,
    ExpectedOutcome,
    Goal,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    ObservedOutcome,
    OutcomeStatus,
    ResourceBudget,
    RunStatus,
    TaskEventType,
    TaskStatus,
    WorkflowGraph,
)
from agent_os_core import (
    InMemoryTaskEventStore,
    InvalidTransitionError,
    ScopeMismatchError,
    TaskNotFoundError,
    TaskService,
    ValidatedTestReport,
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


def _expected(task_id: str) -> ExpectedOutcome:
    return ExpectedOutcome(
        expected_outcome_id="expected-1",
        task_id=task_id,
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


def test_record_outcome_rejects_verified_score_below_frozen_threshold() -> None:
    store = InMemoryTaskEventStore()
    service = _service(store, DeterministicIdFactory())
    created = service.create_task(_goal())
    expected = _expected(created.task_id).model_copy(update={"threshold": 2.0})
    service.commit_task(
        created.task_id,
        _commitment(created.task_id),
        _workflow(),
        expected,
    )
    running = service.start_run(created.task_id)
    assert running.run is not None
    outcome = ObservedOutcome(
        observed_outcome_id="observed-forged",
        expected_outcome_id=expected.expected_outcome_id,
        task_id=created.task_id,
        run_id=running.run.run_id,
        tenant_id=expected.tenant_id,
        workspace_id=expected.workspace_id,
        evaluator_type=expected.evaluator_type,
        evaluator_version=expected.evaluator_version,
        status=OutcomeStatus.VERIFIED,
        score=1.0,
        confidence=1.0,
        evidence_refs=("artifact:test-report",),
        observed_at=NOW + timedelta(seconds=30),
    )

    with pytest.raises(InvalidTransitionError, match="threshold"):
        service.record_outcome(created.task_id, outcome)

    assert service.get_task(created.task_id).observed_outcome is None


def test_record_outcome_rejects_scope_mismatch() -> None:
    store = InMemoryTaskEventStore()
    service = _service(store, DeterministicIdFactory())
    created = service.create_task(_goal())
    expected = _expected(created.task_id)
    service.commit_task(
        created.task_id,
        _commitment(created.task_id),
        _workflow(),
        expected,
    )
    running = service.start_run(created.task_id)
    assert running.run is not None
    outcome = ObservedOutcome(
        observed_outcome_id="observed-wrong-scope",
        expected_outcome_id=expected.expected_outcome_id,
        task_id="task-other",
        run_id=running.run.run_id,
        tenant_id=expected.tenant_id,
        workspace_id=expected.workspace_id,
        evaluator_type=expected.evaluator_type,
        evaluator_version=expected.evaluator_version,
        status=OutcomeStatus.NOT_MET,
        score=0.0,
        confidence=1.0,
        evidence_refs=("artifact:test-report",),
        observed_at=NOW + timedelta(seconds=30),
    )

    with pytest.raises(InvalidTransitionError, match="scope"):
        service.record_outcome(created.task_id, outcome)

    assert service.get_task(created.task_id).observed_outcome is None


def test_record_artifact_rejects_unbound_action_receipt() -> None:
    store = InMemoryTaskEventStore()
    service = _service(store, DeterministicIdFactory())
    created = service.create_task(_goal())

    with pytest.raises(InvalidTransitionError, match="action receipt"):
        service.record_artifact(
            created.task_id,
            "artifact:" + "a" * 64,
            node_id="tests",
            action_id="action-forged",
        )

    assert len(store.read(created.task_id)) == 1


def test_append_event_rejects_protected_action_receipt_truth() -> None:
    store = InMemoryTaskEventStore()
    service = _service(store, DeterministicIdFactory())
    created = service.create_task(_goal())

    with pytest.raises(InvalidTransitionError, match="protected event"):
        service.append_event(
            created.task_id,
            TaskEventType.ACTION_RECEIPT_RECORDED,
            {},
        )

    assert len(store.read(created.task_id)) == 1


def test_record_outcome_persists_matching_invalid_evaluator_result() -> None:
    store = InMemoryTaskEventStore()
    service = _service(store, DeterministicIdFactory())
    created = service.create_task(_goal())
    expected = _expected(created.task_id).model_copy(
        update={"evaluator_type": "unknown"}
    )
    workflow = _workflow().model_copy(
        update={"evaluator_refs": ("evaluator:unknown:1",)}
    )
    service.commit_task(
        created.task_id,
        _commitment(created.task_id),
        workflow,
        expected,
    )
    running = service.start_run(created.task_id)
    assert running.run is not None
    outcome = ObservedOutcome(
        observed_outcome_id="observed-unsupported",
        expected_outcome_id=expected.expected_outcome_id,
        task_id=created.task_id,
        run_id=running.run.run_id,
        tenant_id=expected.tenant_id,
        workspace_id=expected.workspace_id,
        evaluator_type=expected.evaluator_type,
        evaluator_version=expected.evaluator_version,
        status=OutcomeStatus.INVALID,
        score=None,
        confidence=1.0,
        evidence_refs=(),
        unresolved_gaps=("unsupported evaluator",),
        observed_at=NOW + timedelta(seconds=30),
    )

    recorded = service.record_outcome(created.task_id, outcome)

    assert recorded.observed_outcome == outcome


def test_record_outcome_rejects_test_report_completed_before_freeze() -> None:
    store = InMemoryTaskEventStore()
    service = _service(store, DeterministicIdFactory())
    created = service.create_task(_goal())
    expected = _expected(created.task_id)
    service.commit_task(
        created.task_id,
        _commitment(created.task_id),
        _workflow(),
        expected,
    )
    running = service.start_run(created.task_id)
    assert running.run is not None
    artifact_id = "artifact:" + "c" * 64
    report = ValidatedTestReport(
        artifact_ids=(artifact_id,),
        exit_code=0,
        node_id="tests",
        action_id="action-tests",
        receipt_id="receipt-tests",
        completed_sequence=10,
        completed_at=expected.frozen_at - timedelta(seconds=1),
    )

    def pre_freeze_report(_task_id: str, _run_id: str) -> ValidatedTestReport:
        return report

    service.validated_test_report = pre_freeze_report  # type: ignore[method-assign]
    outcome = ObservedOutcome(
        observed_outcome_id="observed-pre-freeze",
        expected_outcome_id=expected.expected_outcome_id,
        task_id=created.task_id,
        run_id=running.run.run_id,
        tenant_id=expected.tenant_id,
        workspace_id=expected.workspace_id,
        evaluator_type=expected.evaluator_type,
        evaluator_version=expected.evaluator_version,
        status=OutcomeStatus.VERIFIED,
        score=1.0,
        confidence=1.0,
        evidence_refs=(artifact_id,),
        observed_at=NOW + timedelta(seconds=30),
    )

    with pytest.raises(InvalidTransitionError, match="predates frozen"):
        service.record_outcome(created.task_id, outcome)


def test_run_terminal_state_cannot_be_reopened() -> None:
    store = InMemoryTaskEventStore()
    ids = DeterministicIdFactory()
    service = _service(store, ids)
    created = service.create_task(_goal())
    service.commit_task(
        created.task_id,
        _commitment(created.task_id),
        _workflow(),
        _expected(created.task_id),
    )
    service.start_run(created.task_id)
    service.update_run_status(
        created.task_id, RunStatus.RUNNING, event_type=TaskEventType.RUN_QUEUED
    )
    service.update_run_status(
        created.task_id, RunStatus.SUCCEEDED, event_type=TaskEventType.RUN_SUCCEEDED
    )
    with pytest.raises(InvalidTransitionError, match="SUCCEEDED"):
        service.update_run_status(
            created.task_id, RunStatus.RUNNING, event_type=TaskEventType.RUN_RESUMED
        )


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
