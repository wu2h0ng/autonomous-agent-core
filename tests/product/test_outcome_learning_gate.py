"""P0-3 Increment 2: OutcomeLearningGate behavioural tests.

The positive path runs the real developer golden path to obtain a genuinely
VERIFIED outcome; the denial paths use committed tasks with constructed outcomes.
The gate is read-only.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone


from agent_os_contracts import (
    EdgeSpec,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    ObservedOutcome,
    OutcomeStatus,
    ProviderToolProposal,
    WorkflowGraph,
)
from agent_os_core import DeterministicProvider
from agent_os_core.outcome_learning_gate import (
    OutcomeAdmissionReason,
    OutcomeLearningGate,
)
from apps.api_server.app import AgentOSApplication


NOW = datetime.now(timezone.utc)


def _workflow() -> WorkflowGraph:
    nodes = (
        NodeSpec(node_id="read", kind=NodeKind.TOOL, capability="workspace.read",
                 idempotency=IdempotencyMode.IDEMPOTENT),
        NodeSpec(node_id="provider", kind=NodeKind.PROVIDER, capability="provider.chat"),
        NodeSpec(node_id="approve", kind=NodeKind.APPROVAL),
        NodeSpec(node_id="apply", kind=NodeKind.TOOL, capability="workspace.apply_patch",
                 idempotency=IdempotencyMode.COMPENSATABLE),
        NodeSpec(node_id="tests", kind=NodeKind.TOOL, capability="workspace.run_tests",
                 idempotency=IdempotencyMode.COMPENSATABLE),
        NodeSpec(node_id="evaluate", kind=NodeKind.EVALUATION),
        NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
    )
    edges = tuple(
        EdgeSpec(source=s, target=t)
        for s, t in (
            ("read", "provider"), ("provider", "approve"), ("approve", "apply"),
            ("apply", "tests"), ("tests", "evaluate"), ("evaluate", "done"),
        )
    )
    return WorkflowGraph(
        schema_version="WorkflowGraph/dag_v1",
        workflow_id="workflow:learning-gate",
        version=1,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=nodes,
        edges=edges,
    )


def _verified(tmp_path):
    """Run the real golden path to completion and return (app, task_id, outcome)."""
    (tmp_path / "fixture.txt").write_text("before\n", encoding="utf-8")
    (tmp_path / "test_fixture.py").write_text(
        "def test_fixture():\n    assert open('fixture.txt').read() == 'after\\n'\n",
        encoding="utf-8",
    )
    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    app.provider = DeterministicProvider(
        text="",
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:fixture",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps({"path": "fixture.txt", "content": "after\n"}),
            ),
        ),
    )
    app.provider_configured = True
    task = app.create_task({
        "goal_id": "goal:lg", "tenant_id": "tenant:local",
        "workspace_id": "workspace:local", "created_by": "user:local",
        "created_at": NOW, "statement": "patch fixture",
    })
    app.commit_task(task.task_id, {
        "commitment": {
            "commitment_id": "commitment:lg", "task_id": task.task_id, "goal_id": "goal:lg",
            "tenant_id": "tenant:local", "workspace_id": "workspace:local",
            "accepted_by": "user:local", "accepted_at": NOW,
            "deliverables": ["fixture patch"], "acceptance_criteria": ["pytest passes"],
            "authority_scopes": ["workspace:read", "workspace:write"],
            "budget": {"max_cost_usd": "1", "max_duration_seconds": 300,
                       "max_provider_tokens": 1000, "max_tool_calls": 10},
            "risk_tier": 1, "exit_conditions": ["verified"],
            "expires_at": NOW + timedelta(hours=1),
        },
        "workflow": _workflow().model_dump(mode="json"),
        "expected_outcome": {
            "expected_outcome_id": "expected:lg", "task_id": task.task_id,
            "tenant_id": "tenant:local", "workspace_id": "workspace:local",
            "evaluator_type": "pytest", "evaluator_version": "1",
            "evidence_requirements": ["test-report"], "failure_semantics": ["non-zero exit"],
            "threshold": 1, "observation_window_seconds": 3600, "frozen_at": NOW,
        },
    })
    inputs = {"target_path": "fixture.txt", "test_command": "python -m pytest"}
    try:
        app.run_task(task.task_id, inputs, stop_after_node="read")
    except Exception:
        pass
    restarted = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    restarted.provider = app.provider
    restarted.provider_configured = True
    restarted.run_task(task.task_id, inputs, recover_stale_lease=True)
    restarted.record_approval(
        task.task_id, {"disposition": "APPROVE", "reason": "reviewed"}
    )
    result = restarted.run_task(task.task_id, inputs)
    assert result.observed_outcome is not None
    assert result.observed_outcome.status is OutcomeStatus.VERIFIED
    return restarted, task.task_id, result.observed_outcome


def _committed_only(tmp_path):
    (tmp_path / "test_fixture.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    task = app.create_task({
        "goal_id": "goal:c", "tenant_id": "tenant:local",
        "workspace_id": "workspace:local", "created_by": "user:local",
        "created_at": NOW, "statement": "x",
    })
    return app, task.task_id


def _outcome(*, task_id: str) -> ObservedOutcome:
    return ObservedOutcome(
        observed_outcome_id="observed:forged",
        expected_outcome_id="expected:lg",
        task_id=task_id,
        run_id="run",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        status=OutcomeStatus.VERIFIED,
        score=1.0,
        confidence=1.0,
        evidence_refs=("artifact:x",),
        observed_at=NOW,
    )


def test_admits_a_current_verified_outcome(tmp_path):
    app, task_id, observed = _verified(tmp_path)
    decision = OutcomeLearningGate(app.tasks).admit(task_id, observed)
    assert decision.admitted is True
    assert decision.reason_code is OutcomeAdmissionReason.ADMITTED


def test_rejects_unverified_outcome(tmp_path):
    app, task_id, observed = _verified(tmp_path)
    unverified = observed.model_copy(update={"status": OutcomeStatus.UNRESOLVED, "score": None})
    decision = OutcomeLearningGate(app.tasks).admit(task_id, unverified)
    assert decision.admitted is False
    assert decision.reason_code is OutcomeAdmissionReason.OUTCOME_NOT_VERIFIED


def test_rejects_scope_mismatch(tmp_path):
    app, task_id, observed = _verified(tmp_path)
    foreign = observed.model_copy(update={"tenant_id": "tenant:other"})
    decision = OutcomeLearningGate(app.tasks).admit(task_id, foreign)
    assert decision.admitted is False
    assert decision.reason_code is OutcomeAdmissionReason.OUTCOME_SCOPE_MISMATCH


def test_rejects_outcome_for_missing_expected_outcome(tmp_path):
    app, task_id = _committed_only(tmp_path)
    decision = OutcomeLearningGate(app.tasks).admit(task_id, _outcome(task_id=task_id))
    assert decision.admitted is False
    assert decision.reason_code is OutcomeAdmissionReason.NO_EXPECTED_OUTCOME


def _committed_with_evaluator(tmp_path, evaluator_type: str):
    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    task = app.create_task({
        "goal_id": "goal:ue", "tenant_id": "tenant:local",
        "workspace_id": "workspace:local", "created_by": "user:local",
        "created_at": NOW, "statement": "x",
    })
    workflow = _workflow().model_copy(
        update={"evaluator_refs": (f"evaluator:{evaluator_type}:1",)}
    )
    app.commit_task(task.task_id, {
        "commitment": {
            "commitment_id": "commitment:ue", "task_id": task.task_id, "goal_id": "goal:ue",
            "tenant_id": "tenant:local", "workspace_id": "workspace:local",
            "accepted_by": "user:local", "accepted_at": NOW,
            "deliverables": ["x"], "acceptance_criteria": ["x"],
            "authority_scopes": ["workspace:read"],
            "budget": {"max_cost_usd": "1", "max_duration_seconds": 300,
                       "max_provider_tokens": 0, "max_tool_calls": 1},
            "risk_tier": 1, "exit_conditions": ["x"],
            "expires_at": NOW + timedelta(hours=1),
        },
        "workflow": workflow.model_dump(mode="json"),
        "expected_outcome": {
            "expected_outcome_id": "expected:ue", "task_id": task.task_id,
            "tenant_id": "tenant:local", "workspace_id": "workspace:local",
            "evaluator_type": evaluator_type, "evaluator_version": "1",
            "evidence_requirements": ["x"], "failure_semantics": ["x"],
            "threshold": 1, "observation_window_seconds": 3600, "frozen_at": NOW,
        },
    })
    return app, task.task_id


def test_rejects_unknown_evaluator(tmp_path):
    app, task_id = _committed_with_evaluator(tmp_path, "unknown:evaluator")
    outcome = ObservedOutcome(
        observed_outcome_id="observed:ue",
        expected_outcome_id="expected:ue",
        task_id=task_id,
        run_id="run",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="unknown:evaluator",
        evaluator_version="1",
        status=OutcomeStatus.VERIFIED,
        score=1.0,
        confidence=1.0,
        evidence_refs=("x",),
        observed_at=NOW,
    )
    decision = OutcomeLearningGate(app.tasks).admit(task_id, outcome)
    assert decision.admitted is False
    assert decision.reason_code is OutcomeAdmissionReason.UNKNOWN_EVALUATOR


def test_rejects_forged_verified_evidence(tmp_path):
    app, task_id, observed = _verified(tmp_path)
    forged = observed.model_copy(update={"score": 0.5})
    decision = OutcomeLearningGate(app.tasks).admit(task_id, forged)
    assert decision.admitted is False
    assert decision.reason_code is OutcomeAdmissionReason.EVIDENCE_INVALID


def test_rejects_non_current_outcome(tmp_path):
    app, task_id, observed = _verified(tmp_path)
    other = observed.model_copy(update={"observed_outcome_id": "observed:not-current"})
    decision = OutcomeLearningGate(app.tasks).admit(task_id, other)
    assert decision.admitted is False
    assert decision.reason_code is OutcomeAdmissionReason.OUTCOME_NOT_CURRENT


def test_gate_does_not_mutate_task_state(tmp_path):
    app, task_id, observed = _verified(tmp_path)
    before = app.tasks.get_task(task_id)
    OutcomeLearningGate(app.tasks).admit(task_id, observed)
    after = app.tasks.get_task(task_id)
    assert before == after
