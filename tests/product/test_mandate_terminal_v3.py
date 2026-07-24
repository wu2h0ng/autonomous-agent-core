"""TERMINAL-3: freer bash, MCP hub, streaming TUI surface."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path
from uuid import uuid4

from agent_os_contracts import (
    ProviderErrorCode,
    ProviderFailure,
    ProviderResponse,
    ProviderToolProposal,
    ProviderUsage,
)
from agent_os_core.capability import CapabilityDenied, WorkspaceSandbox
from agent_os_core.mandate_repl import MandateRepl, SequencedProvider, run_mandate_repl
from agent_os_core.mandate_terminal import ensure_local_mandate_session
from agent_os_core.terminal_mcp import MandateMcpHub
from agent_os_core.terminal_tui import TerminalRenderer

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def _fixture_mcp_config() -> dict:
    import agent_os_core.terminal_mcp_fixture_server as fixture

    script = Path(fixture.__file__).resolve()
    return {
        "servers": {
            "fixture": {
                "command": "python3",
                "args": [str(script)],
            }
        }
    }


def _boot(workspace: Path, database: Path):
    session, _ = ensure_local_mandate_session(
        workspace=workspace,
        database=database,
        goal_statement="terminal-3",
        evaluated_at=NOW,
    )
    return session


def test_freer_bash_allows_python_and_bash_c(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    sandbox = WorkspaceSandbox(repo)
    py = sandbox._dispatch(
        "workspace.shell",
        {"argv": ["python3", "-c", "print(40+2)"]},
        "key:py",
    )
    assert py["exit_code"] == 0
    assert "42" in py["stdout"]
    bash = sandbox._dispatch(
        "workspace.shell",
        {"argv": ["bash", "-c", "echo hello-t3"]},
        "key:bash",
    )
    assert bash["exit_code"] == 0
    assert "hello-t3" in bash["stdout"]


def test_freer_bash_still_denies_meta_and_sudo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    sandbox = WorkspaceSandbox(repo)
    for argv in (
        ["ls", ";", "rm", "-rf", "/"],
        "echo hi | cat",
        ["sudo", "ls"],
        ["bash", "-c", "echo a; echo b"],
    ):
        try:
            sandbox._dispatch("workspace.shell", {"argv": argv}, f"key:{argv}")
            raise AssertionError(f"expected deny for {argv!r}")
        except CapabilityDenied:
            pass


def test_mcp_hub_lists_and_calls_fixture_server(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg = workspace / ".agent_os"
    cfg.mkdir()
    (cfg / "mcp.json").write_text(
        json.dumps(_fixture_mcp_config()),
        encoding="utf-8",
    )
    hub = MandateMcpHub(workspace)
    tools = hub.start()
    try:
        assert any(t.capability_id == "mcp.fixture.echo" for t in tools)
        out = hub.call("mcp.fixture.echo", {"text": "ping"})
        text = json.dumps(out)
        assert "echo:ping" in text
    finally:
        hub.close()


def test_repl_invokes_mcp_tool_with_approval(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    database = tmp_path / "db.sqlite3"
    repo = tmp_path / "repo"
    workspace.mkdir()
    repo.mkdir()
    cfg = workspace / ".agent_os"
    cfg.mkdir()
    (cfg / "mcp.json").write_text(
        json.dumps(_fixture_mcp_config()),
        encoding="utf-8",
    )
    session = _boot(workspace, database)
    proposal = ProviderToolProposal(
        proposal_id="p1",
        capability_id="mcp.fixture.echo",
        arguments_json=json.dumps({"text": "from-repl"}),
    )

    def make_response(text: str, tools=()):
        return ProviderResponse(
            response_id=f"r-{uuid4()}",
            request_id="ignored",
            text=text,
            tool_proposals=tuple(tools),
            usage=ProviderUsage(
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
                estimated_cost_usd=Decimal("0"),
            ),
            finish_reason="stop",
            received_at=NOW,
        )

    provider = SequencedProvider(
        [
            make_response("(tool)", [proposal]),
            make_response("DONE mcp ok"),
        ]
    )
    answers = iter(["y", "/quit"])
    out = StringIO()
    repl = MandateRepl(
        workspace=workspace,
        provider=provider,
        session=session,
        stdin=StringIO(""),
        stdout=out,
        input_fn=lambda _p: next(answers),
        clock=lambda: NOW,
        initial_prompt="call mcp",
        tools_enabled=True,
        repo_root=repo,
        enable_mcp=True,
        enable_tui=False,
        auto_approve_patches=False,
    )
    result = repl.run()
    text = out.getvalue()
    assert "mcp.fixture.echo" in text or "echo:from-repl" in text
    assert result.tool_invocations >= 1


def test_tui_renderer_ansi_fallback_streams(tmp_path: Path) -> None:
    buf = StringIO()
    renderer = TerminalRenderer(stdout=buf)
    # force non-rich path
    renderer._rich = False
    renderer._live = None
    renderer.start("t3")
    renderer.append_assistant("Hello")
    renderer.append_assistant(" world")
    renderer.add_tool("workspace.read path=a.py")
    renderer.stop()
    text = buf.getvalue()
    assert "Hello" in text
    assert " world" in text
    assert "workspace.read" in text


def test_complete_streaming_default_emits_delta() -> None:
    from agent_os_core.provider import DeterministicProvider
    from agent_os_contracts import (
        ProviderMessage,
        ProviderMessageRole,
        ProviderRequest,
    )

    deltas: list[str] = []
    provider = DeterministicProvider(text="stream-me")
    req = ProviderRequest(
        request_id="req:t3",
        task_id="task:t3",
        run_id="run:t3",
        provider_profile_id="provider-profile:t3",
        messages=(
            ProviderMessage(role=ProviderMessageRole.USER, content="hi"),
        ),
        allowed_capability_ids=(),
        timeout_seconds=30,
        created_at=NOW,
    )
    result = provider.complete_streaming(req, on_text_delta=deltas.append)
    assert isinstance(result, ProviderResponse)
    assert deltas == ["stream-me"]
