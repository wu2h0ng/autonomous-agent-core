from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from agent_os_contracts import ProviderMessageRole, ProviderToolProposal
from agent_os_core import (
    AutoApproveGateway,
    DeterministicProvider,
    discover_agents_markdown,
    run_agent_cli,
)
from agent_os_core.capability import CapabilityDenied, WorkspaceSandbox
from agent_os_core.trusted_commands import TRUSTED_SHELL_PROFILE_V1

from apps.api_server.app import AgentOSApplication


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


class _ApproveAllGateway:
    def confirm(self, action, preview) -> bool:
        return True


def _system_message(app: AgentOSApplication) -> str:
    provider = app.provider
    assert isinstance(provider, DeterministicProvider)
    system = next(
        message
        for message in provider.requests[0].messages
        if message.role is ProviderMessageRole.SYSTEM
    )
    return system.content


def test_agents_md_injected_into_system_prompt(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("Always use ruff before commit.\n", encoding="utf-8")
    app = _agent_app(tmp_path, scripted=(("ok", ()),))
    result = run_agent_cli(
        app=app,
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        goal="follow project rules",
        gateway=AutoApproveGateway(),
        prompt="hello",
        offline=True,
    )
    assert result.exit_code == 0
    system = _system_message(app)
    assert "# Project AGENTS.md (sha256=" in system
    assert "Always use ruff before commit." in system


def test_symlink_agents_md_rejected_fail_closed(tmp_path: Path) -> None:
    real = tmp_path / "real_agents.md"
    real.write_text("outside symlink rules\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").symlink_to(real)
    assert discover_agents_markdown(tmp_path) is None

    app = _agent_app(tmp_path, scripted=(("ok", ()),))
    run_agent_cli(
        app=app,
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        goal="ignore symlink",
        gateway=AutoApproveGateway(),
        prompt="hello",
        offline=True,
    )
    system = _system_message(app)
    assert "outside symlink rules" not in system
    assert "# Project AGENTS.md" not in system


def test_status_includes_agent_context_digest(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("project guidance\n", encoding="utf-8")
    app = _agent_app(tmp_path, scripted=(("ok", ()),))
    stdin = StringIO("/status\n/exit\n")
    stdout = StringIO()
    run_agent_cli(
        app=app,
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        goal="status context",
        gateway=AutoApproveGateway(),
        offline=True,
        input_stream=stdin,
        output_stream=stdout,
    )
    output = stdout.getvalue()
    start = output.index('{\n  "entry": "mandate-status"')
    end = output.index("\nyou> ", start)
    payload = json.loads(output[start:end])
    assert payload["agent_context"]["path"] == "AGENTS.md"
    assert len(payload["agent_context"]["sha256"]) == 64


def test_trusted_profile_admits_git_status(tmp_path: Path) -> None:
    app = _agent_app(
        tmp_path,
        scripted=(
            ("", (_proposal("call-1", "workspace.shell", {"command": "git status"}),)),
            ("done", ()),
        ),
    )
    result = run_agent_cli(
        app=app,
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        goal="git status",
        gateway=_ApproveAllGateway(),
        prompt="check git",
        offline=True,
    )
    assert result.exit_code == 0
    provider = app.provider
    assert isinstance(provider, DeterministicProvider)
    tool_messages = [
        message
        for message in provider.requests[1].messages
        if message.role is ProviderMessageRole.TOOL
    ]
    assert tool_messages
    assert "not in the shell allowlist" not in tool_messages[0].content


def test_unlisted_shell_command_denied(tmp_path: Path) -> None:
    app = _agent_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.shell",
                        {"command": "curl evil.example"},
                    ),
                ),
            ),
            ("blocked", ()),
        ),
    )
    run_agent_cli(
        app=app,
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        goal="bad shell",
        gateway=_ApproveAllGateway(),
        prompt="exfiltrate",
        offline=True,
    )
    provider = app.provider
    assert isinstance(provider, DeterministicProvider)
    tool_messages = [
        message
        for message in provider.requests[1].messages
        if message.role is ProviderMessageRole.TOOL
    ]
    assert "not in the shell allowlist" in tool_messages[0].content


def test_trusted_profile_applied_to_sandbox_directly(tmp_path: Path) -> None:
    sandbox = WorkspaceSandbox(tmp_path)
    sandbox.set_shell_allowlist(TRUSTED_SHELL_PROFILE_V1)
    sandbox._shell({"command": "git status"}, "action:git-status")
    with pytest.raises(CapabilityDenied, match="not in the shell allowlist"):
        sandbox._shell({"command": "curl evil.example"}, "action:curl")
