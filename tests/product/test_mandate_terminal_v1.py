"""Terminal V1: shell/search, zero-config attach, continuation."""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_os_contracts import ProviderToolProposal
from agent_os_core.capability import CapabilityDenied, WorkspaceSandbox
from agent_os_core.governance import CorrectionAuthority
from agent_os_core.mandate_repl import (
    MandateRepl,
    SequencedProvider,
    make_tool_response,
    run_mandate_repl,
)
from agent_os_core.mandate_terminal import (
    MandateTerminalError,
    ensure_local_mandate_session,
    load_attach_session,
)
from agent_os_core.mandate_tool_runtime import MandateToolRuntime
from agent_os_contracts import ActionContract, ActionPermit, ResourceBudget
from decimal import Decimal
from uuid import uuid4

NOW = datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc)


def test_workspace_search_finds_line(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    sandbox = WorkspaceSandbox(repo)
    out = sandbox._dispatch(
        "workspace.search",
        {"pattern": "def alpha", "glob": "*.py"},
        "key:search",
    )
    assert out["match_count"] == 1
    assert out["matches"][0]["path"] == "a.py"


def test_workspace_shell_allowlist_and_deny(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    sandbox = WorkspaceSandbox(repo)
    ok = sandbox._dispatch(
        "workspace.shell",
        {"argv": ["pwd"]},
        "key:shell-ok",
    )
    assert ok["exit_code"] == 0
    assert str(repo) in ok["stdout"] or ok["stdout"].strip() != ""
    try:
        sandbox._dispatch(
            "workspace.shell",
            {"argv": "rm -rf /"},
            "key:shell-bad",
        )
        assert False, "expected deny"
    except CapabilityDenied:
        pass
    try:
        sandbox._dispatch(
            "workspace.shell",
            {"argv": ["ls", ";", "rm", "-rf", "/"]},
            "key:shell-meta",
        )
        assert False, "expected meta deny"
    except CapabilityDenied:
        pass


def test_zero_config_bootstrap_and_reuse(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    database = tmp_path / "db.sqlite3"
    workspace.mkdir()
    session, created = ensure_local_mandate_session(
        workspace=workspace,
        database=database,
        goal_statement="Ship terminal V1",
        evaluated_at=NOW,
    )
    assert created is True
    assert session.mandate_id == "mandate:local-terminal"
    again, created2 = ensure_local_mandate_session(
        workspace=workspace,
        database=database,
        evaluated_at=NOW,
    )
    assert created2 is False
    assert again.mandate_id == session.mandate_id
    loaded = load_attach_session(workspace)
    assert loaded.mandate_id == session.mandate_id


def test_run_mandate_repl_zero_config_without_prior_attach(tmp_path: Path) -> None:
    from agent_os_core.provider import DeterministicProvider

    workspace = tmp_path / "ws"
    database = tmp_path / "db.sqlite3"
    repo = tmp_path / "repo"
    workspace.mkdir()
    repo.mkdir()
    out = io.StringIO()
    lines = iter(["/quit"])
    result = run_mandate_repl(
        workspace=workspace,
        database=database,
        provider=DeterministicProvider(text="hi"),
        input_fn=lambda _p: next(lines),
        stdout=out,
        clock=lambda: NOW,
        zero_config=True,
        tools_enabled=False,
        repo_root=repo,
    )
    assert result.auto_attached is True
    assert "[zero-config]" in out.getvalue()
    assert result.quit_reason == "quit"


def test_continuation_cycles_until_done(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    database = tmp_path / "db.sqlite3"
    repo = tmp_path / "repo"
    workspace.mkdir()
    repo.mkdir()
    ensure_local_mandate_session(
        workspace=workspace,
        database=database,
        goal_statement="finish work",
        evaluated_at=NOW,
    )
    provider = SequencedProvider(
        [
            make_tool_response(request_id="r1", text="working"),
            make_tool_response(request_id="r2", text="DONE all set"),
        ]
    )
    out = io.StringIO()
    # only /quit if continuation stops; initial prompt drives first turn
    lines = iter(["/quit"])
    result = MandateRepl(
        workspace=workspace,
        provider=provider,
        input_fn=lambda _p: next(lines),
        stdout=out,
        clock=lambda: NOW,
        repo_root=repo,
        initial_prompt="finish work",
        continue_autonomous=True,
        max_continuation_cycles=3,
        tools_enabled=True,
        auto_approve_patches=True,
    ).run()
    assert result.continuation_cycles >= 1
    assert "DONE" in out.getvalue()
    assert "[continuation]" in out.getvalue()
    assert result.provider_calls == 2


def test_tools_list_includes_shell_and_search(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    database = tmp_path / "db.sqlite3"
    repo = tmp_path / "repo"
    workspace.mkdir()
    repo.mkdir()
    ensure_local_mandate_session(
        workspace=workspace, database=database, evaluated_at=NOW
    )
    provider = SequencedProvider([make_tool_response(request_id="r1", text="ok")])
    answers = iter(["/tools", "/quit"])
    out = io.StringIO()
    MandateRepl(
        workspace=workspace,
        provider=provider,
        input_fn=lambda _p: next(answers),
        stdout=out,
        clock=lambda: NOW,
        repo_root=repo,
    ).run()
    text = out.getvalue()
    assert "workspace.shell" in text
    assert "workspace.search" in text
