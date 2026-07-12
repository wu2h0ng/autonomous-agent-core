from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from agent_os_contracts import ActionContract, ActionPermit, ResourceBudget
from agent_os_core import (
    CapabilityDenied,
    CorrectionAuthority,
    DeterministicProvider,
    RunCoordinator,
    RunExecutionError,
    SQLiteTaskEventStore,
    WorkerInterrupted,
    WorkspaceSandbox,
)
from apps.api_server.app import AgentOSApplication

from agent_os_contracts import (
    CompensationMode,
    CompensationStatus,
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


def _action(
    correction: CorrectionAuthority,
    now: datetime,
    *,
    action_id: str = "action:artifact",
    idempotency_key: str = "run:artifact",
    content: str = "must not be written",
) -> ActionContract:
    return ActionContract(
        action_id=action_id,
        task_id="task:long",
        run_id="run:long",
        node_id="artifact",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        capability_id="artifact.write",
        capability_version="1",
        arguments_json=json.dumps({"content": content}),
        risk_tier=1,
        idempotency_key=idempotency_key,
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=10,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-1",
        observed_correction_epochs=correction.snapshot(
            "task:long", "run:long", "artifact.write"
        ),
        expected_outcome_id="expected:long",
        candidate_envelope_id="envelope:long",
        created_at=now,
    )


def _permit(
    action: ActionContract,
    *,
    issued_at: datetime,
    expires_at: datetime,
) -> ActionPermit:
    return ActionPermit(
        permit_id=f"permit:{action.action_id}",
        action_id=action.action_id,
        action_digest=action.action_digest(),
        principal_id=action.principal_id,
        tenant_id=action.tenant_id,
        workspace_id=action.workspace_id,
        policy_decision_id="decision:long",
        grant_id="grant:artifact.write",
        correction_epochs=action.observed_correction_epochs,
        lease_fence=0,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def test_second_authority_observes_external_halt_without_restart(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    first = CorrectionAuthority(SQLiteTaskEventStore(database))
    second = CorrectionAuthority(SQLiteTaskEventStore(database))
    assert not second.halted("task:long", "run:long", "artifact.write")

    first.correct("task", "task:long", "external principal halt")

    assert second.halted("task:long", "run:long", "artifact.write")
    assert second.snapshot(
        "task:long", "run:long", "artifact.write"
    ).task_epoch == 1


def test_stale_authorities_advance_correction_epoch_monotonically(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    first = CorrectionAuthority(SQLiteTaskEventStore(database))
    second = CorrectionAuthority(SQLiteTaskEventStore(database))
    first.snapshot("task:long", "run:long", "artifact.write")
    second.snapshot("task:long", "run:long", "artifact.write")

    assert first.correct("task", "task:long", "first halt") == 1
    assert second.correct("task", "task:long", "second halt") == 2

    reloaded = CorrectionAuthority(SQLiteTaskEventStore(database))
    assert reloaded.snapshot(
        "task:long", "run:long", "artifact.write"
    ).task_epoch == 2


def test_connector_rejects_expired_permit_before_side_effect(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    correction = CorrectionAuthority()
    action = _action(correction, now)
    permit = _permit(
        action,
        issued_at=now - timedelta(minutes=10),
        expires_at=now - timedelta(minutes=5),
    )
    sandbox = WorkspaceSandbox(tmp_path)
    before = tuple(sandbox.artifacts.iterdir())

    with pytest.raises(CapabilityDenied, match="expired"):
        sandbox.invoke(action, permit, correction)

    assert tuple(sandbox.artifacts.iterdir()) == before


def test_forged_current_epoch_permit_cannot_bypass_halt(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    correction = CorrectionAuthority()
    correction.correct("task", "task:long", "principal halt")
    action = _action(correction, now)
    permit = _permit(
        action,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    sandbox = WorkspaceSandbox(tmp_path)

    with pytest.raises(CapabilityDenied, match="halted"):
        sandbox.invoke(action, permit, correction)

    assert not any(sandbox.artifacts.iterdir())


def test_patch_snapshot_survives_new_sandbox_instance(tmp_path: Path) -> None:
    target = tmp_path / "fixture.txt"
    target.write_text("before\n", encoding="utf-8")
    first = WorkspaceSandbox(tmp_path)

    output = first._dispatch(
        "workspace.apply_patch",
        {"path": "fixture.txt", "content": "after\n"},
        "run:apply",
    )
    assert target.read_text(encoding="utf-8") == "after\n"

    second = WorkspaceSandbox(tmp_path)
    restored = second._dispatch(
        "workspace.compensate_patch",
        {
            "path": "fixture.txt",
            "original_action_key": "run:apply",
            "compensation_ref": output["compensation_ref"],
            "manifest_sha256": output["manifest_sha256"],
        },
        "run:compensate:apply",
    )

    assert target.read_text(encoding="utf-8") == "before\n"
    assert restored["compensated"] is True


def test_compensation_refuses_to_overwrite_later_user_edit(tmp_path: Path) -> None:
    target = tmp_path / "fixture.txt"
    target.write_text("before\n", encoding="utf-8")
    sandbox = WorkspaceSandbox(tmp_path)
    output = sandbox._dispatch(
        "workspace.apply_patch",
        {"path": "fixture.txt", "content": "after\n"},
        "run:apply",
    )
    target.write_text("user edit\n", encoding="utf-8")

    with pytest.raises(CapabilityDenied, match="changed after patch"):
        WorkspaceSandbox(tmp_path)._dispatch(
            "workspace.compensate_patch",
            {
                "path": "fixture.txt",
                "original_action_key": "run:apply",
                "compensation_ref": output["compensation_ref"],
                "manifest_sha256": output["manifest_sha256"],
            },
            "run:compensate:apply",
        )

    assert target.read_text(encoding="utf-8") == "user edit\n"


def test_snapshot_write_failure_has_zero_patch_effect(tmp_path: Path) -> None:
    target = tmp_path / "fixture.txt"
    target.write_text("before\n", encoding="utf-8")
    sandbox = WorkspaceSandbox(tmp_path)

    def fail_snapshot(*args: object, **kwargs: object) -> None:
        raise OSError("injected snapshot failure")

    sandbox._persist_snapshot = fail_snapshot  # type: ignore[attr-defined,method-assign]

    with pytest.raises(OSError, match="snapshot failure"):
        sandbox._dispatch(
            "workspace.apply_patch",
            {"path": "fixture.txt", "content": "after\n"},
            "run:apply",
        )

    assert target.read_text(encoding="utf-8") == "before\n"


def test_missing_or_tampered_snapshot_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / "fixture.txt"
    target.write_text("before\n", encoding="utf-8")
    sandbox = WorkspaceSandbox(tmp_path)
    output = sandbox._dispatch(
        "workspace.apply_patch",
        {"path": "fixture.txt", "content": "after\n"},
        "run:apply",
    )
    snapshot_dir = (
        sandbox.artifacts
        / "compensation"
        / str(output["compensation_ref"]).removeprefix("compensation:")
    )
    (snapshot_dir / "manifest.json").write_text("{}", encoding="utf-8")

    with pytest.raises(CapabilityDenied, match="manifest"):
        WorkspaceSandbox(tmp_path)._dispatch(
            "workspace.compensate_patch",
            {
                "path": "fixture.txt",
                "original_action_key": "run:apply",
                "compensation_ref": output["compensation_ref"],
                "manifest_sha256": output["manifest_sha256"],
            },
            "run:compensate:apply",
        )

    assert target.read_text(encoding="utf-8") == "after\n"


def test_same_idempotency_key_with_changed_intent_is_rejected(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    store = SQLiteTaskEventStore(tmp_path / "state.sqlite3")
    correction = CorrectionAuthority(store)
    sandbox = WorkspaceSandbox(tmp_path, idempotency_store=store)
    first = _action(
        correction,
        now,
        action_id="action:first",
        idempotency_key="same-key",
        content="first",
    )
    sandbox.invoke(
        first,
        _permit(first, issued_at=now, expires_at=now + timedelta(minutes=5)),
        correction,
    )
    changed = _action(
        correction,
        now,
        action_id="action:changed",
        idempotency_key="same-key",
        content="changed",
    )

    with pytest.raises(CapabilityDenied, match="idempotency key reused"):
        sandbox.invoke(
            changed,
            _permit(
                changed,
                issued_at=now,
                expires_at=now + timedelta(minutes=5),
            ),
            correction,
        )


def _patch_failure_workflow(now: datetime) -> WorkflowGraph:
    nodes = (
        NodeSpec(
            node_id="read",
            kind=NodeKind.TOOL,
            capability="workspace.read",
            idempotency=IdempotencyMode.IDEMPOTENT,
        ),
        NodeSpec(node_id="provider", kind=NodeKind.PROVIDER, capability="provider.chat"),
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
        workflow_id="workflow:compensation-failure",
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
                ("provider", "approve"),
                ("approve", "apply"),
                ("apply", "tests"),
                ("tests", "evaluate"),
                ("evaluate", "done"),
            )
        ),
    )


def _interrupt_after_patch(root: Path) -> tuple[Path, str]:
    now = datetime.now(timezone.utc)
    database = root / "agent-os.sqlite3"
    target = root / "fixture.txt"
    target.write_text("before\n", encoding="utf-8")
    (root / "test_fixture.py").write_text(
        "def test_fixture():\n    assert open('fixture.txt').read() == 'expected\\n'\n",
        encoding="utf-8",
    )
    app = AgentOSApplication(database=database, workspace=root)
    app.provider = DeterministicProvider(
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:bad-patch",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps(
                    {"path": "fixture.txt", "content": "bad\n"}
                ),
            ),
        )
    )
    app.provider_configured = True
    task = app.create_task(
        {
            "goal_id": "goal:compensate",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": now,
            "statement": "apply then verify a deliberately failing patch",
        }
    )
    app.commit_task(
        task.task_id,
        {
            "commitment": {
                "commitment_id": "commitment:compensate",
                "task_id": task.task_id,
                "goal_id": "goal:compensate",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "accepted_by": "user:local",
                "accepted_at": now,
                "deliverables": ["verified patch"],
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
            "workflow": _patch_failure_workflow(now).model_dump(mode="json"),
            "expected_outcome": {
                "expected_outcome_id": "expected:compensate",
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
    inputs = {"target_path": "fixture.txt", "test_command": "python -m pytest"}
    waiting = app.run_task(task.task_id, inputs)
    assert waiting.run is not None
    assert waiting.run.status is RunStatus.WAITING_APPROVAL
    app.record_approval(
        task.task_id,
        {"disposition": "APPROVE", "reason": "exercise compensation path"},
    )
    with pytest.raises(WorkerInterrupted):
        app.run_task(task.task_id, inputs, stop_after_node="apply")
    assert target.read_text(encoding="utf-8") == "bad\n"
    return database, task.task_id


def test_not_met_after_worker_restart_compensates_completed_patch(
    tmp_path: Path,
) -> None:
    database, task_id = _interrupt_after_patch(tmp_path)
    restarted = AgentOSApplication(database=database, workspace=tmp_path)
    restarted.provider = DeterministicProvider()
    restarted.provider_configured = True

    result = restarted.run_task(
        task_id,
        {"target_path": "fixture.txt", "test_command": "python -m pytest"},
        recover_stale_lease=True,
    )

    assert result.status is TaskStatus.FAILED
    assert result.run is not None
    assert result.run.status is RunStatus.FAILED
    assert result.observed_outcome is not None
    assert result.observed_outcome.status.value == "NOT_MET"
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "before\n"
    records = [
        event.decoded_payload()["compensation"]
        for event in restarted.store.read(task_id)
        if event.event_type is TaskEventType.ACTION_COMPENSATED
    ]
    assert len(records) == 1
    assert records[0]["status"] == CompensationStatus.COMPENSATED.value


def test_c7_halt_requires_principal_resume_before_manual_compensation(
    tmp_path: Path,
) -> None:
    database, task_id = _interrupt_after_patch(tmp_path)
    restarted = AgentOSApplication(database=database, workspace=tmp_path)
    restarted.provider = DeterministicProvider()
    restarted.provider_configured = True
    restarted.correct_task(task_id, "principal halt before recovery")

    with pytest.raises(RunExecutionError, match="node tests failed"):
        restarted.run_task(
            task_id,
            {"target_path": "fixture.txt", "test_command": "python -m pytest"},
            recover_stale_lease=True,
        )

    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "bad\n"
    assert any(
        event.event_type is TaskEventType.COMPENSATION_BLOCKED
        for event in restarted.store.read(task_id)
    )
    restarted.resume_task(task_id)
    assert restarted.correction.halted(
        task_id,
        restarted.tasks.get_task(task_id).run.run_id,  # type: ignore[union-attr]
        "workspace.compensate_patch",
    )
    runner = RunCoordinator(
        restarted.tasks,
        restarted.sandbox,
        restarted.provider,
        restarted.provider_profile,
        restarted.policy,
        restarted.correction,
        restarted.grants,
        compensation_grant=restarted.compensation_grant,
    )
    runner.compensate_task(
        task_id,
        restarted.principal,
        mode=CompensationMode.MANUAL,
    )
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "bad\n"

    restarted.correction.resume("task", task_id, "principal correction resume")
    runner.compensate_task(
        task_id,
        restarted.principal,
        mode=CompensationMode.MANUAL,
    )

    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "before\n"
    assert sum(
        event.event_type is TaskEventType.ACTION_COMPENSATED
        for event in restarted.store.read(task_id)
    ) == 1


def test_internal_compensation_capability_is_not_ordinary_grant(tmp_path: Path) -> None:
    app = AgentOSApplication(database=tmp_path / "state.sqlite3", workspace=tmp_path)

    assert "workspace.compensate_patch" not in app.grants
    assert "workspace.compensate_patch" in app.sandbox.specs(include_internal=True)
