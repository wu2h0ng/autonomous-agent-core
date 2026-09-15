"""P0-3 Increment 1: SRL execution bridge behavioural tests.

Condition-compliant flow: commit -> seal (reserves run id) -> verify C7 with the
reserved run id -> start. Denials are fail-closed and effect-free.
"""

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
    TaskStatus,
    WorkflowGraph,
)
from agent_os_core import TASK_CONFIGURATION_CAPABILITY
from agent_os_core.c7_receipt import C7ReceiptIssuer, C7ReceiptVerifier
from agent_os_core.srl_execution import (
    ExecutionDenialReason,
    SrlExecutionPlan,
    SrlTaskExecutionBridge,
)
from apps.api_server.app import AgentOSApplication


NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


class _PlanPort:
    def __init__(self, plan: SrlExecutionPlan | None) -> None:
        self._plan = plan

    def resolve(self, task_id: str) -> SrlExecutionPlan | None:
        return self._plan


class _HaltingSealer:
    """Seals via the real service then halts C7 (simulates a mid-window change)."""

    def __init__(self, inner, admin, scope_kind: str, scope_id: str) -> None:
        self._inner = inner
        self._admin = admin
        self._kind = scope_kind
        self._id = scope_id

    def seal(self, principal, task_id, command):
        snapshot = self._inner.seal(principal, task_id, command)
        # Admin authority halts the scope after commit+seal, before start.
        self._admin.correct(self._kind, self._id, "halt before start")
        return snapshot


def _goal(app, suffix="1") -> Goal:
    return Goal(
        goal_id=f"goal:srl-exec:{suffix}",
        tenant_id=app.principal.tenant_id,
        workspace_id=app.principal.workspace_id,
        created_by=app.principal.principal_id,
        created_at=NOW,
        statement="execute the activated work",
    )


def _plan(app, task) -> SrlExecutionPlan:
    goal = task.goal
    commitment = Commitment(
        commitment_id="commitment:srl-exec:1",
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
        workflow_id="workflow:srl-exec:1",
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
        expected_outcome_id="expected:srl-exec:1",
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


def _bridge(app, task, plan, *, sealer=None) -> SrlTaskExecutionBridge:
    authority = app.correction
    return SrlTaskExecutionBridge(
        task_service=app.tasks,
        plan_port=_PlanPort(plan),
        snapshot_sealer=sealer or app.task_configurations,
        principal=app.principal,
        c7_issuer=C7ReceiptIssuer(
            authority,
            tenant_id=app.principal.tenant_id,
            workspace_id=app.principal.workspace_id,
            issuer_id="c7:issuer",
        ),
        c7_verifier=C7ReceiptVerifier(authority),
    )


def test_draft_task_commits_and_starts_a_run(tmp_path):
    app = AgentOSApplication(database=tmp_path / "srl-exec.sqlite3", workspace=tmp_path)
    task = app.tasks.create_task(_goal(app))
    plan = _plan(app, task)
    result = _bridge(app, task, plan).commit_and_start(
        task.task_id, snapshot_command=TaskConfigurationSnapshotCommand()
    )
    assert result.committed is True
    assert result.started is True
    assert result.run_id is not None
    started = app.tasks.get_task(task.task_id)
    assert started.run is not None
    assert started.run.run_id == result.run_id


def test_activated_task_cannot_commit_without_trusted_plan(tmp_path):
    app = AgentOSApplication(database=tmp_path / "srl-exec.sqlite3", workspace=tmp_path)
    task = app.tasks.create_task(_goal(app))
    result = _bridge(app, task, None).commit_and_start(task.task_id)
    assert result.committed is False
    assert result.denial_reason is ExecutionDenialReason.PLAN_UNAVAILABLE


def test_conflicting_second_commit_fails_closed(tmp_path):
    app = AgentOSApplication(database=tmp_path / "srl-exec.sqlite3", workspace=tmp_path)
    task = app.tasks.create_task(_goal(app))
    bridge = _bridge(app, task, _plan(app, task))
    first = bridge.commit_and_start(
        task.task_id, snapshot_command=TaskConfigurationSnapshotCommand()
    )
    assert first.started is True
    second = bridge.commit_and_start(
        task.task_id, snapshot_command=TaskConfigurationSnapshotCommand()
    )
    assert second.committed is False
    assert second.denial_reason is ExecutionDenialReason.TASK_NOT_DRAFT


def test_plan_scope_mismatch_fails_closed(tmp_path):
    app = AgentOSApplication(database=tmp_path / "srl-exec.sqlite3", workspace=tmp_path)
    task = app.tasks.create_task(_goal(app))
    plan = _plan(app, task)
    bad = plan.model_copy(
        update={"commitment": plan.commitment.model_copy(update={"tenant_id": "tenant:other"})}
    )
    result = _bridge(app, task, bad).commit_and_start(task.task_id)
    assert result.committed is False
    assert result.denial_reason is ExecutionDenialReason.PLAN_BINDING_MISMATCH


def test_c7_change_before_start_leaves_committed_without_effect(tmp_path):
    app = AgentOSApplication(database=tmp_path / "srl-exec.sqlite3", workspace=tmp_path)
    task = app.tasks.create_task(_goal(app))
    plan = _plan(app, task)
    sealer = _HaltingSealer(
        app.task_configurations, app.correction_admin, "task", task.task_id
    )
    result = _bridge(app, task, plan, sealer=sealer).commit_and_start(
        task.task_id, snapshot_command=TaskConfigurationSnapshotCommand()
    )
    assert result.committed is True
    assert result.started is False
    assert result.denial_reason is ExecutionDenialReason.C7_REJECTED
    aggregate = app.tasks.get_task(task.task_id)
    assert aggregate.status is TaskStatus.COMMITTED
    assert aggregate.run is None


def test_halted_c7_blocks_start(tmp_path):
    app = AgentOSApplication(database=tmp_path / "srl-exec.sqlite3", workspace=tmp_path)
    task = app.tasks.create_task(_goal(app))
    plan = _plan(app, task)
    # Halt the task scope; the bridge commits then fails the C7 guard before
    # start (the seal step is itself C7-guarded, so either denial is valid).
    app.correction_admin.correct("task", task.task_id, "halt task")
    result = _bridge(app, task, plan).commit_and_start(
        task.task_id, snapshot_command=TaskConfigurationSnapshotCommand()
    )
    assert result.committed is True
    assert result.started is False
    assert result.denial_reason in {
        ExecutionDenialReason.C7_REJECTED,
        ExecutionDenialReason.SNAPSHOT_REJECTED,
    }
    assert app.tasks.get_task(task.task_id).run is None


def test_misbound_evaluator_blocks_commit(tmp_path):
    app = AgentOSApplication(database=tmp_path / "srl-exec.sqlite3", workspace=tmp_path)
    task = app.tasks.create_task(_goal(app))
    plan = _plan(app, task)
    bad = plan.model_copy(
        update={
            "expected_outcome": plan.expected_outcome.model_copy(
                update={"evaluator_type": "unknown:evaluator"}
            )
        }
    )
    result = _bridge(app, task, bad).commit_and_start(task.task_id)
    assert result.committed is False
    assert result.denial_reason is ExecutionDenialReason.COMMIT_REJECTED
    assert app.tasks.get_task(task.task_id).run is None


def test_commit_succeeds_but_wrong_scope_is_denied_before_start(tmp_path):
    app = AgentOSApplication(database=tmp_path / "srl-exec.sqlite3", workspace=tmp_path)
    task = app.tasks.create_task(_goal(app))
    plan = _plan(app, task)
    # The plan's tenant is wrong -> binding denial before any commit.
    bad = plan.model_copy(
        update={"workflow": plan.workflow.model_copy(update={"workspace_id": "ws:other"})}
    )
    result = _bridge(app, task, bad).commit_and_start(task.task_id)
    assert result.committed is False
    assert app.tasks.get_task(task.task_id).status is TaskStatus.DRAFT
