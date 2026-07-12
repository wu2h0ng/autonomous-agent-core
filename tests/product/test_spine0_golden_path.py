from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from agent_os_contracts import (
    EdgeSpec,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    ProviderToolProposal,
    RunStatus,
    TaskStatus,
    WorkflowGraph,
)
from apps.api_server.app import AgentOSApplication
from agent_os_core import DeterministicProvider, RunExecutionError, WorkerInterrupted


NOW = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)


def _workflow() -> WorkflowGraph:
    nodes = (
        NodeSpec(node_id="read", kind=NodeKind.TOOL, capability="workspace.read", idempotency=IdempotencyMode.IDEMPOTENT),
        NodeSpec(node_id="provider", kind=NodeKind.PROVIDER, capability="provider.chat"),
        NodeSpec(node_id="approve", kind=NodeKind.APPROVAL),
        NodeSpec(node_id="apply", kind=NodeKind.TOOL, capability="workspace.apply_patch", idempotency=IdempotencyMode.COMPENSATABLE),
        NodeSpec(node_id="tests", kind=NodeKind.TOOL, capability="workspace.run_tests", idempotency=IdempotencyMode.COMPENSATABLE),
        NodeSpec(node_id="evaluate", kind=NodeKind.EVALUATION),
        NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
    )
    edges = tuple(EdgeSpec(source=source, target=target) for source, target in (
        ("read", "provider"), ("provider", "approve"), ("approve", "apply"), ("apply", "tests"),
        ("tests", "evaluate"), ("evaluate", "done"),
    ))
    return WorkflowGraph(
        workflow_id="workflow:developer-golden-path", version=1,
        tenant_id="tenant:local", workspace_id="workspace:local", created_by="user:local",
        created_at=NOW, policy_version="policy-1", evaluator_refs=("evaluator:pytest:1",),
        nodes=nodes, edges=edges,
    )


def test_restart_safe_store_survives_new_service_instance(tmp_path) -> None:
    path = tmp_path / "agent-os.sqlite3"
    first = AgentOSApplication(database=path, workspace=tmp_path)
    task = first.create_task({
        "goal_id": "goal:1", "tenant_id": "tenant:local", "workspace_id": "workspace:local",
        "created_by": "user:local", "created_at": NOW, "statement": "patch fixture",
    })
    second = AgentOSApplication(database=path, workspace=tmp_path)
    assert second.task_json(task.task_id)["status"] == "DRAFT"


def test_developer_golden_path_real_read_patch_tests_and_outcome(tmp_path) -> None:
    (tmp_path / "fixture.txt").write_text("before\n", encoding="utf-8")
    (tmp_path / "test_fixture.py").write_text("def test_fixture():\n    assert open('fixture.txt').read() == 'after\\n'\n", encoding="utf-8")
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
        "goal_id": "goal:2", "tenant_id": "tenant:local", "workspace_id": "workspace:local",
        "created_by": "user:local", "created_at": NOW, "statement": "patch fixture",
    })
    commitment = {
        "commitment_id": "commitment:2", "task_id": task.task_id, "goal_id": "goal:2",
        "tenant_id": "tenant:local", "workspace_id": "workspace:local", "accepted_by": "user:local",
        "accepted_at": NOW, "deliverables": ["fixture patch"], "acceptance_criteria": ["pytest passes"],
        "authority_scopes": ["workspace:read", "workspace:write"],
        "budget": {"max_cost_usd": "1", "max_duration_seconds": 300, "max_provider_tokens": 1000, "max_tool_calls": 10},
        "risk_tier": 1, "exit_conditions": ["verified"], "expires_at": NOW + timedelta(hours=1),
    }
    expected = {
        "expected_outcome_id": "expected:2", "task_id": task.task_id, "tenant_id": "tenant:local",
        "workspace_id": "workspace:local", "evaluator_type": "pytest", "evaluator_version": "1",
        "evidence_requirements": ["test-report"], "failure_semantics": ["non-zero exit"],
        "threshold": 1, "observation_window_seconds": 60, "frozen_at": NOW,
    }
    app.commit_task(task.task_id, {"commitment": commitment, "workflow": _workflow().model_dump(mode="json"), "expected_outcome": expected})
    inputs = {"target_path": "fixture.txt", "test_command": "python -m pytest"}
    assert "content" not in inputs
    try:
        app.run_task(task.task_id, inputs, stop_after_node="read")
    except WorkerInterrupted:
        pass
    restarted = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    restarted.provider = app.provider
    restarted.provider_configured = True
    waiting = restarted.run_task(task.task_id, inputs, recover_stale_lease=True)
    assert waiting.run is not None
    assert waiting.run.status is RunStatus.WAITING_APPROVAL
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "before\n"
    approved = restarted.record_approval(
        task.task_id,
        {"disposition": "APPROVE", "reason": "Reviewed provider patch"},
    )
    assert approved.approval is not None
    result = restarted.run_task(task.task_id, inputs)
    assert result.status is TaskStatus.COMPLETED
    assert result.observed_outcome is not None
    assert result.observed_outcome.status.value == "VERIFIED"
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "after\n"
    assert len(result.artifacts) == 1
    completed_nodes = {
        event.decoded_payload()["node_id"]
        for event in restarted.store.read(task.task_id)
        if event.event_type.value == "NODE_COMPLETED"
    }
    assert completed_nodes == {"read", "provider", "approve", "apply", "tests", "evaluate", "done"}
    requests = app.provider.requests
    assert len(requests) == 1
    assert requests[0].allowed_capability_ids == ("workspace.apply_patch",)


def test_malformed_provider_output_has_zero_file_effects(tmp_path) -> None:
    target = tmp_path / "fixture.txt"
    target.write_text("before\n", encoding="utf-8")
    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    app.provider = DeterministicProvider(
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:valid-but-ambiguous",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps({"path": "fixture.txt", "content": "after\n"}),
            ),
            ProviderToolProposal(
                proposal_id="proposal:unauthorized",
                capability_id="artifact.write",
                arguments_json=json.dumps({"content": "not authorized"}),
            ),
        )
    )
    app.provider_configured = True
    task = app.create_task({
        "goal_id": "goal:malformed", "tenant_id": "tenant:local", "workspace_id": "workspace:local",
        "created_by": "user:local", "created_at": NOW, "statement": "patch fixture",
    })
    app.commit_task(task.task_id, {
        "commitment": {
            "commitment_id": "commitment:malformed", "task_id": task.task_id, "goal_id": "goal:malformed",
            "tenant_id": "tenant:local", "workspace_id": "workspace:local", "accepted_by": "user:local",
            "accepted_at": NOW, "deliverables": ["fixture patch"], "acceptance_criteria": ["pytest passes"],
            "authority_scopes": ["workspace:read", "workspace:write"],
            "budget": {"max_cost_usd": "1", "max_duration_seconds": 300, "max_provider_tokens": 1000, "max_tool_calls": 10},
            "risk_tier": 1, "exit_conditions": ["verified"], "expires_at": NOW + timedelta(hours=1),
        },
        "workflow": _workflow().model_dump(mode="json"),
        "expected_outcome": {
            "expected_outcome_id": "expected:malformed", "task_id": task.task_id,
            "tenant_id": "tenant:local", "workspace_id": "workspace:local", "evaluator_type": "pytest",
            "evaluator_version": "1", "evidence_requirements": ["test-report"],
            "failure_semantics": ["non-zero exit"], "threshold": 1,
            "observation_window_seconds": 60, "frozen_at": NOW,
        },
    })

    with pytest.raises(RunExecutionError, match="node provider failed"):
        app.run_task(task.task_id, {"target_path": "fixture.txt", "test_command": "python -m pytest"})

    assert target.read_text(encoding="utf-8") == "before\n"
    receipts = [
        event.decoded_payload()["receipt"]
        for event in app.store.read(task.task_id)
        if event.event_type.value == "ACTION_RECEIPT_RECORDED"
    ]
    assert all(receipt["connector_id"] != "workspace.apply_patch" for receipt in receipts)

    app.provider = DeterministicProvider(
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:retry",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps({"path": "fixture.txt", "content": "after\n"}),
            ),
        )
    )
    retried = app.run_task(
        task.task_id,
        {"target_path": "fixture.txt", "test_command": "python -m pytest"},
    )
    assert retried.run is not None
    assert retried.run.status is RunStatus.WAITING_APPROVAL
    assert target.read_text(encoding="utf-8") == "before\n"
