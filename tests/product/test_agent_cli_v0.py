from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

import pytest
from agent_os_contracts import (
    ApprovalDecision,
    ApprovalDisposition,
    PrincipalRole,
    ProviderMessageRole,
    ProviderToolProposal,
    RunStatus,
    TaskEventType,
)
from agent_os_core import (
    AgentLoop,
    AgentLoopConfig,
    AutoApproveGateway,
    DeferredApprovalGateway,
    DeterministicProvider,
    ExecutionLease,
    NonInteractiveDenyGateway,
    ensure_local_mandate_session,
    load_terminal_session,
    run_agent_cli,
)
from agent_os_core.agent_cli import AgentCLIError, event_types
from agent_os_core.capability import CapabilityDenied
from agent_os_core.errors import InvalidTransitionError
from agent_os_core.mandate_terminal import mandate_status
from agent_os_core.responsibility_loop import ResponsibilityLoopStaleFence

from apps.api_server.app import AgentOSApplication
from apps.cli.__main__ import main as cli_main
from domain_packs.developer_agent import WorkspaceSandbox


def _proposal(call_id: str, capability_id: str, arguments: dict) -> ProviderToolProposal:
    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id=capability_id,
        arguments_json=json.dumps(arguments),
    )


def _prepare_workspace(root: Path) -> None:
    (root / "fixture.txt").write_text("stable\n", encoding="utf-8")
    (root / "test_fixture.py").write_text(
        "def test_fixture():\n    assert open('fixture.txt').read() == 'stable\\n'\n",
        encoding="utf-8",
    )


def _proposed_actions_for_task(app: AgentOSApplication, task_id: str):
    from agent_os_contracts import ActionContract

    return [
        ActionContract.model_validate(event.decoded_payload()["action"])
        for event in app.tasks._event_store.read(task_id)
        if event.event_type is TaskEventType.ACTION_PROPOSED
    ]


def _held_claim(app: AgentOSApplication) -> ExecutionLease:
    expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
    fence = app.store.acquire_lease(
        "run:test-claim", "test:worker", expiry.isoformat()
    )
    return ExecutionLease(
        run_id="run:test-claim",
        owner="test:worker",
        fence=fence,
        expires_at=expiry,
    )


def _record_sink(app):
    def sink(session, message_index, message, turn_id):
        app.tasks.record_session_message(
            session.task_id,
            session.ref.session_id,
            message_index,
            message,
            turn_id=turn_id,
        )

    return sink


def _session_loop(
    app,
    session,
    *,
    custody=None,
    execution_fence=None,
    gateway=None,
) -> AgentLoop:
    projected = app.tasks.project_session(session.task_id, session.session_id)
    resumable_turn_ids = (
        (projected.resumable_turn_id,)
        if projected.resumable_turn_id is not None
        else ()
    )
    return AgentLoop(
        tasks=app.tasks,
        provider=app.provider,
        provider_profile=app.provider_profile,
        policy=app.policy,
        correction=app.correction,
        connector=app.sandbox,
        grants=dict(app.grants),
        principal=app.principal,
        gateway=gateway or DeferredApprovalGateway(),
        session=session,
        config=AgentLoopConfig(stream=False),
        initial_history=projected.history,
        message_sink=_record_sink(app),
        resumable_turn_ids=resumable_turn_ids,
        execution_fence=execution_fence or (lambda _phase: None),
        effect_custody=custody,
        independent_approval=True,
        external_exact_approval=True,
    )


def _agent_app(root: Path, scripted=()) -> AgentOSApplication:
    _prepare_workspace(root)
    app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
    app.provider = DeterministicProvider(
        scripted=scripted,
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def test_zero_config_mandate_and_agent_turn(tmp_path: Path) -> None:
    app = _agent_app(
        tmp_path,
        scripted=(
            ("", (_proposal("call-1", "workspace.read", {"path": "fixture.txt"}),)),
            ("read complete", ()),
        ),
    )
    result = run_agent_cli(
        app=app,
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        goal="inspect fixture",
        gateway=AutoApproveGateway(),
        prompt="read the fixture",
        offline=True,
    )
    assert result.exit_code == 0
    assert result.last_text == "read complete"
    mandate_attach = tmp_path / ".agent_os" / "mandate_attach.json"
    assert mandate_attach.is_file()
    saved = load_terminal_session(tmp_path)
    assert saved.mandate_id == "mandate:local-terminal"
    assert saved.goal == "inspect fixture"


def test_session_save_and_resume_restores_history(tmp_path: Path) -> None:
    app = _agent_app(
        tmp_path,
        scripted=(
            ("first answer", ()),
            ("second answer", ()),
        ),
    )
    first = run_agent_cli(
        app=app,
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        goal="resume me",
        gateway=AutoApproveGateway(),
        prompt="hello once",
        offline=True,
    )
    assert first.exit_code == 0
    record = load_terminal_session(tmp_path)
    roles = [message["role"] for message in record.messages]
    assert "USER" in roles
    assert "ASSISTANT" in roles

    app2 = _agent_app(
        tmp_path,
        scripted=(("continuing", ()),),
    )
    resumed = run_agent_cli(
        app=app2,
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        goal="resume me",
        gateway=AutoApproveGateway(),
        prompt="hello again",
        resume=True,
        offline=True,
    )
    assert resumed.exit_code == 0
    assert resumed.last_text == "continuing"
    provider = app2.provider
    assert isinstance(provider, DeterministicProvider)
    assert len(provider.requests) == 1
    resumed_roles = [message.role.value for message in provider.requests[0].messages]
    assert "USER" in resumed_roles
    assert "ASSISTANT" in resumed_roles


def test_write_action_requires_confirmation_gateway(tmp_path: Path) -> None:
    app = _agent_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.edit",
                        {
                            "path": "fixture.txt",
                            "old_string": "stable",
                            "new_string": "mutated",
                        },
                    ),
                ),
            ),
            ("edit blocked", ()),
        ),
    )
    result = run_agent_cli(
        app=app,
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        goal="edit fixture",
        gateway=NonInteractiveDenyGateway(),
        prompt="change the fixture",
        offline=True,
    )
    assert result.exit_code == 0
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
    provider = app.provider
    assert isinstance(provider, DeterministicProvider)
    assert len(provider.requests) == 2
    tool_message = next(
        message
        for message in provider.requests[1].messages
        if message.role is ProviderMessageRole.TOOL
    )
    assert "user rejected" in tool_message.content


def test_policy_kernel_events_after_tool_turn(tmp_path: Path) -> None:
    app = _agent_app(
        tmp_path,
        scripted=(
            ("", (_proposal("call-1", "workspace.read", {"path": "fixture.txt"}),)),
            ("done", ()),
        ),
    )
    run_agent_cli(
        app=app,
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        goal="governed read",
        gateway=AutoApproveGateway(),
        prompt="read fixture",
        offline=True,
    )
    saved = load_terminal_session(tmp_path)
    events = event_types(app, saved.task_id)
    assert TaskEventType.ACTION_PROPOSED in events
    assert TaskEventType.POLICY_DECIDED in events


def test_stale_responsibility_fence_stops_before_next_tool_effect(
    tmp_path: Path,
) -> None:
    app = _agent_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.edit",
                        {
                            "path": "fixture.txt",
                            "old_string": "stable",
                            "new_string": "mutated",
                        },
                    ),
                ),
            ),
        ),
    )
    session, _ = app.open_chat_session("fenced edit", AutoApproveGateway())
    phases: list[str] = []

    def assert_current(phase: str) -> None:
        phases.append(phase)
        if phase == "before_tool_effect":
            raise ResponsibilityLoopStaleFence("Process B owns the loop")

    loop = AgentLoop(
        tasks=app.tasks,
        provider=app.provider,
        provider_profile=app.provider_profile,
        policy=app.policy,
        correction=app.correction,
        connector=app.sandbox,
        grants=dict(app.grants),
        principal=app.principal,
        gateway=AutoApproveGateway(),
        session=session,
        config=AgentLoopConfig(stream=False),
        message_sink=_record_sink(app),
        execution_fence=assert_current,
    )

    with pytest.raises(ResponsibilityLoopStaleFence, match="Process B"):
        loop.run_turn(session, "change the fixture")
    assert "before_provider" in phases
    assert "before_provider_commit" in phases
    assert "before_tool_effect" in phases
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"


def test_agent_loop_routes_tool_effect_through_responsibility_custody(
    tmp_path: Path,
) -> None:
    app = _agent_app(
        tmp_path,
        scripted=(("", (_proposal("call-1", "workspace.read", {"path": "fixture.txt"}),)),),
    )
    session, _ = app.open_chat_session("custodied read", AutoApproveGateway())
    custody_calls: list[tuple[str, str]] = []

    def custody(operation_slot, intent_digest, effect):
        custody_calls.append((operation_slot, intent_digest))
        return effect()

    loop = AgentLoop(
        tasks=app.tasks,
        provider=app.provider,
        provider_profile=app.provider_profile,
        policy=app.policy,
        correction=app.correction,
        connector=app.sandbox,
        grants=dict(app.grants),
        principal=app.principal,
        gateway=AutoApproveGateway(),
        session=session,
        config=AgentLoopConfig(stream=False),
        message_sink=_record_sink(app),
        effect_custody=custody,
    )

    loop.run_turn(session, "read the fixture")

    assert len(custody_calls) == 1
    assert custody_calls[0][0].endswith("action-0")
    assert len(custody_calls[0][1]) == 64
    assert TaskEventType.ACTION_RECEIPT_RECORDED in event_types(app, session.task_id)


def test_agent_loop_fences_after_custodied_effect_before_task_receipt(
    tmp_path: Path,
) -> None:
    app = _agent_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.edit",
                        {
                            "path": "fixture.txt",
                            "old_string": "stable",
                            "new_string": "mutated",
                        },
                    ),
                ),
            ),
        ),
    )
    session, _ = app.open_chat_session("custodied edit", AutoApproveGateway())
    phases: list[str] = []
    custody_calls: list[str] = []

    def custody(operation_slot, _intent_digest, effect):
        custody_calls.append(operation_slot)
        return effect()

    def assert_current(phase: str) -> None:
        phases.append(phase)
        if phase == "before_tool_effect_commit":
            raise ResponsibilityLoopStaleFence("Process B owns the loop")

    loop = AgentLoop(
        tasks=app.tasks,
        provider=app.provider,
        provider_profile=app.provider_profile,
        policy=app.policy,
        correction=app.correction,
        connector=app.sandbox,
        grants=dict(app.grants),
        principal=app.principal,
        gateway=AutoApproveGateway(),
        session=session,
        config=AgentLoopConfig(stream=False),
        message_sink=_record_sink(app),
        execution_fence=assert_current,
        effect_custody=custody,
    )

    with pytest.raises(ResponsibilityLoopStaleFence, match="Process B"):
        loop.run_turn(session, "change the fixture")

    assert custody_calls
    assert "before_tool_effect_commit" in phases
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "mutated\n"
    assert TaskEventType.ACTION_RECEIPT_RECORDED not in event_types(
        app, session.task_id
    )


def test_existing_task_agent_loop_waits_for_external_exact_write_approval(
    tmp_path: Path,
) -> None:
    app = _agent_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.edit",
                        {
                            "path": "fixture.txt",
                            "old_string": "stable",
                            "new_string": "mutated",
                        },
                    ),
                ),
            ),
            ("edit complete", ()),
        ),
    )
    session, _ = app.open_chat_session("same task edit", AutoApproveGateway())
    task_count = len(app.list_tasks())
    def custody(_operation_slot, _intent_digest, effect):
        return effect()

    loop = _session_loop(app, session, custody=custody)

    waiting = loop.run_turn(session, "make the exact edit")

    assert waiting.stop_reason == "approval_required"
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
    aggregate = app.tasks.get_task(session.task_id)
    assert aggregate.run is not None
    assert aggregate.run.status is RunStatus.WAITING_APPROVAL
    pending = [
        action
        for action in _proposed_actions_for_task(app, session.task_id)
        if action.capability_id == "workspace.edit"
    ]
    assert len(pending) == 1
    with pytest.raises(ValueError, match="already has an open durable turn"):
        loop.run_turn(session, "silently substitute a second action")
    assert _proposed_actions_for_task(app, session.task_id) == pending
    with pytest.raises(InvalidTransitionError, match="external exact approval"):
        loop._actions.execute(
            pending[0],
            app.principal,
            capability_spec=app.sandbox.specs()["workspace.edit"],
            approval=None,
            record_artifacts=False,
            execution_fence=lambda _phase: None,
            effect_custody=custody,
            execution_claim=_held_claim(app),
        )
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
    now = datetime.now(timezone.utc)
    app.tasks.record_approval(
        session.task_id,
        ApprovalDecision(
            approval_id="approval:external:selfdev",
            tenant_id=app.principal.tenant_id,
            workspace_id=app.principal.workspace_id,
            action_digest=pending[0].action_digest(),
            actor_id="admin:external:selfdev",
            actor_role=PrincipalRole.TENANT_ADMIN,
            disposition=ApprovalDisposition.APPROVE,
            reason="external exact action approval",
            decided_at=now,
            expires_at=now + timedelta(minutes=5),
        ),
    )

    approval = app.tasks.get_task(session.task_id).approval
    assert approval is not None
    completed = loop.resume_pending_approval(session, approval)

    assert completed.stop_reason == "completed"
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "mutated\n"
    assert len(app.list_tasks()) == task_count
    assert _proposed_actions_for_task(app, session.task_id) == pending


def test_existing_task_agent_loop_restarts_and_requires_each_file_approval(
    tmp_path: Path,
) -> None:
    app = _agent_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.edit",
                        {
                            "path": "fixture.txt",
                            "old_string": "stable",
                            "new_string": "first",
                        },
                    ),
                ),
            ),
            (
                "",
                (
                    _proposal(
                        "call-2",
                        "workspace.edit",
                        {
                            "path": "second.txt",
                            "old_string": "before",
                            "new_string": "second",
                        },
                    ),
                ),
            ),
            ("both complete", ()),
        ),
    )
    (tmp_path / "second.txt").write_text("before\n", encoding="utf-8")
    session, _ = app.open_chat_session("same task two-file edit", AutoApproveGateway())

    def new_loop() -> AgentLoop:
        def custody(_operation_slot, _intent_digest, effect):
            return effect()

        return _session_loop(app, session, custody=custody)

    def approve_latest() -> None:
        action = _proposed_actions_for_task(app, session.task_id)[-1]
        now = datetime.now(timezone.utc)
        app.tasks.record_approval(
            session.task_id,
            ApprovalDecision(
                approval_id=f"approval:external:{action.action_id}",
                tenant_id=app.principal.tenant_id,
                workspace_id=app.principal.workspace_id,
                action_digest=action.action_digest(),
                actor_id="admin:external:selfdev",
                actor_role=PrincipalRole.TENANT_ADMIN,
                disposition=ApprovalDisposition.APPROVE,
                reason="external exact action approval",
                decided_at=now,
                expires_at=now + timedelta(minutes=5),
            ),
        )

    first_wait = new_loop().run_turn(session, "edit both files precisely")
    assert first_wait.stop_reason == "approval_required"
    approve_latest()

    approval = app.tasks.get_task(session.task_id).approval
    assert approval is not None
    second_wait = new_loop().resume_pending_approval(session, approval)
    assert second_wait.stop_reason == "approval_required"
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "first\n"
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == "before\n"
    assert app.tasks.get_task(session.task_id).approval is None
    approve_latest()

    approval = app.tasks.get_task(session.task_id).approval
    assert approval is not None
    completed = new_loop().resume_pending_approval(session, approval)
    assert completed.stop_reason == "completed"
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == "second\n"
    history = new_loop()
    roles = [message.role for message in history.history]
    assert roles.count(ProviderMessageRole.ASSISTANT) == 3
    assert roles.count(ProviderMessageRole.TOOL) == 2


def test_durable_agent_loop_recovers_crash_after_effect_receipt_before_tool_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _agent_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.edit",
                        {
                            "path": "fixture.txt",
                            "old_string": "stable",
                            "new_string": "recovered",
                        },
                    ),
                ),
            ),
            ("recovered after durable receipt", ()),
        ),
    )
    session, _ = app.open_chat_session("recover exact edit", AutoApproveGateway())

    def custody(_operation_slot, _intent_digest, effect):
        return effect()

    def new_loop() -> AgentLoop:
        return _session_loop(app, session, custody=custody)

    first = new_loop()
    assert first.run_turn(session, "edit once").stop_reason == "approval_required"
    action = app.tasks.pending_action(session.task_id)
    assert action is not None
    now = datetime.now(timezone.utc)
    app.tasks.record_approval(
        session.task_id,
        ApprovalDecision(
            approval_id="approval:crash-window",
            tenant_id=app.principal.tenant_id,
            workspace_id=app.principal.workspace_id,
            action_digest=action.action_digest(),
            actor_id="admin:external:crash-window",
            actor_role=PrincipalRole.TENANT_ADMIN,
            disposition=ApprovalDisposition.APPROVE,
            reason="exact action approved",
            decided_at=now,
            expires_at=now + timedelta(minutes=5),
        ),
    )

    def crash_after_receipt(*_args, **_kwargs):
        raise RuntimeError("simulated crash after Task action receipt")

    original_resolve = app.tasks.resolve_session_approval
    monkeypatch.setattr(app.tasks, "resolve_session_approval", crash_after_receipt)
    with pytest.raises(RuntimeError, match="simulated crash"):
        approval = app.tasks.get_task(session.task_id).approval
        assert approval is not None
        first.resume_pending_approval(session, approval)
    monkeypatch.setattr(app.tasks, "resolve_session_approval", original_resolve)
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "recovered\n"

    approval = app.tasks.get_task(session.task_id).approval
    assert approval is not None
    completed = new_loop().resume_pending_approval(session, approval)

    assert completed.stop_reason == "completed"
    receipts = [
        event
        for event in app.tasks._event_store.read(session.task_id)
        if event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED
        and event.decoded_payload().get("decision", {}).get("action_id")
        == action.action_id
    ]
    assert len(receipts) == 1


def test_resume_rejects_mandate_or_workspace_mismatch(tmp_path: Path) -> None:
    app = _agent_app(tmp_path, scripted=(("first", ()),))
    run_agent_cli(
        app=app,
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        goal="bind me",
        gateway=AutoApproveGateway(),
        prompt="hello",
        offline=True,
    )
    session_path = tmp_path / ".agent_os" / "terminal_session.json"
    raw = json.loads(session_path.read_text(encoding="utf-8"))
    raw["mandate_id"] = "mandate:forged"
    session_path.write_text(json.dumps(raw), encoding="utf-8")
    app2 = _agent_app(tmp_path, scripted=(("nope", ()),))
    with pytest.raises(AgentCLIError, match="mandate_id"):
        run_agent_cli(
            app=app2,
            workspace=tmp_path,
            database=tmp_path / "agent-os.sqlite3",
            goal="bind me",
            gateway=AutoApproveGateway(),
            prompt="hello again",
            resume=True,
            offline=True,
        )


def test_workspace_tools_cannot_touch_agent_os_state(tmp_path: Path) -> None:
    sandbox = WorkspaceSandbox(tmp_path)
    (tmp_path / ".agent_os").mkdir()
    (tmp_path / ".agent_os" / "terminal_session.json").write_text("{}", encoding="utf-8")
    with pytest.raises(CapabilityDenied, match="reserved"):
        sandbox._safe_path(".agent_os/terminal_session.json")


def test_ensure_local_mandate_session_clock_fix(tmp_path: Path) -> None:
    frozen = datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc)
    session, created = ensure_local_mandate_session(
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        evaluated_at=frozen,
    )
    assert created is True
    status = mandate_status(
        workspace=tmp_path,
        evaluated_at=frozen + timedelta(minutes=5),
        session=session,
    )
    assert status["mandate_id"] == "mandate:local-terminal"
    assert status["status"] == "ACTIVE"


def test_agent_repl_status_command(tmp_path: Path) -> None:
    app = _agent_app(tmp_path, scripted=(("ok", ()),))
    stdin = StringIO("/status\n/exit\n")
    stdout = StringIO()
    run_agent_cli(
        app=app,
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        goal="status check",
        gateway=AutoApproveGateway(),
        offline=True,
        input_stream=stdin,
        output_stream=stdout,
    )
    assert "mandate:local-terminal" in stdout.getvalue()
    assert "agent_session" in stdout.getvalue()


def test_default_help_exposes_one_agent_work_surface_without_internal_organs(
    capsys,
) -> None:
    with pytest.raises(SystemExit) as exited:
        cli_main(["agent-os", "--help"])
    assert exited.value.code == 0
    output = capsys.readouterr().out
    assert "run/status/answer/correct/resume" in output
    assert "selfdev" not in output
    assert "responsibility-controller" not in output
    assert "agent-run" not in output
