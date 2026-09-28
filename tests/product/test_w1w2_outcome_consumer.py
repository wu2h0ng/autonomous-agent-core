"""P0-3 Inc3: W1/W2 outcome consumer (SRL closed-loop last hop).

Fail-closed, structurally confined to the typed in-envelope W1State (A-SRL-1 I-22 /
AC-14), default-off at the composition root, with a digest-bound audit event.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from agent_os_contracts import (
    EdgeSpec,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    ObservedOutcome,
    OutcomeStatus,
    ProviderToolProposal,
    TaskEventType,
    WorkflowGraph,
)
from agent_os_core import DeterministicProvider
from agent_os_core.w1w2_consumer import (
    W1State,
    W1W2OutcomeConsumer,
    W1W2UpdateReason,
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
        workflow_id="workflow:w1w2",
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


def _commit(app: AgentOSApplication, task, *, goal_id: str) -> None:
    app.commit_task(task.task_id, {
        "commitment": {
            "commitment_id": f"commitment:{goal_id}", "task_id": task.task_id, "goal_id": goal_id,
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
            "expected_outcome_id": f"expected:{goal_id}", "task_id": task.task_id,
            "tenant_id": "tenant:local", "workspace_id": "workspace:local",
            "evaluator_type": "pytest", "evaluator_version": "1",
            "evidence_requirements": ["test-report"], "failure_semantics": ["non-zero exit"],
            "threshold": 1, "observation_window_seconds": 3600, "frozen_at": NOW,
        },
    })


def _verified(tmp_path, *, enabled: bool = True):
    """Run the real golden path; return (app, task_id, verified outcome)."""
    (tmp_path / "fixture.txt").write_text("before\n", encoding="utf-8")
    (tmp_path / "test_fixture.py").write_text(
        "def test_fixture():\n    assert open('fixture.txt').read() == 'after\\n'\n",
        encoding="utf-8",
    )
    app = AgentOSApplication(
        database=tmp_path / "agent-os.sqlite3",
        workspace=tmp_path,
        w1w2_learning_enabled=enabled,
    )
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
        "goal_id": "goal:w1w2", "tenant_id": "tenant:local",
        "workspace_id": "workspace:local", "created_by": "user:local",
        "created_at": NOW, "statement": "patch fixture",
    })
    _commit(app, task, goal_id="goal:w1w2")
    inputs = {"target_path": "fixture.txt", "test_command": "python -m pytest"}
    try:
        app.run_task(task.task_id, inputs, stop_after_node="read")
    except Exception:
        pass
    restarted = AgentOSApplication(
        database=tmp_path / "agent-os.sqlite3",
        workspace=tmp_path,
        w1w2_learning_enabled=enabled,
    )
    restarted.provider = app.provider
    restarted.provider_configured = True
    restarted.run_task(task.task_id, inputs, recover_stale_lease=True)
    restarted.record_approval(task.task_id, {"disposition": "APPROVE", "reason": "reviewed"})
    result = restarted.run_task(task.task_id, inputs)
    assert result.observed_outcome is not None
    assert result.observed_outcome.status is OutcomeStatus.VERIFIED
    return restarted, task.task_id, result.observed_outcome


def _committed_only(tmp_path):
    (tmp_path / "test_fixture.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    app = AgentOSApplication(
        database=tmp_path / "agent-os.sqlite3", workspace=tmp_path, w1w2_learning_enabled=True
    )
    task = app.create_task({
        "goal_id": "goal:c", "tenant_id": "tenant:local",
        "workspace_id": "workspace:local", "created_by": "user:local",
        "created_at": NOW, "statement": "x",
    })
    return app, task.task_id


def _forged(task_id: str, *, status=OutcomeStatus.VERIFIED, oid="observed:forged") -> ObservedOutcome:
    return ObservedOutcome(
        observed_outcome_id=oid,
        expected_outcome_id="expected:w1w2",
        task_id=task_id,
        run_id="run",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        status=status,
        score=1.0 if status is OutcomeStatus.VERIFIED else None,
        confidence=1.0,
        evidence_refs=("artifact:x",),
        observed_at=NOW,
    )


def _envelope_digest(app, task_id):
    task = app.tasks.get_task(task_id)
    return (
        task.goal.model_dump(mode="json") if task.goal else None,
        task.commitment.model_dump(mode="json") if task.commitment else None,
        task.expected_outcome.model_dump(mode="json") if task.expected_outcome else None,
        task.workflow.model_dump(mode="json") if task.workflow else None,
    )


def _w1w2_events(app, task_id):
    return [
        json.loads(e.payload_json)
        for e in app.store.read(task_id)
        if e.event_type is TaskEventType.W1W2_UPDATED
    ]


def test_refused_admission_produces_no_mutation(tmp_path):
    app, task_id = _committed_only(tmp_path)
    consumer = W1W2OutcomeConsumer(app.tasks)
    before = consumer.w1_state().digest()
    decision = consumer.consume(task_id, _forged(task_id))
    assert decision.applied is False
    assert decision.reason_code is W1W2UpdateReason.REFUSED
    assert consumer.w1_state().digest() == before
    assert _w1w2_events(app, task_id) == []


def test_admitted_outcome_updates_only_w1state(tmp_path):
    # I-22 / AC-14: the update touches ONLY the typed W1State; the task's
    # Mandate-bound objects (goal/commitment/expected_outcome/workflow) are unchanged.
    app, task_id, observed = _verified(tmp_path)
    consumer = W1W2OutcomeConsumer(app.tasks)
    envelope_before = _envelope_digest(app, task_id)
    decision = consumer.consume(task_id, observed)
    assert decision.applied is True
    assert decision.reason_code is W1W2UpdateReason.UPDATED
    assert decision.w1_before_digest != decision.w1_after_digest
    assert _envelope_digest(app, task_id) == envelope_before


def test_update_cannot_derive_a_mandate_envelope(tmp_path):
    # AC-14: W1State has no Mandate/Envelope/StandingMission/grant/policy field, and
    # the consumer exposes no such mutation surface.
    assert set(W1State.model_fields) == {"schema_version", "weights"}
    for field_name in W1State.model_fields:
        lowered = field_name.lower()
        assert "mandate" not in lowered and "envelope" not in lowered
        assert "grant" not in lowered and "policy" not in lowered
    app, task_id, observed = _verified(tmp_path)
    consumer = W1W2OutcomeConsumer(app.tasks)
    consumer.consume(task_id, observed)
    for attribute in dir(consumer):
        lowered = attribute.lower()
        assert "mandate" not in lowered
        assert "envelope" not in lowered
        assert "grant" not in lowered


def test_update_is_deterministic_and_idempotent_per_outcome(tmp_path):
    app, task_id, observed = _verified(tmp_path)
    consumer = W1W2OutcomeConsumer(app.tasks)
    consumer.consume(task_id, observed)
    after_first = consumer.w1_state().digest()
    second = consumer.consume(task_id, observed)
    assert second.reason_code is W1W2UpdateReason.DUPLICATE
    assert second.applied is False
    assert consumer.w1_state().digest() == after_first
    # determinism: the fixed rule moves the weight from 0.5 toward the score 1.0 by
    # step 0.5 -> exactly 0.75, independent of any randomness or model
    assert consumer.w1_state().weights["goal:w1w2"] == 0.75
    # durable idempotency: a fresh consumer (new instance) still refuses to re-apply
    replay = W1W2OutcomeConsumer(app.tasks).consume(task_id, observed)
    assert replay.reason_code is W1W2UpdateReason.DUPLICATE
    assert len(_w1w2_events(app, task_id)) == 1


def test_update_records_digest_bound_audit_event(tmp_path):
    app, task_id, observed = _verified(tmp_path)
    consumer = W1W2OutcomeConsumer(app.tasks)
    decision = consumer.consume(task_id, observed)
    events = _w1w2_events(app, task_id)
    assert len(events) == 1
    payload = events[0]
    assert payload["outcome_id"] == observed.observed_outcome_id
    assert payload["candidate_key"] == "goal:w1w2"
    assert payload["w1_before_digest"] == decision.w1_before_digest
    assert payload["w1_after_digest"] == decision.w1_after_digest
    assert payload["run_id"] == observed.run_id


def test_model_narration_or_stale_outcome_is_never_consumed(tmp_path):
    app, task_id, observed = _verified(tmp_path)
    consumer = W1W2OutcomeConsumer(app.tasks)
    before = consumer.w1_state().digest()
    # model narration: self-reported VERIFIED with no registered evaluator evidence
    narration = observed.model_copy(
        update={"status": OutcomeStatus.UNRESOLVED, "score": None, "evidence_refs": ()}
    )
    assert consumer.consume(task_id, narration).reason_code is W1W2UpdateReason.REFUSED
    # stale: a genuine id replaced by a non-current one
    stale = observed.model_copy(update={"observed_outcome_id": "observed:not-current"})
    assert consumer.consume(task_id, stale).reason_code is W1W2UpdateReason.REFUSED
    assert consumer.w1_state().digest() == before
    assert _w1w2_events(app, task_id) == []


def test_consumer_is_default_off_at_the_composition_root(tmp_path):
    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    assert app.w1w2_consumer is None
    with pytest.raises(RuntimeError):
        app.consume_outcome_for_learning("task:any", _forged("task:any"))
    enabled = AgentOSApplication(
        database=tmp_path / "agent-os-2.sqlite3", workspace=tmp_path, w1w2_learning_enabled=True
    )
    assert enabled.w1w2_consumer is not None
