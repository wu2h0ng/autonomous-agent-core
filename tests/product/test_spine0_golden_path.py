from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import threading
import time

import pytest

from agent_os_contracts import (
    EdgeSpec,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    ProviderToolProposal,
    RunStatus,
    TaskEventType,
    TaskStatus,
    WorkflowGraph,
)
from apps.api_server.app import AgentOSApplication
from agent_os_core import DeterministicProvider, RunExecutionError, WorkerInterrupted
from agent_os_core.errors import ConcurrentWriteError
from agent_os_core.execution import RunCoordinator


NOW = datetime.now(timezone.utc)


def _workflow() -> WorkflowGraph:
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
            idempotency=IdempotencyMode.COMPENSATABLE,
        ),
        NodeSpec(node_id="evaluate", kind=NodeKind.EVALUATION),
        NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
    )
    edges = tuple(
        EdgeSpec(source=source, target=target)
        for source, target in (
            ("read", "provider"),
            ("provider", "approve"),
            ("approve", "apply"),
            ("apply", "tests"),
            ("tests", "evaluate"),
            ("evaluate", "done"),
        )
    )
    return WorkflowGraph(
        schema_version="WorkflowGraph/dag_v1",
        workflow_id="workflow:developer-golden-path",
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


def test_restart_safe_store_survives_new_service_instance(tmp_path) -> None:
    path = tmp_path / "agent-os.sqlite3"
    first = AgentOSApplication(database=path, workspace=tmp_path)
    task = first.create_task(
        {
            "goal_id": "goal:1",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": NOW,
            "statement": "patch fixture",
        }
    )
    second = AgentOSApplication(database=path, workspace=tmp_path)
    assert second.task_json(task.task_id)["status"] == "DRAFT"


def test_developer_golden_path_real_read_patch_tests_and_outcome(tmp_path) -> None:
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
                arguments_json=json.dumps(
                    {"path": "fixture.txt", "content": "after\n"}
                ),
            ),
        ),
    )
    app.provider_configured = True
    task = app.create_task(
        {
            "goal_id": "goal:2",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": NOW,
            "statement": "patch fixture",
        }
    )
    commitment = {
        "commitment_id": "commitment:2",
        "task_id": task.task_id,
        "goal_id": "goal:2",
        "tenant_id": "tenant:local",
        "workspace_id": "workspace:local",
        "accepted_by": "user:local",
        "accepted_at": NOW,
        "deliverables": ["fixture patch"],
        "acceptance_criteria": ["pytest passes"],
        "authority_scopes": ["workspace:read", "workspace:write"],
        "budget": {
            "max_cost_usd": "1",
            "max_duration_seconds": 300,
            "max_provider_tokens": 1000,
            "max_tool_calls": 10,
        },
        "risk_tier": 1,
        "exit_conditions": ["verified"],
        "expires_at": NOW + timedelta(hours=1),
    }
    expected = {
        "expected_outcome_id": "expected:2",
        "task_id": task.task_id,
        "tenant_id": "tenant:local",
        "workspace_id": "workspace:local",
        "evaluator_type": "pytest",
        "evaluator_version": "1",
        "evidence_requirements": ["test-report"],
        "failure_semantics": ["non-zero exit"],
        "threshold": 1,
        "observation_window_seconds": 3600,
        "frozen_at": NOW,
    }
    app.commit_task(
        task.task_id,
        {
            "commitment": commitment,
            "workflow": _workflow().model_dump(mode="json"),
            "expected_outcome": expected,
        },
    )
    inputs = {"target_path": "fixture.txt", "test_command": "python -m pytest"}
    assert "content" not in inputs
    try:
        app.run_task(task.task_id, inputs, stop_after_node="read")
    except WorkerInterrupted:
        pass
    restarted = AgentOSApplication(
        database=tmp_path / "agent-os.sqlite3", workspace=tmp_path
    )
    restarted.provider = app.provider
    restarted.provider_configured = True
    interrupted_run = restarted.tasks.get_task(task.task_id).run
    assert interrupted_run is not None
    restarted.store._db.execute(  # noqa: SLF001 - simulate natural lease expiry.
        "UPDATE run_leases SET expires_at = ? WHERE run_id = ?",
        (
            (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            interrupted_run.run_id,
        ),
    )
    restarted.store._db.commit()  # noqa: SLF001
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
    assert result.run is not None
    reader = AgentOSApplication(
        database=tmp_path / "agent-os.sqlite3", workspace=tmp_path
    )
    assert reader.task_json(task.task_id)["outcome_evidence_valid"] is True
    report = reader.tasks.validated_test_report(task.task_id, result.run.run_id)
    assert report is not None
    report_path = reader.sandbox.artifacts / report.artifact_ids[0].removeprefix(
        "artifact:"
    )
    report_path.unlink()
    assert (
        reader.tasks.validated_test_report(task.task_id, result.run.run_id) is None
    )
    completed_nodes = {
        event.decoded_payload()["node_id"]
        for event in restarted.store.read(task.task_id)
        if event.event_type.value == "NODE_COMPLETED"
    }
    assert completed_nodes == {
        "read",
        "provider",
        "approve",
        "apply",
        "tests",
        "evaluate",
        "done",
    }
    requests = app.provider.requests
    assert len(requests) == 1
    assert requests[0].allowed_capability_ids == ("workspace.apply_patch",)

    historical = reader.tasks.get_task(task.task_id)
    assert historical.observed_outcome is not None
    assert historical.observed_outcome.status.value == "VERIFIED"
    current = reader.tasks.current_outcome(task.task_id)
    assert current is not None
    assert current.status.value == "UNRESOLVED"
    projected = reader.task_json(task.task_id)
    assert projected["status"] == "FAILED"
    assert projected["run"]["status"] == "FAILED"
    assert projected["observed_outcome"]["status"] == "UNRESOLVED"
    assert projected["historical_observed_outcome"]["status"] == "VERIFIED"
    assert projected["outcome_evidence_valid"] is False
    compensated = reader.compensate_task(task.task_id)
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "before\n"
    assert compensated.compensations[-1].status.value == "COMPENSATED"


def test_stale_worker_cannot_commit_after_lease_takeover(tmp_path) -> None:
    (tmp_path / "fixture.txt").write_text("before\n", encoding="utf-8")
    (tmp_path / "test_fixture.py").write_text(
        "def test_fixture():\n    assert open('fixture.txt').read() == 'after\\n'\n",
        encoding="utf-8",
    )
    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    app.provider = DeterministicProvider(
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:fixture",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps(
                    {"path": "fixture.txt", "content": "after\n"}
                ),
            ),
        ),
    )
    app.provider_configured = True
    task = app.create_task(
        {
            "goal_id": "goal:lease",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": NOW,
            "statement": "patch fixture",
        }
    )
    app.commit_task(
        task.task_id,
        {
            "commitment": {
                "commitment_id": "commitment:lease",
                "task_id": task.task_id,
                "goal_id": "goal:lease",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "accepted_by": "user:local",
                "accepted_at": NOW,
                "deliverables": ["fixture patch"],
                "acceptance_criteria": ["pytest passes"],
                "authority_scopes": ["workspace:read", "workspace:write"],
                "budget": {
                    "max_cost_usd": "1",
                    "max_duration_seconds": 300,
                    "max_provider_tokens": 1000,
                    "max_tool_calls": 10,
                },
                "risk_tier": 1,
                "exit_conditions": ["verified"],
                "expires_at": NOW + timedelta(hours=1),
            },
            "workflow": _workflow().model_dump(mode="json"),
            "expected_outcome": {
                "expected_outcome_id": "expected:lease",
                "task_id": task.task_id,
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "evaluator_type": "pytest",
                "evaluator_version": "1",
                "evidence_requirements": ["test-report"],
                "failure_semantics": ["non-zero exit"],
                "threshold": 1,
                "observation_window_seconds": 3600,
                "frozen_at": NOW,
            },
        },
    )
    inputs = {"target_path": "fixture.txt", "test_command": "python -m pytest"}
    waiting = app.run_task(task.task_id, inputs)
    assert waiting.run is not None
    assert waiting.run.status is RunStatus.WAITING_APPROVAL
    app.record_approval(
        task.task_id,
        {"disposition": "APPROVE", "reason": "Reviewed provider patch"},
    )

    took_over = False
    stale_claim: tuple[str, int] | None = None

    def steal_lease(phase: str) -> None:
        nonlocal took_over, stale_claim
        if phase != "before_node_commit:apply" or took_over:
            return
        current = app.tasks.get_task(task.task_id)
        assert current.run is not None
        lease = app.store._db.execute(  # noqa: SLF001 - capture old worker identity.
            "SELECT owner, fence FROM run_leases WHERE run_id = ?",
            (current.run.run_id,),
        ).fetchone()
        assert lease is not None
        stale_claim = (str(lease["owner"]), int(lease["fence"]))
        expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        app.store._db.execute(  # noqa: SLF001 - targeted stale-worker regression.
            "UPDATE run_leases SET expires_at = ? WHERE run_id = ?",
            (expired, current.run.run_id),
        )
        app.store._db.commit()  # noqa: SLF001
        app.store.recover_lease(
            current.run.run_id,
            "worker:takeover",
            (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        )
        took_over = True

    with pytest.raises(RunExecutionError, match="lost its run lease"):
        app.run_task(task.task_id, inputs, execution_fence=steal_lease)

    completed = [
        event.decoded_payload()["node_id"]
        for event in app.store.read(task.task_id)
        if event.event_type.value == "NODE_COMPLETED"
    ]
    assert "apply" not in completed
    assert took_over is True
    assert stale_claim is not None
    with app.tasks.execution_scope():
        app.tasks.bind_execution_claim(
            task.task_id, waiting.run.run_id, stale_claim[0], stale_claim[1]
        )
        with pytest.raises(ConcurrentWriteError, match="stale execution lease"):
            app.tasks.update_run_status(
                task.task_id, RunStatus.PAUSED, event_type=TaskEventType.RUN_PAUSED
            )
    event_types_after_loss = [
        event.event_type.value for event in app.store.read(task.task_id)
    ]
    assert "NODE_FAILED" not in event_types_after_loss
    assert "RUN_FAILED" not in event_types_after_loss
    assert "ACTION_COMPENSATED" not in event_types_after_loss
    assert "COMPENSATION_STARTED" not in event_types_after_loss
    current = app.tasks.get_task(task.task_id)
    assert current.run is not None
    app.store._db.execute(  # noqa: SLF001 - takeover worker is now stale.
        "UPDATE run_leases SET expires_at = ? WHERE run_id = ?",
        (
            (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            current.run.run_id,
        ),
    )
    app.store._db.commit()  # noqa: SLF001

    recovered = app.run_task(task.task_id, inputs, recover_stale_lease=True)
    assert recovered.run is not None
    assert recovered.run.status is RunStatus.SUCCEEDED
    receipts = [
        event.decoded_payload()["receipt"]
        for event in app.store.read(task.task_id)
        if event.event_type.value == "ACTION_RECEIPT_RECORDED"
    ]
    assert [receipt["connector_id"] for receipt in receipts].count(
        "workspace.apply_patch"
    ) == 1


def test_run_wide_heartbeat_renews_lease_during_orchestration(tmp_path, monkeypatch) -> None:
    (tmp_path / "fixture.txt").write_text("before\n", encoding="utf-8")
    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    app.provider = DeterministicProvider(
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:fixture",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps(
                    {"path": "fixture.txt", "content": "after\n"}
                ),
            ),
        ),
    )
    app.provider_configured = True
    task = app.create_task(
        {
            "goal_id": "goal:heartbeat",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": NOW,
            "statement": "patch fixture",
        }
    )
    app.commit_task(
        task.task_id,
        {
            "commitment": {
                "commitment_id": "commitment:heartbeat",
                "task_id": task.task_id,
                "goal_id": "goal:heartbeat",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "accepted_by": "user:local",
                "accepted_at": NOW,
                "deliverables": ["fixture patch"],
                "acceptance_criteria": ["pytest passes"],
                "authority_scopes": ["workspace:read", "workspace:write"],
                "budget": {
                    "max_cost_usd": "1",
                    "max_duration_seconds": 300,
                    "max_provider_tokens": 1000,
                    "max_tool_calls": 10,
                },
                "risk_tier": 1,
                "exit_conditions": ["verified"],
                "expires_at": NOW + timedelta(hours=1),
            },
            "workflow": _workflow().model_dump(mode="json"),
            "expected_outcome": {
                "expected_outcome_id": "expected:heartbeat",
                "task_id": task.task_id,
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "evaluator_type": "pytest",
                "evaluator_version": "1",
                "evidence_requirements": ["test-report"],
                "failure_semantics": ["non-zero exit"],
                "threshold": 1,
                "observation_window_seconds": 3600,
                "frozen_at": NOW,
            },
        },
    )
    monkeypatch.setattr(RunCoordinator, "_LEASE_TTL", timedelta(milliseconds=200))
    takeover_result: list[str] = []

    def try_takeover(run_id: str) -> None:
        time.sleep(0.32)
        try:
            app.store.recover_lease(
                run_id,
                "worker:takeover",
                (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            )
            takeover_result.append("took-over")
        except ConcurrentWriteError:
            takeover_result.append("blocked")

    started = False

    def slow_provider(phase: str) -> None:
        nonlocal started
        # This phase sits outside the provider-specific heartbeat; the Run-wide
        # heartbeat must keep the lease alive while orchestration is blocked.
        if phase != "before_node:provider" or started:
            return
        started = True
        current = app.tasks.get_task(task.task_id)
        assert current.run is not None
        thread = threading.Thread(target=try_takeover, args=(current.run.run_id,))
        thread.start()
        time.sleep(0.5)
        thread.join(timeout=1)

    with pytest.raises(WorkerInterrupted):
        app.run_task(
            task.task_id,
            {"target_path": "fixture.txt", "test_command": "python -m pytest"},
            stop_after_node="provider",
            execution_fence=slow_provider,
        )

    assert started is True
    assert takeover_result == ["blocked"]


def test_slow_dispatch_reservation_accepts_heartbeat_renewed_expiry(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "fixture.txt").write_text("before\n", encoding="utf-8")
    (tmp_path / "test_fixture.py").write_text(
        "def test_fixture():\n    assert open('fixture.txt').read() == 'after\\n'\n",
        encoding="utf-8",
    )
    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    app.provider = DeterministicProvider(
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:fixture",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps(
                    {"path": "fixture.txt", "content": "after\n"}
                ),
            ),
        ),
    )
    app.provider_configured = True
    task = app.create_task(
        {
            "goal_id": "goal:slow-dispatch",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": NOW,
            "statement": "patch fixture",
        }
    )
    app.commit_task(
        task.task_id,
        {
            "commitment": {
                "commitment_id": "commitment:slow-dispatch",
                "task_id": task.task_id,
                "goal_id": "goal:slow-dispatch",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "accepted_by": "user:local",
                "accepted_at": NOW,
                "deliverables": ["fixture patch"],
                "acceptance_criteria": ["pytest passes"],
                "authority_scopes": ["workspace:read", "workspace:write"],
                "budget": {
                    "max_cost_usd": "1",
                    "max_duration_seconds": 300,
                    "max_provider_tokens": 1000,
                    "max_tool_calls": 10,
                },
                "risk_tier": 1,
                "exit_conditions": ["verified"],
                "expires_at": NOW + timedelta(hours=1),
            },
            "workflow": _workflow().model_dump(mode="json"),
            "expected_outcome": {
                "expected_outcome_id": "expected:slow-dispatch",
                "task_id": task.task_id,
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "evaluator_type": "pytest",
                "evaluator_version": "1",
                "evidence_requirements": ["test-report"],
                "failure_semantics": ["non-zero exit"],
                "threshold": 1,
                "observation_window_seconds": 3600,
                "frozen_at": NOW,
            },
        },
    )
    waiting = app.run_task(
        task.task_id, {"target_path": "fixture.txt", "test_command": "python -m pytest"}
    )
    assert waiting.run is not None
    assert waiting.run.status is RunStatus.WAITING_APPROVAL
    app.record_approval(
        task.task_id,
        {"disposition": "APPROVE", "reason": "Reviewed provider patch"},
    )

    monkeypatch.setattr(RunCoordinator, "_LEASE_TTL", timedelta(milliseconds=200))
    original_put = app.store.put_idempotency_guarded_by_lease
    slept = False

    def slow_put(*args, **kwargs):
        nonlocal slept
        if not slept:
            slept = True
            time.sleep(0.35)
        return original_put(*args, **kwargs)

    monkeypatch.setattr(app.store, "put_idempotency_guarded_by_lease", slow_put)
    result = app.run_task(
        task.task_id, {"target_path": "fixture.txt", "test_command": "python -m pytest"}
    )

    assert slept is True
    assert result.run is not None
    assert result.run.status is RunStatus.SUCCEEDED


def test_effect_before_receipt_lost_lease_is_unknown_without_compensation(
    tmp_path,
) -> None:
    (tmp_path / "fixture.txt").write_text("before\n", encoding="utf-8")
    (tmp_path / "test_fixture.py").write_text(
        "def test_fixture():\n    assert open('fixture.txt').read() == 'after\\n'\n",
        encoding="utf-8",
    )
    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    app.provider = DeterministicProvider(
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:fixture",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps(
                    {"path": "fixture.txt", "content": "after\n"}
                ),
            ),
        ),
    )
    app.provider_configured = True
    task = app.create_task(
        {
            "goal_id": "goal:unknown-lease",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": NOW,
            "statement": "patch fixture",
        }
    )
    app.commit_task(
        task.task_id,
        {
            "commitment": {
                "commitment_id": "commitment:unknown-lease",
                "task_id": task.task_id,
                "goal_id": "goal:unknown-lease",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "accepted_by": "user:local",
                "accepted_at": NOW,
                "deliverables": ["fixture patch"],
                "acceptance_criteria": ["pytest passes"],
                "authority_scopes": ["workspace:read", "workspace:write"],
                "budget": {
                    "max_cost_usd": "1",
                    "max_duration_seconds": 300,
                    "max_provider_tokens": 1000,
                    "max_tool_calls": 10,
                },
                "risk_tier": 1,
                "exit_conditions": ["verified"],
                "expires_at": NOW + timedelta(hours=1),
            },
            "workflow": _workflow().model_dump(mode="json"),
            "expected_outcome": {
                "expected_outcome_id": "expected:unknown-lease",
                "task_id": task.task_id,
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "evaluator_type": "pytest",
                "evaluator_version": "1",
                "evidence_requirements": ["test-report"],
                "failure_semantics": ["non-zero exit"],
                "threshold": 1,
                "observation_window_seconds": 3600,
                "frozen_at": NOW,
            },
        },
    )
    inputs = {"target_path": "fixture.txt", "test_command": "python -m pytest"}
    waiting = app.run_task(task.task_id, inputs)
    assert waiting.run is not None
    assert waiting.run.status is RunStatus.WAITING_APPROVAL
    app.record_approval(
        task.task_id,
        {"disposition": "APPROVE", "reason": "Reviewed provider patch"},
    )

    stole = False

    def steal_after_effect(phase: str) -> None:
        nonlocal stole
        if phase != "before_tool_effect_commit" or stole:
            return
        current = app.tasks.get_task(task.task_id)
        assert current.run is not None
        expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        app.store._db.execute(  # noqa: SLF001 - targeted stale-worker regression.
            "UPDATE run_leases SET expires_at = ? WHERE run_id = ?",
            (expired, current.run.run_id),
        )
        app.store._db.commit()  # noqa: SLF001
        app.store.recover_lease(
            current.run.run_id,
            "worker:takeover",
            (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        )
        stole = True

    with pytest.raises(RunExecutionError, match="lost its run lease"):
        app.run_task(task.task_id, inputs, execution_fence=steal_after_effect)

    assert stole is True
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "after\n"
    events = list(app.store.read(task.task_id))
    receipts = [
        event.decoded_payload()["receipt"]
        for event in events
        if event.event_type.value == "ACTION_RECEIPT_RECORDED"
    ]
    apply_receipts = [
        receipt
        for receipt in receipts
        if receipt["connector_id"] == "workspace.apply_patch"
    ]
    assert apply_receipts == []
    event_types = [event.event_type.value for event in events]
    assert "RUN_PAUSED" not in event_types
    assert "RUN_FAILED" not in event_types
    assert "NODE_FAILED" not in event_types
    assert "ACTION_COMPENSATED" not in event_types
    assert "COMPENSATION_STARTED" not in event_types

    current = app.tasks.get_task(task.task_id)
    assert current.run is not None
    app.store._db.execute(  # noqa: SLF001 - takeover worker is now stale.
        "UPDATE run_leases SET expires_at = ? WHERE run_id = ?",
        (
            (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            current.run.run_id,
        ),
    )
    app.store._db.commit()  # noqa: SLF001
    recovered = app.run_task(task.task_id, inputs, recover_stale_lease=True)
    assert recovered.run is not None
    assert recovered.run.status is RunStatus.SUCCEEDED
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "after\n"
    replay_receipts = [
        event.decoded_payload()["receipt"]
        for event in app.store.read(task.task_id)
        if event.event_type.value == "ACTION_RECEIPT_RECORDED"
        and event.decoded_payload()["receipt"]["connector_id"]
        == "workspace.apply_patch"
    ]
    assert [receipt["status"] for receipt in replay_receipts] == ["SUCCEEDED"]


def test_malformed_provider_output_has_zero_file_effects(tmp_path) -> None:
    target = tmp_path / "fixture.txt"
    target.write_text("before\n", encoding="utf-8")
    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    app.provider = DeterministicProvider(
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:valid-but-ambiguous",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps(
                    {"path": "fixture.txt", "content": "after\n"}
                ),
            ),
            ProviderToolProposal(
                proposal_id="proposal:unauthorized",
                capability_id="artifact.write",
                arguments_json=json.dumps({"content": "not authorized"}),
            ),
        )
    )
    app.provider_configured = True
    task = app.create_task(
        {
            "goal_id": "goal:malformed",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": NOW,
            "statement": "patch fixture",
        }
    )
    app.commit_task(
        task.task_id,
        {
            "commitment": {
                "commitment_id": "commitment:malformed",
                "task_id": task.task_id,
                "goal_id": "goal:malformed",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "accepted_by": "user:local",
                "accepted_at": NOW,
                "deliverables": ["fixture patch"],
                "acceptance_criteria": ["pytest passes"],
                "authority_scopes": ["workspace:read", "workspace:write"],
                "budget": {
                    "max_cost_usd": "1",
                    "max_duration_seconds": 300,
                    "max_provider_tokens": 1000,
                    "max_tool_calls": 10,
                },
                "risk_tier": 1,
                "exit_conditions": ["verified"],
                "expires_at": NOW + timedelta(hours=1),
            },
            "workflow": _workflow().model_dump(mode="json"),
            "expected_outcome": {
                "expected_outcome_id": "expected:malformed",
                "task_id": task.task_id,
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "evaluator_type": "pytest",
                "evaluator_version": "1",
                "evidence_requirements": ["test-report"],
                "failure_semantics": ["non-zero exit"],
                "threshold": 1,
                "observation_window_seconds": 60,
                "frozen_at": NOW,
            },
        },
    )

    with pytest.raises(RunExecutionError, match="node provider failed"):
        app.run_task(
            task.task_id,
            {"target_path": "fixture.txt", "test_command": "python -m pytest"},
        )

    assert target.read_text(encoding="utf-8") == "before\n"
    receipts = [
        event.decoded_payload()["receipt"]
        for event in app.store.read(task.task_id)
        if event.event_type.value == "ACTION_RECEIPT_RECORDED"
    ]
    assert all(
        receipt["connector_id"] != "workspace.apply_patch" for receipt in receipts
    )

    app.provider = DeterministicProvider(
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:retry",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps(
                    {"path": "fixture.txt", "content": "after\n"}
                ),
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
