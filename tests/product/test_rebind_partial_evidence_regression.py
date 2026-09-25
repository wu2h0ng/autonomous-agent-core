from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_os_contracts import (
    EdgeSpec,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    RunStatus,
    TaskEventType,
    TaskStatus,
    WorkflowGraph,
)
from agent_os_core import RunCoordinator, TaskEventStore, WorkerInterrupted
from apps.api_server.app import AgentOSApplication


def _prefix_artifact_workflow(now: datetime, *, version: int = 1) -> WorkflowGraph:
    prefix_write = NodeSpec(
        node_id="prefix_write",
        kind=NodeKind.TOOL,
        capability="artifact.write",
        idempotency=IdempotencyMode.IDEMPOTENT,
    )
    evaluate = NodeSpec(node_id="evaluate", kind=NodeKind.EVALUATION)
    done = NodeSpec(node_id="done", kind=NodeKind.TERMINAL)
    if version == 1:
        middle = NodeSpec(
            node_id="tests",
            kind=NodeKind.TOOL,
            capability="workspace.run_tests",
            idempotency=IdempotencyMode.IDEMPOTENT,
        )
        nodes = (prefix_write, middle, evaluate, done)
        edges = (
            EdgeSpec(source="prefix_write", target="tests"),
            EdgeSpec(source="tests", target="evaluate"),
            EdgeSpec(source="evaluate", target="done"),
        )
    else:
        middle = NodeSpec(
            node_id="verify",
            kind=NodeKind.TOOL,
            capability="workspace.run_tests",
            idempotency=IdempotencyMode.IDEMPOTENT,
        )
        nodes = (prefix_write, middle, evaluate, done)
        edges = (
            EdgeSpec(source="prefix_write", target="verify"),
            EdgeSpec(source="verify", target="evaluate"),
            EdgeSpec(source="evaluate", target="done"),
        )
    return WorkflowGraph(
        workflow_id="workflow:rebind-partial-evidence",
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


def _prepare_workspace(root: Path) -> None:
    (root / "fixture.txt").write_text("stable\n", encoding="utf-8")
    (root / "test_fixture.py").write_text(
        "def test_fixture():\n    assert open('fixture.txt').read() == 'stable\\n'\n",
        encoding="utf-8",
    )


def _committed_app(
    root: Path, workflow: WorkflowGraph
) -> tuple[AgentOSApplication, str]:
    _prepare_workspace(root)
    database = root / "agent-os.sqlite3"
    app = AgentOSApplication(database=database, workspace=root)
    app.provider_configured = True
    now = datetime.now(timezone.utc)
    goal_id = "goal:rebind-partial-evidence"
    task = app.create_task(
        {
            "goal_id": goal_id,
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": now,
            "statement": "record prefix artifact, interrupt partial node, rebind suffix",
        }
    )
    app.commit_task(
        task.task_id,
        {
            "commitment": {
                "commitment_id": "commitment:rebind-partial-evidence",
                "task_id": task.task_id,
                "goal_id": goal_id,
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "accepted_by": "user:local",
                "accepted_at": now,
                "deliverables": ["verified rebind after partial evidence"],
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
                "expected_outcome_id": "expected:rebind-partial-evidence",
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


def _inputs() -> dict[str, object]:
    return {
        "target_path": "fixture.txt",
        "test_command": "python -m pytest",
        "artifact.write": {"content": "completed-prefix evidence"},
    }


def _artifact_events(
    task_id: str, store: TaskEventStore
) -> list[tuple[int, str, str, str]]:
    return [
        (
            event.sequence,
            event.event_type.value,
            event.decoded_payload().get("artifact_id", ""),
            event.decoded_payload().get("node_id", ""),
        )
        for event in store.read(task_id)
        if event.event_type is TaskEventType.ARTIFACT_RECORDED
    ]


def test_rebind_removes_partial_artifact_evidence_and_keeps_completed_prefix(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    app, task_id = _committed_app(tmp_path, _prefix_artifact_workflow(now))

    original_append_event = app.tasks.append_event

    def append_event_with_interrupt(
        task_id_arg: str,
        event_type: TaskEventType,
        payload: dict[str, object],
        *,
        correlation_id: str | None = None,
    ) -> object:
        if (
            event_type is TaskEventType.NODE_COMPLETED
            and payload.get("node_id") == "tests"
        ):
            raise WorkerInterrupted(
                "worker interrupted after ARTIFACT_RECORDED, before NODE_COMPLETED"
            )
        return original_append_event(
            task_id_arg, event_type, payload, correlation_id=correlation_id
        )

    app.tasks.append_event = append_event_with_interrupt  # type: ignore[method-assign]

    try:
        with pytest.raises(WorkerInterrupted, match="before NODE_COMPLETED"):
            app.run_task(task_id, _inputs())
    finally:
        app.tasks.append_event = original_append_event  # type: ignore[method-assign]

    events = app.store.read(task_id)
    event_types = [event.event_type for event in events]
    sequences = [event.sequence for event in events]

    assert sequences == list(range(1, len(events) + 1))
    assert event_types.count(TaskEventType.ARTIFACT_RECORDED) == 2
    assert event_types.count(TaskEventType.NODE_COMPLETED) == 1
    assert event_types.index(TaskEventType.ARTIFACT_RECORDED) < event_types.index(
        TaskEventType.NODE_COMPLETED
    )

    artifact_records = _artifact_events(task_id, app.store)
    assert len(artifact_records) == 2
    prefix_sequence, _, prefix_artifact_id, prefix_node_id = artifact_records[0]
    partial_sequence, _, partial_artifact_id, partial_node_id = artifact_records[1]
    assert prefix_node_id == "prefix_write"
    assert partial_node_id == "tests"
    assert prefix_sequence < partial_sequence

    artifact_event_by_node: dict[str, dict[str, object]] = {}
    for event in events:
        if event.event_type is TaskEventType.ARTIFACT_RECORDED:
            payload = event.decoded_payload()
            artifact_event_by_node[str(payload.get("node_id", ""))] = payload
    assert set(artifact_event_by_node) == {"prefix_write", "tests"}
    for node_id in ("prefix_write", "tests"):
        action_id = artifact_event_by_node[node_id].get("action_id")
        assert isinstance(action_id, str) and action_id.startswith("action-")

    partial_node_completed = any(
        event.event_type is TaskEventType.NODE_COMPLETED
        and event.decoded_payload().get("node_id") == "tests"
        for event in events
    )
    assert not partial_node_completed

    prefix_artifact_path = app.sandbox.artifacts / prefix_artifact_id.removeprefix(
        "artifact:"
    )
    assert prefix_artifact_path.is_file()
    assert prefix_artifact_path.read_bytes() == b"completed-prefix evidence"

    partial_artifact_path = app.sandbox.artifacts / partial_artifact_id.removeprefix(
        "artifact:"
    )
    assert partial_artifact_path.is_file()

    def sequence_of(event_type: TaskEventType, *, node_id: str | None = None) -> int:
        for event in events:
            if event.event_type is not event_type:
                continue
            if node_id is None or event.decoded_payload().get("node_id") == node_id:
                return event.sequence
        raise AssertionError(f"missing {event_type.value} for node {node_id}")

    tests_started_seq = sequence_of(TaskEventType.NODE_STARTED, node_id="tests")
    tests_artifact_seq = sequence_of(TaskEventType.ARTIFACT_RECORDED, node_id="tests")
    assert tests_started_seq < tests_artifact_seq

    app.pause_task(task_id)
    rebound = app.replan_task(
        task_id,
        {
            "workflow": _prefix_artifact_workflow(now, version=2).model_dump(
                mode="json"
            ),
            "reason": "replace interrupted tests node with verify after prefix artifact",
        },
    )
    assert rebound.status is TaskStatus.PAUSED
    assert rebound.run is not None
    assert rebound.run.status is RunStatus.PAUSED
    assert rebound.last_rebound is not None
    assert "prefix_write" in rebound.last_rebound.preserved_node_ids
    assert "tests" in rebound.last_rebound.invalidated_node_ids
    assert "verify" in rebound.last_rebound.new_node_ids

    events = app.store.read(task_id)
    rebound_sequence = next(
        event.sequence
        for event in events
        if event.event_type is TaskEventType.RUN_PLAN_REBOUND
    )
    assert tests_artifact_seq < rebound_sequence
    assert not partial_node_completed

    runner = RunCoordinator(
        app.tasks,
        app.sandbox,
        app.execution_profile,
        app.provider,
        app.provider_profile,
        app.policy,
        app.correction,
        app.grants,
    )
    restored = runner._restore_context(task_id, _inputs())
    restored_evidence = restored.get("evidence_refs", ())

    assert prefix_artifact_id in restored_evidence
    assert partial_artifact_id not in restored_evidence
    assert restored.get("prefix_write") is not None
    assert restored.get("tests") is None

    interrupted_run = app.tasks.get_task(task_id).run
    assert interrupted_run is not None
    app.store._db.execute(  # noqa: SLF001 - model the lease's natural expiry.
        "UPDATE run_leases SET expires_at = ? WHERE run_id = ?",
        (
            (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            interrupted_run.run_id,
        ),
    )
    app.store._db.commit()  # noqa: SLF001
    result = app.run_task(task_id, _inputs(), recover_stale_lease=True)
    final_events = app.store.read(task_id)

    assert result.status is TaskStatus.COMPLETED
    assert result.run is not None
    assert result.run.status is RunStatus.SUCCEEDED
    assert final_events[-1].event_type is TaskEventType.RUN_SUCCEEDED

    node_completion_ids = [
        event.decoded_payload().get("node_id")
        for event in final_events
        if event.event_type is TaskEventType.NODE_COMPLETED
    ]
    assert node_completion_ids == ["prefix_write", "verify", "evaluate", "done"]
    assert "tests" not in node_completion_ids

    assert result.observed_outcome is not None
    final_evidence = result.observed_outcome.evidence_refs
    assert prefix_artifact_id in final_evidence
    assert len(final_evidence) == 2

    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
