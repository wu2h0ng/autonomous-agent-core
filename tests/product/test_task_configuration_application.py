from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Event, Thread

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    Commitment,
    EdgeSpec,
    ExpectedOutcome,
    Goal,
    NodeKind,
    NodeSpec,
    ResourceBudget,
    TaskConfigurationSnapshotCommand,
    WorkflowGraph,
)
from agent_os_core import (
    TASK_CONFIGURATION_CAPABILITY,
    TaskConfigurationDrift,
    TaskConfigurationNotFound,
)
from apps.api_server.app import AgentOSApplication


NOW = datetime(2026, 7, 15, 21, 0, tzinfo=timezone.utc)


def _commit(app: AgentOSApplication, suffix: str = "1") -> str:
    goal = Goal(
        goal_id=f"goal:configuration:{suffix}",
        tenant_id=app.principal.tenant_id,
        workspace_id=app.principal.workspace_id,
        created_by=app.principal.principal_id,
        created_at=NOW,
        statement="bind immutable task configuration",
    )
    task = app.tasks.create_task(goal)
    budget = ResourceBudget(
        max_cost_usd=Decimal("1"),
        max_duration_seconds=300,
        max_provider_tokens=0,
        max_tool_calls=1,
    )
    commitment = Commitment(
        commitment_id=f"commitment:configuration:{suffix}",
        task_id=task.task_id,
        goal_id=goal.goal_id,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        accepted_by=goal.created_by,
        accepted_at=NOW,
        deliverables=("result",),
        acceptance_criteria=("verified",),
        authority_scopes=("workspace.read", TASK_CONFIGURATION_CAPABILITY),
        budget=budget,
        risk_tier=1,
        exit_conditions=("done",),
        expires_at=NOW + timedelta(days=30),
    )
    workflow = WorkflowGraph(
        workflow_id=f"workflow:configuration:{suffix}",
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
    expected = ExpectedOutcome(
        expected_outcome_id=f"outcome:configuration:{suffix}",
        task_id=task.task_id,
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
    app.tasks.commit_task(task.task_id, commitment, workflow, expected)
    return task.task_id


def test_application_seal_get_list_and_restart_exact_snapshot(tmp_path) -> None:
    database = tmp_path / "configuration.sqlite3"
    app = AgentOSApplication(database=database, workspace=tmp_path)
    assert TASK_CONFIGURATION_CAPABILITY in app.grants
    task_id = _commit(app)

    snapshot = app.seal_task_configuration(task_id, {})

    assert snapshot.optional_prior is None
    assert app.get_task_configuration(task_id, snapshot.snapshot_id) == snapshot
    assert app.list_task_configurations(task_id) == (snapshot,)

    restarted = AgentOSApplication(database=database, workspace=tmp_path)
    assert (
        restarted.get_task_configuration(task_id, snapshot.snapshot_id).model_dump_json()
        == snapshot.model_dump_json()
    )
    assert restarted.list_task_configurations(task_id) == (snapshot,)


def test_application_bound_start_and_drift_fail_before_run_event(tmp_path) -> None:
    app = AgentOSApplication(
        database=tmp_path / "bound-start.sqlite3",
        workspace=tmp_path,
    )
    task_id = _commit(app)
    snapshot = app.seal_task_configuration(task_id, {})

    with pytest.raises(TaskConfigurationNotFound, match="snapshot"):
        app.start_run(task_id, "task-configuration:wrong")

    app.provider_profile = app.provider_profile.model_copy(
        update={"model_id": "drifted-after-seal"}
    )
    with pytest.raises(TaskConfigurationDrift, match="configuration"):
        app.start_run(task_id, snapshot.snapshot_id)
    assert app.tasks.get_task(task_id).run is None


def test_application_legacy_start_remains_compatible(tmp_path) -> None:
    app = AgentOSApplication(
        database=tmp_path / "legacy-start.sqlite3",
        workspace=tmp_path,
    )
    task_id = _commit(app)

    started = app.start_run(task_id)

    assert started.run is not None
    assert started.run.configuration_snapshot_id is None


def test_application_rejects_authoritative_snapshot_body_fields(tmp_path) -> None:
    app = AgentOSApplication(
        database=tmp_path / "closed-command.sqlite3",
        workspace=tmp_path,
    )
    task_id = _commit(app)

    with pytest.raises(ValidationError):
        app.seal_task_configuration(
            task_id,
            {
                "policy_digest": "a" * 64,
                "activation": True,
            },
        )

    command = TaskConfigurationSnapshotCommand()
    assert command.prior_selector is None


def test_run_rejects_snapshot_or_prior_content_before_start_or_effect(tmp_path) -> None:
    app = AgentOSApplication(
        database=tmp_path / "closed-runtime-input.sqlite3",
        workspace=tmp_path,
    )
    task_id = _commit(app)
    snapshot = app.seal_task_configuration(task_id, {})
    app.provider_configured = True

    with pytest.raises(ValueError, match="configuration.*forbidden"):
        app.run_task(
            task_id,
            {"optional_prior": {"activation": True}},
            configuration_snapshot_id=snapshot.snapshot_id,
        )

    assert app.tasks.get_task(task_id).run is None


def test_workspace_reconfiguration_cannot_interleave_snapshot_append(tmp_path) -> None:
    app = AgentOSApplication(
        database=tmp_path / "configuration-lock.sqlite3",
        workspace=tmp_path,
    )
    task_id = _commit(app)
    reader_entered = Event()
    release_reader = Event()
    workspace_done = Event()
    failures: list[BaseException] = []
    original_reader = app.task_configurations._configuration_reader

    def blocking_reader():  # type: ignore[no-untyped-def]
        reader_entered.set()
        if not release_reader.wait(timeout=5):
            raise TimeoutError("test did not release configuration reader")
        return original_reader()

    app.task_configurations._configuration_reader = blocking_reader

    def seal() -> None:
        try:
            app.seal_task_configuration(task_id, {})
        except BaseException as exc:
            failures.append(exc)

    def reattach() -> None:
        try:
            app.attach_workspace({"path": str(tmp_path.resolve())})
        except BaseException as exc:
            failures.append(exc)
        finally:
            workspace_done.set()

    seal_thread = Thread(target=seal)
    seal_thread.start()
    assert reader_entered.wait(timeout=5)
    attach_thread = Thread(target=reattach)
    attach_thread.start()
    assert not workspace_done.wait(timeout=0.1)

    release_reader.set()
    seal_thread.join(timeout=5)
    attach_thread.join(timeout=5)

    assert not failures
    assert app.tasks.get_task(task_id).configuration_snapshot is not None
    assert workspace_done.is_set()
