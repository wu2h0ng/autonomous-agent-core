from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

import pytest
from agent_os_contracts import ProviderMessageRole, ProviderToolProposal, TaskEventType
from agent_os_core import (
    AgentLoop,
    AgentLoopConfig,
    AutoApproveGateway,
    DeterministicProvider,
    NonInteractiveDenyGateway,
    ensure_local_mandate_session,
    load_terminal_session,
    run_agent_cli,
)
from agent_os_core.agent_cli import AgentCLIError, event_types
from agent_os_core.capability import CapabilityDenied, WorkspaceSandbox
from agent_os_core.mandate_terminal import mandate_status
from agent_os_core.responsibility_loop import ResponsibilityLoopStaleFence

from apps.api_server.app import AgentOSApplication
from apps.cli.__main__ import main as cli_main


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
        sandbox=app.sandbox,
        grants=dict(app.grants),
        principal=app.principal,
        gateway=AutoApproveGateway(),
        config=AgentLoopConfig(stream=False),
        execution_fence=assert_current,
    )

    with pytest.raises(ResponsibilityLoopStaleFence, match="Process B"):
        loop.run_turn(session, "change the fixture")
    assert "before_provider" in phases
    assert "before_provider_commit" in phases
    assert "before_tool_effect" in phases
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"


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
