from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_os_contracts import (
    EdgeSpec,
    ExternalSignal,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    ProviderToolProposal,
    RunStatus,
    TaskEventType,
    TaskStatus,
    WorkflowGraph,
)
from agent_os_core import (
    ConcurrentWriteError,
    DeterministicProvider,
    InvalidTransitionError,
    RunCoordinator,
    TaskService,
)
from apps.api_server.app import AgentOSApplication


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _simple_workflow(now: datetime, *, timeout_seconds: int = 120) -> WorkflowGraph:
    nodes = (
        NodeSpec(
            node_id="read",
            kind=NodeKind.TOOL,
            capability="workspace.read",
            idempotency=IdempotencyMode.IDEMPOTENT,
        ),
        NodeSpec(
            node_id="wait",
            kind=NodeKind.WAIT_EVENT,
            wait_signal_name="build.finished",
            wait_correlation_key="build:7",
            timeout_seconds=timeout_seconds,
        ),
        NodeSpec(
            node_id="tests",
            kind=NodeKind.TOOL,
            capability="workspace.run_tests",
            idempotency=IdempotencyMode.IDEMPOTENT,
        ),
        NodeSpec(node_id="evaluate", kind=NodeKind.EVALUATION),
        NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
    )
    return WorkflowGraph(
        workflow_id="workflow:durable-wait",
        version=1,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=now,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=nodes,
        edges=tuple(
            EdgeSpec(source=source, target=target)
            for source, target in (
                ("read", "wait"),
                ("wait", "tests"),
                ("tests", "evaluate"),
                ("evaluate", "done"),
            )
        ),
        max_replans=1,
    )


def _artifact_before_wait_workflow(
    now: datetime,
    *,
    version: int = 1,
) -> WorkflowGraph:
    read = NodeSpec(
        node_id="read",
        kind=NodeKind.TOOL,
        capability="workspace.read",
        idempotency=IdempotencyMode.IDEMPOTENT,
    )
    tests = NodeSpec(
        node_id="tests",
        kind=NodeKind.TOOL,
        capability="workspace.run_tests",
        idempotency=IdempotencyMode.IDEMPOTENT,
    )
    evaluate = NodeSpec(node_id="evaluate", kind=NodeKind.EVALUATION)
    done = NodeSpec(node_id="done", kind=NodeKind.TERMINAL)
    if version == 1:
        middle = NodeSpec(
            node_id="wait",
            kind=NodeKind.WAIT_EVENT,
            wait_signal_name="review.ready",
            wait_correlation_key="review:artifact",
            timeout_seconds=120,
        )
        nodes = (read, tests, middle, evaluate, done)
        edges = (
            EdgeSpec(source="read", target="tests"),
            EdgeSpec(source="tests", target="wait"),
            EdgeSpec(source="wait", target="evaluate"),
            EdgeSpec(source="evaluate", target="done"),
        )
    else:
        middle = NodeSpec(node_id="inspect", kind=NodeKind.TRANSFORM)
        nodes = (read, tests, middle, evaluate, done)
        edges = (
            EdgeSpec(source="read", target="tests"),
            EdgeSpec(source="tests", target="inspect"),
            EdgeSpec(source="inspect", target="evaluate"),
            EdgeSpec(source="evaluate", target="done"),
        )
    return WorkflowGraph(
        workflow_id="workflow:artifact-before-wait",
        version=version,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=now,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=nodes,
        edges=edges,
        max_replans=1,
    )


def _provider_wait_workflow(now: datetime) -> WorkflowGraph:
    nodes = (
        NodeSpec(
            node_id="read",
            kind=NodeKind.TOOL,
            capability="workspace.read",
            idempotency=IdempotencyMode.IDEMPOTENT,
        ),
        NodeSpec(
            node_id="provider", kind=NodeKind.PROVIDER, capability="provider.chat"
        ),
        NodeSpec(
            node_id="wait",
            kind=NodeKind.WAIT_EVENT,
            wait_signal_name="review.ready",
            wait_correlation_key="review:7",
            timeout_seconds=120,
        ),
        NodeSpec(node_id="approve", kind=NodeKind.APPROVAL),
        NodeSpec(
            node_id="apply",
            kind=NodeKind.TOOL,
            capability="workspace.apply_patch",
            idempotency=IdempotencyMode.COMPENSATABLE,
        ),
        NodeSpec(
            node_id="tests",
            kind=NodeKind.TOOL,
            capability="workspace.run_tests",
            idempotency=IdempotencyMode.IDEMPOTENT,
        ),
        NodeSpec(node_id="evaluate", kind=NodeKind.EVALUATION),
        NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
    )
    return WorkflowGraph(
        workflow_id="workflow:provider-wait",
        version=1,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=now,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=nodes,
        edges=tuple(
            EdgeSpec(source=source, target=target)
            for source, target in (
                ("read", "provider"),
                ("provider", "wait"),
                ("wait", "approve"),
                ("approve", "apply"),
                ("apply", "tests"),
                ("tests", "evaluate"),
                ("evaluate", "done"),
            )
        ),
        max_replans=1,
    )


def _replanned_workflow(now: datetime) -> WorkflowGraph:
    nodes = (
        NodeSpec(
            node_id="read",
            kind=NodeKind.TOOL,
            capability="workspace.read",
            idempotency=IdempotencyMode.IDEMPOTENT,
        ),
        NodeSpec(
            node_id="provider", kind=NodeKind.PROVIDER, capability="provider.chat"
        ),
        NodeSpec(node_id="inspect", kind=NodeKind.TRANSFORM),
        NodeSpec(
            node_id="tests",
            kind=NodeKind.TOOL,
            capability="workspace.run_tests",
            idempotency=IdempotencyMode.IDEMPOTENT,
        ),
        NodeSpec(node_id="evaluate", kind=NodeKind.EVALUATION),
        NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
    )
    return WorkflowGraph(
        workflow_id="workflow:provider-wait",
        version=2,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=now,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=nodes,
        edges=tuple(
            EdgeSpec(source=source, target=target)
            for source, target in (
                ("read", "provider"),
                ("provider", "inspect"),
                ("inspect", "tests"),
                ("tests", "evaluate"),
                ("evaluate", "done"),
            )
        ),
        max_replans=1,
    )


def _replanned_with_preserved_apply(now: datetime) -> WorkflowGraph:
    base = _replanned_workflow(now)
    apply = NodeSpec(
        node_id="apply",
        kind=NodeKind.TOOL,
        capability="workspace.apply_patch",
        idempotency=IdempotencyMode.COMPENSATABLE,
    )
    nodes = tuple(node if node.node_id != "tests" else apply for node in base.nodes) + (
        next(node for node in base.nodes if node.node_id == "tests"),
    )
    return base.model_copy(
        update={
            "nodes": nodes,
            "edges": (
                EdgeSpec(source="read", target="provider"),
                EdgeSpec(source="provider", target="inspect"),
                EdgeSpec(source="inspect", target="apply"),
                EdgeSpec(source="apply", target="tests"),
                EdgeSpec(source="tests", target="evaluate"),
                EdgeSpec(source="evaluate", target="done"),
            ),
        }
    )


def _prepare_workspace(root: Path) -> None:
    (root / "fixture.txt").write_text("stable\n", encoding="utf-8")
    (root / "test_fixture.py").write_text(
        "def test_fixture():\n    assert open('fixture.txt').read() == 'stable\\n'\n",
        encoding="utf-8",
    )


def _committed_app(
    root: Path,
    workflow: WorkflowGraph,
    *,
    clock: MutableClock | None = None,
) -> tuple[AgentOSApplication, str]:
    _prepare_workspace(root)
    database = root / "agent-os.sqlite3"
    app = AgentOSApplication(database=database, workspace=root)
    if clock is not None:
        app.tasks = TaskService(app.store, clock=clock)
    app.provider = DeterministicProvider()
    app.provider_configured = True
    now = clock() if clock is not None else datetime.now(timezone.utc)
    goal_id = "goal:durable-wait"
    task = app.create_task(
        {
            "goal_id": goal_id,
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": now,
            "statement": "wait, verify, and finish",
        }
    )
    app.commit_task(
        task.task_id,
        {
            "commitment": {
                "commitment_id": "commitment:durable-wait",
                "task_id": task.task_id,
                "goal_id": goal_id,
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "accepted_by": "user:local",
                "accepted_at": now,
                "deliverables": ["verified wait result"],
                "acceptance_criteria": ["pytest passes"],
                "authority_scopes": ["workspace:read", "workspace:write"],
                "budget": {
                    "max_cost_usd": "1",
                    "max_duration_seconds": 3600,
                    "max_provider_tokens": 1000,
                    "max_tool_calls": 20,
                },
                "risk_tier": 1,
                "exit_conditions": ["verified"],
                "expires_at": now + timedelta(hours=1),
            },
            "workflow": workflow.model_dump(mode="json"),
            "expected_outcome": {
                "expected_outcome_id": "expected:durable-wait",
                "task_id": task.task_id,
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "evaluator_type": "pytest",
                "evaluator_version": "1",
                "evidence_requirements": ["test-report"],
                "failure_semantics": ["non-zero exit"],
                "threshold": 1,
                "observation_window_seconds": 60,
                "frozen_at": now,
            },
        },
    )
    return app, task.task_id


def _inputs() -> dict[str, str]:
    return {"target_path": "fixture.txt", "test_command": "python -m pytest"}


def _signal(
    app: AgentOSApplication, task_id: str, *, name: str = "build.finished"
) -> ExternalSignal:
    task = app.tasks.get_task(task_id)
    assert task.run is not None
    return ExternalSignal(
        signal_id="signal:build-7",
        task_id=task_id,
        run_id=task.run.run_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        signal_name=name,
        correlation_key="build:7",
        payload_json=json.dumps({"status": "passed"}),
        evidence_refs=("artifact:build-7",),
        occurred_at=app.tasks.now(),
    )


def test_run_stops_at_typed_wait_without_downstream_execution(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    app, task_id = _committed_app(tmp_path, _simple_workflow(now))

    result = app.run_task(task_id, _inputs())
    events = app.store.read(task_id)

    assert result.status is TaskStatus.WAITING
    assert result.run is not None
    assert result.run.status is RunStatus.WAITING_EVENT
    assert result.run.wait_condition is not None
    assert [event.event_type for event in events].count(
        TaskEventType.WAIT_REGISTERED
    ) == 1
    assert not any(
        event.event_type is TaskEventType.NODE_STARTED
        and event.decoded_payload().get("node_id") == "tests"
        for event in events
    )


def test_run_while_wait_is_live_is_an_event_stream_noop(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    app, task_id = _committed_app(tmp_path, _simple_workflow(now))
    waiting = app.run_task(task_id, _inputs())
    before = tuple(app.store.read(task_id))

    repeated = app.run_task(task_id, _inputs())

    assert repeated.sequence == waiting.sequence
    assert tuple(app.store.read(task_id)) == before


def test_matching_signal_then_new_process_resumes_after_completed_wait(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    database = tmp_path / "agent-os.sqlite3"
    app, task_id = _committed_app(tmp_path, _simple_workflow(now))
    waiting = app.run_task(task_id, _inputs())
    assert waiting.run is not None
    app.tasks.record_signal(task_id, _signal(app, task_id))

    restarted = AgentOSApplication(database=database, workspace=tmp_path)
    restarted.provider = DeterministicProvider()
    restarted.provider_configured = True
    result = restarted.run_task(task_id, _inputs())
    events = restarted.store.read(task_id)

    assert result.status is TaskStatus.COMPLETED
    assert result.run is not None
    assert result.run.status is RunStatus.SUCCEEDED
    assert [event.event_type for event in events].count(
        TaskEventType.WAIT_REGISTERED
    ) == 1
    assert [event.event_type for event in events].count(
        TaskEventType.WAIT_SATISFIED
    ) == 1
    assert [
        event.decoded_payload().get("node_id")
        for event in events
        if event.event_type is TaskEventType.NODE_COMPLETED
    ].count("wait") == 1


def test_signal_recorded_during_lease_acquisition_is_seen_before_dispatch(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    app, task_id = _committed_app(tmp_path, _simple_workflow(now))
    app.run_task(task_id, _inputs())
    signal = _signal(app, task_id)
    original_acquire = app.store.acquire_lease

    def acquire_and_signal(run_id: str, owner: str, expires_at: str) -> int:
        fence = original_acquire(run_id, owner, expires_at)
        app.tasks.record_signal(task_id, signal)
        return fence

    app.store.acquire_lease = acquire_and_signal  # type: ignore[method-assign]

    result = app.run_task(task_id, _inputs())

    assert result.status is TaskStatus.COMPLETED
    assert result.run is not None
    assert result.run.status is RunStatus.SUCCEEDED


def test_wait_timeout_fails_without_downstream_action(tmp_path: Path) -> None:
    clock = MutableClock(datetime.now(timezone.utc))
    app, task_id = _committed_app(
        tmp_path,
        _simple_workflow(clock(), timeout_seconds=10),
        clock=clock,
    )
    app.run_task(task_id, _inputs())
    clock.value += timedelta(seconds=11)

    result = app.run_task(task_id, _inputs())
    events = app.store.read(task_id)

    assert result.status is TaskStatus.FAILED
    assert result.run is not None
    assert result.run.status is RunStatus.FAILED
    assert events[-1].event_type is TaskEventType.WAIT_TIMED_OUT
    assert not any(
        event.event_type is TaskEventType.NODE_STARTED
        and event.decoded_payload().get("node_id") == "tests"
        for event in events
    )


def test_status_cas_failure_releases_acquired_lease(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    app, task_id = _committed_app(tmp_path, _simple_workflow(now))
    started = app.start_run(task_id)
    assert started.run is not None
    run_id = started.run.run_id

    def fail_status_update(*args: object, **kwargs: object):
        raise ConcurrentWriteError("injected status CAS conflict")

    app.tasks.update_run_status = fail_status_update  # type: ignore[method-assign]

    with pytest.raises(ConcurrentWriteError, match="status CAS"):
        app.run_task(task_id, _inputs())

    fence = app.store.acquire_lease(
        run_id,
        "worker:probe",
        (now + timedelta(minutes=5)).isoformat(),
    )
    assert fence >= 2


def test_completed_tool_artifact_remains_active_evidence_after_rebind(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    app, task_id = _committed_app(
        tmp_path,
        _artifact_before_wait_workflow(now),
    )
    waiting = app.run_task(task_id, _inputs())
    assert waiting.run is not None
    artifact_event = next(
        event
        for event in app.store.read(task_id)
        if event.event_type is TaskEventType.ARTIFACT_RECORDED
    )
    artifact_payload = artifact_event.decoded_payload()
    artifact_id = artifact_payload["artifact_id"]
    assert artifact_payload["node_id"] == "tests"
    assert str(artifact_payload["action_id"]).startswith("action-")

    app.tasks.replan_task(
        task_id,
        _artifact_before_wait_workflow(now, version=2),
        requested_by="user:local",
        reason="replace wait after verified test artifact",
    )
    runner = RunCoordinator(
        app.tasks,
        app.sandbox,
        app.provider,
        app.provider_profile,
        app.policy,
        app.correction,
        app.grants,
    )
    restored = runner._restore_context(task_id, _inputs())

    assert artifact_id in restored["evidence_refs"]
    result = app.run_task(task_id, _inputs())
    assert result.status is TaskStatus.COMPLETED
    assert result.run is not None
    assert result.run.status is RunStatus.SUCCEEDED


def test_rebind_clears_invalidated_action_projection_and_approval(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    app, task_id = _committed_app(tmp_path, _provider_wait_workflow(now))
    app.provider = DeterministicProvider(
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:stale",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps(
                    {"path": "fixture.txt", "content": "changed\n"}
                ),
            ),
        )
    )
    waiting = app.run_task(task_id, _inputs())
    assert waiting.run is not None
    app.record_approval(
        task_id,
        {"disposition": "APPROVE", "reason": "approve only the original plan"},
    )
    app.tasks.append_event(
        task_id,
        TaskEventType.ARTIFACT_RECORDED,
        {
            "artifact_id": "artifact:partial-old-plan",
            "node_id": "apply",
            "action_id": "action:partial-old-plan",
        },
    )

    rebound = app.tasks.replan_task(
        task_id,
        _replanned_workflow(now),
        requested_by="user:local",
        reason="replace the unexecuted suffix",
    )
    runner = RunCoordinator(
        app.tasks,
        app.sandbox,
        app.provider,
        app.provider_profile,
        app.policy,
        app.correction,
        app.grants,
    )
    restored = runner._restore_context(task_id, _inputs())

    assert rebound.approval is None
    with pytest.raises(ValueError, match="no pending provider action"):
        app.record_approval(
            task_id,
            {"disposition": "APPROVE", "reason": "must not approve stale action"},
        )
    assert "action:workspace.apply_patch" not in restored
    assert "workspace.apply_patch" not in restored
    assert "provider" in restored
    assert "artifact:partial-old-plan" not in restored.get("evidence_refs", ())

    result = app.run_task(task_id, _inputs())

    assert result.status is TaskStatus.COMPLETED
    assert result.run is not None
    assert result.run.status is RunStatus.SUCCEEDED
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"


def test_rebind_clears_old_action_for_preserved_but_uncompleted_node(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    app, task_id = _committed_app(tmp_path, _provider_wait_workflow(now))
    app.provider = DeterministicProvider(
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:preserved-node",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps(
                    {"path": "fixture.txt", "content": "changed\n"}
                ),
            ),
        )
    )
    app.run_task(task_id, _inputs())

    rebound = app.tasks.replan_task(
        task_id,
        _replanned_with_preserved_apply(now),
        requested_by="user:local",
        reason="preserve node shape but invalidate old proposal authority",
    )
    assert rebound.last_rebound is not None
    assert "apply" in rebound.last_rebound.preserved_node_ids
    runner = RunCoordinator(
        app.tasks,
        app.sandbox,
        app.provider,
        app.provider_profile,
        app.policy,
        app.correction,
        app.grants,
    )

    restored = runner._restore_context(task_id, _inputs())

    assert "action:workspace.apply_patch" not in restored
    assert "workspace.apply_patch" not in restored


def test_approval_cannot_cross_rebind_between_scan_and_append(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    app, task_id = _committed_app(tmp_path, _provider_wait_workflow(now))
    app.provider = DeterministicProvider(
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:racing",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps(
                    {"path": "fixture.txt", "content": "changed\n"}
                ),
            ),
        )
    )
    app.run_task(task_id, _inputs())
    original_record = getattr(app.tasks, "record_approval", None)

    def record_after_rebind(task: str, approval: object):
        assert callable(original_record)
        app.tasks.record_approval = original_record  # type: ignore[attr-defined,method-assign]
        app.tasks.replan_task(
            task,
            _replanned_workflow(now),
            requested_by="user:local",
            reason="race before approval append",
        )
        return original_record(task, approval)

    app.tasks.record_approval = record_after_rebind  # type: ignore[attr-defined,method-assign]

    with pytest.raises(InvalidTransitionError, match="pending action"):
        app.record_approval(
            task_id,
            {"disposition": "APPROVE", "reason": "must bind to current plan"},
        )

    events = app.store.read(task_id)
    rebound_sequence = max(
        event.sequence
        for event in events
        if event.event_type is TaskEventType.RUN_PLAN_REBOUND
    )
    assert not any(
        event.event_type is TaskEventType.APPROVAL_RECORDED
        and event.sequence > rebound_sequence
        for event in events
    )
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
