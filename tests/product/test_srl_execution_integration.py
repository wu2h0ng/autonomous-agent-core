"""P0-3 Increment 1 production wiring: the execution bridge is composed by the
AgentOSApplication and reached through its public methods."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

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
import pytest

from agent_os_core import (
    TASK_CONFIGURATION_CAPABILITY,
    ExecutionDenialReason,
    PlanRegistrationDenialReason,
    SQLiteSrlExecutionPlanStore,
    SrlExecutionPlan,
    SrlExecutionPlanRegistrationError,
    SrlExecutionPlanRegistry,
)
from apps.api_server.app import AgentOSApplication


NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def _plan(app: AgentOSApplication, task) -> SrlExecutionPlan:
    goal = task.goal
    commitment = Commitment(
        commitment_id="commitment:srl-int:1",
        task_id=task.task_id,
        goal_id=goal.goal_id,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        accepted_by=goal.created_by,
        accepted_at=NOW,
        deliverables=("result",),
        acceptance_criteria=("verified",),
        authority_scopes=("workspace.read", TASK_CONFIGURATION_CAPABILITY),
        budget=ResourceBudget(
            max_cost_usd=Decimal("1"),
            max_duration_seconds=300,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        risk_tier=1,
        exit_conditions=("done",),
        expires_at=NOW + timedelta(days=30),
    )
    workflow = WorkflowGraph(
        workflow_id="workflow:srl-int:1",
        version=1,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        created_by=goal.created_by,
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=(
            NodeSpec(node_id="read", kind=NodeKind.TOOL, capability="workspace.read"),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(EdgeSpec(source="read", target="done"),),
    )
    expected = ExpectedOutcome(
        expected_outcome_id="expected:srl-int:1",
        task_id=task.task_id,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("tests fail",),
        threshold=1.0,
        observation_window_seconds=60,
        frozen_at=NOW,
    )
    return SrlExecutionPlan(
        task_id=task.task_id,
        commitment=commitment,
        workflow=workflow,
        expected_outcome=expected,
        capability_id="workspace.read",
    )


def _draft_task(app: AgentOSApplication):
    goal = Goal(
        goal_id="goal:srl-int:1",
        tenant_id=app.principal.tenant_id,
        workspace_id=app.principal.workspace_id,
        created_by=app.principal.principal_id,
        created_at=NOW,
        statement="execute the activated work",
    )
    return app.tasks.create_task(goal)


def test_application_wires_and_runs_the_srl_execution_bridge(tmp_path):
    app = AgentOSApplication(database=tmp_path / "srl-int.sqlite3", workspace=tmp_path)
    task = _draft_task(app)
    app.register_srl_execution_plan(_plan(app, task), registered_by="organ:srl")
    result = app.commit_and_start_srl_task(
        task.task_id, snapshot_command=TaskConfigurationSnapshotCommand()
    )
    assert result.committed is True
    assert result.started is True
    aggregate = app.tasks.get_task(task.task_id)
    assert aggregate.run is not None
    assert aggregate.run.run_id == result.run_id


def test_commit_and_start_without_registered_plan_denies(tmp_path):
    app = AgentOSApplication(database=tmp_path / "srl-int.sqlite3", workspace=tmp_path)
    task = _draft_task(app)
    result = app.commit_and_start_srl_task(task.task_id)
    assert result.committed is False
    assert result.denial_reason is ExecutionDenialReason.PLAN_UNAVAILABLE


def test_srl_execution_bridge_is_composed(tmp_path):
    app = AgentOSApplication(database=tmp_path / "srl-int.sqlite3", workspace=tmp_path)
    # The bridge and its trusted plan registry are owned by the composition root.
    assert app.srl_execution is not None
    assert app.srl_execution_plans.resolve("missing") is None


def test_registration_refuses_missing_registrant(tmp_path):
    app = AgentOSApplication(database=tmp_path / "srl-int.sqlite3", workspace=tmp_path)
    task = _draft_task(app)
    with pytest.raises(SrlExecutionPlanRegistrationError) as excinfo:
        app.srl_execution_plans.register(_plan(app, task), registered_by="")
    assert excinfo.value.reason is PlanRegistrationDenialReason.MISSING_REGISTRANT


def test_registration_refuses_duplicate_plan_without_overwrite(tmp_path):
    app = AgentOSApplication(database=tmp_path / "srl-int.sqlite3", workspace=tmp_path)
    task = _draft_task(app)
    plan = _plan(app, task)
    app.register_srl_execution_plan(plan, registered_by="organ:srl")
    with pytest.raises(SrlExecutionPlanRegistrationError) as excinfo:
        app.register_srl_execution_plan(plan, registered_by="organ:impostor")
    assert excinfo.value.reason is PlanRegistrationDenialReason.DUPLICATE_PLAN
    # the original registration is intact (no silent overwrite)
    assert app.srl_execution_plans.resolve(task.task_id) == plan
    assert app.srl_execution_plans.registered_by(task.task_id) == "organ:srl"


def test_app_registration_refuses_unknown_task(tmp_path):
    app = AgentOSApplication(database=tmp_path / "srl-int.sqlite3", workspace=tmp_path)
    task = _draft_task(app)
    forged = _plan(app, task).model_copy(update={"task_id": "task:missing"})
    with pytest.raises(SrlExecutionPlanRegistrationError) as excinfo:
        app.register_srl_execution_plan(forged, registered_by="organ:srl")
    assert excinfo.value.reason is PlanRegistrationDenialReason.TASK_UNAVAILABLE


def test_app_registration_refuses_non_draft_task(tmp_path):
    app = AgentOSApplication(database=tmp_path / "srl-int.sqlite3", workspace=tmp_path)
    task = _draft_task(app)
    plan = _plan(app, task)
    app.tasks.commit_task(task.task_id, plan.commitment, plan.workflow, plan.expected_outcome)
    with pytest.raises(SrlExecutionPlanRegistrationError) as excinfo:
        app.register_srl_execution_plan(plan, registered_by="organ:srl")
    assert excinfo.value.reason is PlanRegistrationDenialReason.TASK_NOT_DRAFT


def test_app_registration_refuses_binding_mismatch(tmp_path):
    app = AgentOSApplication(database=tmp_path / "srl-int.sqlite3", workspace=tmp_path)
    task = _draft_task(app)
    plan = _plan(app, task)
    # a tool capability not present in the workflow is not a coherent binding
    forged = plan.model_copy(update={"capability_id": "workspace.edit"})
    with pytest.raises(SrlExecutionPlanRegistrationError) as excinfo:
        app.register_srl_execution_plan(forged, registered_by="organ:srl")
    assert excinfo.value.reason is PlanRegistrationDenialReason.BINDING_MISMATCH


def test_app_registration_refuses_foreign_tenant_binding(tmp_path):
    app = AgentOSApplication(database=tmp_path / "srl-int.sqlite3", workspace=tmp_path)
    task = _draft_task(app)
    plan = _plan(app, task)
    forged = plan.model_copy(
        update={"commitment": plan.commitment.model_copy(update={"tenant_id": "tenant:other"})}
    )
    with pytest.raises(SrlExecutionPlanRegistrationError) as excinfo:
        app.register_srl_execution_plan(forged, registered_by="organ:srl")
    assert excinfo.value.reason is PlanRegistrationDenialReason.BINDING_MISMATCH


def test_durable_registry_survives_restart(tmp_path):
    source = AgentOSApplication(database=tmp_path / "src.sqlite3", workspace=tmp_path)
    task = _draft_task(source)
    plan = _plan(source, task)

    db = tmp_path / "plans.sqlite3"
    store = SQLiteSrlExecutionPlanStore(db)
    SrlExecutionPlanRegistry(store=store).register(plan, registered_by="organ:srl")
    store.close()

    reopened_store = SQLiteSrlExecutionPlanStore(db)
    reopened = SrlExecutionPlanRegistry(store=reopened_store)
    assert reopened.resolve(task.task_id) == plan
    assert reopened.registered_by(task.task_id) == "organ:srl"
    # a plan loaded from disk still refuses a duplicate (durability participates in N6)
    with pytest.raises(SrlExecutionPlanRegistrationError) as excinfo:
        reopened.register(plan, registered_by="organ:other")
    assert excinfo.value.reason is PlanRegistrationDenialReason.DUPLICATE_PLAN
    reopened_store.close()
