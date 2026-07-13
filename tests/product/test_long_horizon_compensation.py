from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from agent_os_contracts import ActionContract, ActionPermit, ResourceBudget
from agent_os_core import (
    CapabilityDenied,
    ConcurrentWriteError,
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
    CompensationStatus,
    EdgeSpec,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    ProviderToolProposal,
    PrincipalIdentity,
    PrincipalRole,
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


def test_second_authority_observes_external_halt_without_restart(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    first = CorrectionAuthority(SQLiteTaskEventStore(database))
    second = CorrectionAuthority(SQLiteTaskEventStore(database))
    assert not second.halted("task:long", "run:long", "artifact.write")

    first.correct("task", "task:long", "external principal halt")

    assert second.halted("task:long", "run:long", "artifact.write")
    assert second.snapshot("task:long", "run:long", "artifact.write").task_epoch == 1


def test_stale_authorities_advance_correction_epoch_monotonically(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    first = CorrectionAuthority(SQLiteTaskEventStore(database))
    second = CorrectionAuthority(SQLiteTaskEventStore(database))
    first.snapshot("task:long", "run:long", "artifact.write")
    second.snapshot("task:long", "run:long", "artifact.write")

    assert first.correct("task", "task:long", "first halt") == 1
    assert second.correct("task", "task:long", "second halt") == 2

    reloaded = CorrectionAuthority(SQLiteTaskEventStore(database))
    assert reloaded.snapshot("task:long", "run:long", "artifact.write").task_epoch == 2


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

    with pytest.raises(CapabilityDenied, match="already compensated"):
        WorkspaceSandbox(tmp_path)._dispatch(
            "workspace.apply_patch",
            {"path": "fixture.txt", "content": "after\n"},
            "run:apply",
        )
    assert target.read_text(encoding="utf-8") == "before\n"

    target.write_text("after\n", encoding="utf-8")
    with pytest.raises(CapabilityDenied, match="terminal"):
        WorkspaceSandbox(tmp_path)._dispatch(
            "workspace.compensate_patch",
            {
                "path": "fixture.txt",
                "original_action_key": "run:apply",
                "compensation_ref": output["compensation_ref"],
                "manifest_sha256": output["manifest_sha256"],
            },
            "run:compensate:apply:retry",
        )
    assert target.read_text(encoding="utf-8") == "after\n"


def test_applied_snapshot_with_missing_effect_does_not_resurrect_patch(
    tmp_path: Path,
) -> None:
    target = tmp_path / "fixture.txt"
    target.write_text("before\n", encoding="utf-8")
    sandbox = WorkspaceSandbox(tmp_path)
    sandbox._dispatch(
        "workspace.apply_patch",
        {"path": "fixture.txt", "content": "after\n"},
        "run:apply",
    )
    target.write_text("before\n", encoding="utf-8")

    with pytest.raises(CapabilityDenied, match="APPLIED"):
        WorkspaceSandbox(tmp_path)._dispatch(
            "workspace.apply_patch",
            {"path": "fixture.txt", "content": "after\n"},
            "run:apply",
        )

    assert target.read_text(encoding="utf-8") == "before\n"


def test_persistent_apply_replay_cannot_resurrect_compensated_patch(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    target = tmp_path / "fixture.txt"
    target.write_text("before\n", encoding="utf-8")
    store = SQLiteTaskEventStore(tmp_path / "state.sqlite3")
    correction = CorrectionAuthority(store)
    sandbox = WorkspaceSandbox(tmp_path, idempotency_store=store)
    action = ActionContract(
        action_id="action:persistent-patch",
        task_id="task:long",
        run_id="run:long",
        node_id="apply",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        capability_id="workspace.apply_patch",
        capability_version="1",
        arguments_json=json.dumps({"path": "fixture.txt", "content": "after\n"}),
        risk_tier=1,
        idempotency_key="run:persistent-apply",
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=10,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-1",
        observed_correction_epochs=correction.snapshot(
            "task:long", "run:long", "workspace.apply_patch"
        ),
        expected_outcome_id="expected:long",
        candidate_envelope_id="envelope:long",
        created_at=now,
    )
    permit = _permit(
        action,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    applied = sandbox.invoke(action, permit, correction)
    compensation_action = ActionContract(
        action_id="action:persistent-compensation",
        task_id=action.task_id,
        run_id=action.run_id,
        node_id=action.node_id,
        principal_id=action.principal_id,
        tenant_id=action.tenant_id,
        workspace_id=action.workspace_id,
        capability_id="workspace.compensate_patch",
        capability_version="1",
        arguments_json=json.dumps(
            {
                "path": "fixture.txt",
                "original_action_key": action.idempotency_key,
                "compensation_ref": applied.output["compensation_ref"],
                "manifest_sha256": applied.output["manifest_sha256"],
            }
        ),
        risk_tier=1,
        idempotency_key="run:persistent-compensation",
        estimated_budget=action.estimated_budget,
        policy_version=action.policy_version,
        observed_correction_epochs=correction.snapshot(
            action.task_id,
            action.run_id,
            "workspace.compensate_patch",
        ),
        expected_outcome_id=action.expected_outcome_id,
        candidate_envelope_id=action.candidate_envelope_id,
        created_at=now,
    )
    compensation_permit = _permit(
        compensation_action,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    sandbox.invoke(compensation_action, compensation_permit, correction)

    with pytest.raises(CapabilityDenied, match="already compensated"):
        WorkspaceSandbox(tmp_path, idempotency_store=store).invoke(
            action,
            permit,
            correction,
        )

    assert target.read_text(encoding="utf-8") == "before\n"
    target.write_text("after\n", encoding="utf-8")
    with pytest.raises(CapabilityDenied, match="cached compensation"):
        WorkspaceSandbox(tmp_path, idempotency_store=store).invoke(
            compensation_action,
            compensation_permit,
            correction,
        )
    assert target.read_text(encoding="utf-8") == "after\n"


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


def test_workspace_capability_cannot_write_reserved_artifact_state(
    tmp_path: Path,
) -> None:
    sandbox = WorkspaceSandbox(tmp_path)

    with pytest.raises(CapabilityDenied, match="reserved"):
        sandbox._dispatch(
            "workspace.apply_patch",
            {
                "path": ".agent-os-artifacts/compensation/forged/state.json",
                "content": '{"state":"COMPENSATED"}',
            },
            "run:forged",
        )


def _patch_failure_workflow(now: datetime) -> WorkflowGraph:
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
                arguments_json=json.dumps({"path": "fixture.txt", "content": "bad\n"}),
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


def test_compensation_infrastructure_error_does_not_mask_not_met(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, task_id = _interrupt_after_patch(tmp_path)

    def fail_compensation(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected compensation infrastructure failure")

    monkeypatch.setattr(
        RunCoordinator,
        "_auto_compensate_task",
        fail_compensation,
    )
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
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "bad\n"


def test_manual_compensation_rejects_active_run_without_failure_context(
    tmp_path: Path,
) -> None:
    database, task_id = _interrupt_after_patch(tmp_path)
    restarted = AgentOSApplication(database=database, workspace=tmp_path)
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

    with pytest.raises(RunExecutionError, match="FAILED/NOT_MET"):
        runner.compensate_task(
            task_id,
            restarted.principal,
        )

    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "bad\n"


def test_worker_role_cannot_request_manual_compensation(tmp_path: Path) -> None:
    database, task_id = _interrupt_after_patch(tmp_path)
    restarted = AgentOSApplication(database=database, workspace=tmp_path)
    restarted.tasks.update_run_status(
        task_id,
        RunStatus.FAILED,
        event_type=TaskEventType.RUN_FAILED,
    )
    worker = PrincipalIdentity(
        principal_id=restarted.principal.principal_id,
        tenant_id=restarted.principal.tenant_id,
        workspace_id=restarted.principal.workspace_id,
        role=PrincipalRole.WORKER,
        authenticated_at=datetime.now(timezone.utc),
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

    with pytest.raises(PermissionError, match="principal"):
        runner.compensate_task(
            task_id,
            worker,
        )

    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "bad\n"


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
    current = restarted.tasks.get_task(task_id)
    assert current.run is not None
    active_owner = "worker:still-active"
    restarted.store.acquire_lease(
        current.run.run_id,
        active_owner,
        (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    )
    with pytest.raises(ConcurrentWriteError, match="leased"):
        runner.compensate_task(
            task_id,
            restarted.principal,
        )
    restarted.store.release_lease(current.run.run_id, active_owner)
    runner.compensate_task(
        task_id,
        restarted.principal,
    )
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "bad\n"

    worker = PrincipalIdentity(
        principal_id="worker:cannot-resume-c7",
        tenant_id=restarted.principal.tenant_id,
        workspace_id=restarted.principal.workspace_id,
        role=PrincipalRole.WORKER,
        authenticated_at=datetime.now(timezone.utc),
    )
    with pytest.raises(PermissionError, match="principal authority"):
        restarted.resume_correction(
            task_id,
            "worker must not resume correction",
            principal=worker,
        )
    assert restarted.correction.halted(
        task_id,
        current.run.run_id,
        "workspace.compensate_patch",
    )
    restarted.resume_correction(task_id, "principal correction resume")
    runner.compensate_task(
        task_id,
        restarted.principal,
    )

    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "before\n"
    assert (
        sum(
            event.event_type is TaskEventType.ACTION_COMPENSATED
            for event in restarted.store.read(task_id)
        )
        == 1
    )


def test_original_patch_capability_halt_blocks_automatic_compensation(
    tmp_path: Path,
) -> None:
    database, task_id = _interrupt_after_patch(tmp_path)
    restarted = AgentOSApplication(database=database, workspace=tmp_path)
    restarted.provider = DeterministicProvider()
    restarted.provider_configured = True
    restarted.correction.correct(
        "capability",
        "workspace.apply_patch",
        "halt patch capability",
    )

    result = restarted.run_task(
        task_id,
        {"target_path": "fixture.txt", "test_command": "python -m pytest"},
        recover_stale_lease=True,
    )

    assert result.status is TaskStatus.FAILED
    assert result.observed_outcome is not None
    assert result.observed_outcome.status.value == "NOT_MET"
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "bad\n"
    assert any(
        event.event_type is TaskEventType.COMPENSATION_BLOCKED
        for event in restarted.store.read(task_id)
    )


def test_internal_compensation_capability_is_not_ordinary_grant(tmp_path: Path) -> None:
    app = AgentOSApplication(database=tmp_path / "state.sqlite3", workspace=tmp_path)

    assert "workspace.compensate_patch" not in app.grants
    assert "workspace.compensate_patch" in app.sandbox.specs(include_internal=True)


def test_missing_later_patch_binding_stops_reverse_compensation(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    first_target = tmp_path / "first.txt"
    second_target = tmp_path / "second.txt"
    first_target.write_text("first-before\n", encoding="utf-8")
    second_target.write_text("second-before\n", encoding="utf-8")
    app = AgentOSApplication(database=tmp_path / "state.sqlite3", workspace=tmp_path)
    workflow = WorkflowGraph(
        workflow_id="workflow:two-patches",
        version=1,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=now,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=(
            NodeSpec(
                node_id="apply-first",
                kind=NodeKind.TOOL,
                capability="workspace.apply_patch",
                idempotency=IdempotencyMode.COMPENSATABLE,
            ),
            NodeSpec(
                node_id="apply-second",
                kind=NodeKind.TOOL,
                capability="workspace.apply_patch",
                idempotency=IdempotencyMode.COMPENSATABLE,
            ),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(
            EdgeSpec(source="apply-first", target="apply-second"),
            EdgeSpec(source="apply-second", target="done"),
        ),
    )
    task = app.create_task(
        {
            "goal_id": "goal:two-patches",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": now,
            "statement": "exercise reverse compensation stop",
        }
    )
    app.commit_task(
        task.task_id,
        {
            "commitment": {
                "commitment_id": "commitment:two-patches",
                "task_id": task.task_id,
                "goal_id": "goal:two-patches",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "accepted_by": "user:local",
                "accepted_at": now,
                "deliverables": ["two patches"],
                "acceptance_criteria": ["manual verification"],
                "authority_scopes": ["workspace:write"],
                "budget": {
                    "max_cost_usd": "1",
                    "max_duration_seconds": 300,
                    "max_provider_tokens": 0,
                    "max_tool_calls": 10,
                },
                "risk_tier": 1,
                "exit_conditions": ["verified"],
                "expires_at": now + timedelta(hours=1),
            },
            "workflow": workflow.model_dump(mode="json"),
            "expected_outcome": {
                "expected_outcome_id": "expected:two-patches",
                "task_id": task.task_id,
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "evaluator_type": "pytest",
                "evaluator_version": "1",
                "evidence_requirements": ["manual"],
                "failure_semantics": ["not verified"],
                "threshold": 1,
                "observation_window_seconds": 60,
                "frozen_at": now,
            },
        },
    )
    started = app.start_run(task.task_id)
    assert started.run is not None
    run_id = started.run.run_id
    app.tasks.update_run_status(
        task.task_id,
        RunStatus.RUNNING,
        event_type=TaskEventType.RUN_QUEUED,
    )

    def patch_action(node_id: str, path: str) -> ActionContract:
        return ActionContract(
            action_id=f"action:{node_id}",
            task_id=task.task_id,
            run_id=run_id,
            node_id=node_id,
            principal_id=app.principal.principal_id,
            tenant_id=app.principal.tenant_id,
            workspace_id=app.principal.workspace_id,
            capability_id="workspace.apply_patch",
            capability_version="1",
            arguments_json=json.dumps({"path": path, "content": "after\n"}),
            risk_tier=1,
            idempotency_key=f"{run_id}:{node_id}",
            estimated_budget=ResourceBudget(
                max_cost_usd=Decimal("0"),
                max_duration_seconds=10,
                max_provider_tokens=0,
                max_tool_calls=1,
            ),
            policy_version="policy-1",
            observed_correction_epochs=app.correction.snapshot(
                task.task_id,
                run_id,
                "workspace.apply_patch",
            ),
            expected_outcome_id="expected:two-patches",
            candidate_envelope_id="envelope:two-patches",
            created_at=now,
        )

    first_action = patch_action("apply-first", "first.txt")
    second_action = patch_action("apply-second", "second.txt")
    first_output = app.sandbox._dispatch(
        "workspace.apply_patch",
        {"path": "first.txt", "content": "after\n"},
        first_action.idempotency_key,
    )
    for action in (first_action, second_action):
        app.tasks.append_event(
            task.task_id,
            TaskEventType.ACTION_PROPOSED,
            {"action": action.model_dump(mode="json")},
        )
        app.tasks.append_event(
            task.task_id,
            TaskEventType.NODE_COMPLETED,
            (
                {"node_id": action.node_id, "output": first_output}
                if action is first_action
                else {"node_id": action.node_id}
            ),
        )
    app.tasks.update_run_status(
        task.task_id,
        RunStatus.FAILED,
        event_type=TaskEventType.RUN_FAILED,
    )
    runner = RunCoordinator(
        app.tasks,
        app.sandbox,
        app.provider,
        app.provider_profile,
        app.policy,
        app.correction,
        app.grants,
        compensation_grant=app.compensation_grant,
    )

    result = runner.compensate_task(task.task_id, app.principal)

    assert first_target.read_text(encoding="utf-8") == "after\n"
    assert second_target.read_text(encoding="utf-8") == "second-before\n"
    assert result.compensations[-1].status is CompensationStatus.FAILED
    assert result.compensations[-1].node_id == "apply-second"
    assert not any(
        record.status is CompensationStatus.COMPENSATED
        for record in result.compensations
    )
