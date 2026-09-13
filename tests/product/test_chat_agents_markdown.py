"""M1: workspace AGENTS.md context is injected into the chat system prompt."""

from __future__ import annotations

from pathlib import Path

from agent_os_core import AgentLoopConfig, DeferredApprovalGateway, DeterministicProvider

from apps.api_server.app import AgentOSApplication


def _app(root: Path) -> AgentOSApplication:
    app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
    app.provider = DeterministicProvider(
        scripted=(("ok", ()),),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def _system_prompt(root: Path) -> str:
    app = _app(root)
    _, loop = app.open_chat_session("hi", DeferredApprovalGateway())
    return loop.history[0].content


def test_chat_injects_workspace_agents_markdown(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# Project rules\nBe careful.\n", encoding="utf-8")
    system = _system_prompt(tmp_path)
    assert "Project AGENTS.md" in system
    assert "Be careful." in system
    assert "sha256=" in system


def test_chat_without_agents_markdown_is_unchanged(tmp_path: Path) -> None:
    assert "Project AGENTS.md" not in _system_prompt(tmp_path)


def test_chat_ignores_symlinked_agents_markdown(tmp_path: Path) -> None:
    (tmp_path / "real.md").write_text("secret\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").symlink_to(tmp_path / "real.md")
    assert "Project AGENTS.md" not in _system_prompt(tmp_path)


def test_chat_ignores_non_utf8_agents_markdown(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_bytes(b"\xff\xfe\x00not utf-8")
    # must be a no-op, not an exception
    assert "Project AGENTS.md" not in _system_prompt(tmp_path)


def test_explicit_loop_config_wins_over_agents_markdown(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# rules\n", encoding="utf-8")
    app = _app(tmp_path)
    _, loop = app.open_chat_session(
        "hi",
        DeferredApprovalGateway(),
        loop_config=AgentLoopConfig(system_prompt="EXPLICIT"),
    )
    assert loop.history[0].content == "EXPLICIT"
