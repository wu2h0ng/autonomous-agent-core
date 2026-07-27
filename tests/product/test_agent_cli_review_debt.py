from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from agent_os_contracts import ProviderToolProposal, RunStatus, TaskEventType
from agent_os_core import (
    AutoApproveGateway,
    DeterministicProvider,
    MandateTerminalError,
    ensure_local_mandate_session,
    load_terminal_session,
    run_agent_cli,
)
from agent_os_core.agent_cli import AgentCLIError
from agent_os_core.mandate_terminal import load_attach_session

from apps.api_server.app import AgentOSApplication
from apps.cli import __main__ as cli_main


def _proposal(call_id: str, capability_id: str, arguments: dict) -> ProviderToolProposal:
    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id=capability_id,
        arguments_json=json.dumps(arguments),
    )


def _prepare_workspace(root: Path) -> None:
    (root / "fixture.txt").write_text("stable\n", encoding="utf-8")


def _agent_app(root: Path, scripted=()) -> AgentOSApplication:
    _prepare_workspace(root)
    app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
    app.provider = DeterministicProvider(
        scripted=scripted,
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def test_cli_oneshot_selects_auto_approve_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_agent_cli(**kwargs: object) -> object:
        captured["gateway"] = kwargs["gateway"]
        return type("Result", (), {"exit_code": 0})()

    monkeypatch.setattr(cli_main, "run_agent_cli", fake_run_agent_cli)
    args = argparse.Namespace(
        prompt="fix fixture",
        workspace=".",
        database="agent-os.sqlite3",
        resume=False,
        offline=True,
        no_stream=False,
    )
    exit_code = cli_main._run_agent_command(
        args,
        default_goal="interactive agent session",
        repl_banner_template=None,
    )
    assert exit_code == 0
    assert isinstance(captured["gateway"], AutoApproveGateway)


def test_oneshot_auto_approve_allows_tier2_edit(tmp_path: Path) -> None:
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
    result = run_agent_cli(
        app=app,
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        goal="edit fixture",
        gateway=AutoApproveGateway(),
        prompt="change the fixture",
        offline=True,
    )
    assert result.exit_code == 0
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "mutated\n"


def test_resume_rejects_database_mismatch(tmp_path: Path) -> None:
    app = _agent_app(tmp_path, scripted=(("first", ()),))
    db = tmp_path / "agent-os.sqlite3"
    run_agent_cli(
        app=app,
        workspace=tmp_path,
        database=db,
        goal="bind db",
        gateway=AutoApproveGateway(),
        prompt="hello",
        offline=True,
    )
    saved = load_terminal_session(tmp_path)
    assert Path(saved.database).resolve() == db.resolve()

    other_db = tmp_path / "other.sqlite3"
    app2 = AgentOSApplication(database=other_db, workspace=tmp_path)
    app2.provider = DeterministicProvider(
        scripted=(("nope", ()),),
        invocation_binding=app2.provider.invocation_binding,
    )
    app2.provider_configured = True
    with pytest.raises(MandateTerminalError, match="database"):
        run_agent_cli(
            app=app2,
            workspace=tmp_path,
            database=other_db,
            goal="bind db",
            gateway=AutoApproveGateway(),
            prompt="hello again",
            resume=True,
            offline=True,
        )


def test_resume_rejects_session_database_tamper(tmp_path: Path) -> None:
    app = _agent_app(tmp_path, scripted=(("first", ()),))
    db = tmp_path / "agent-os.sqlite3"
    run_agent_cli(
        app=app,
        workspace=tmp_path,
        database=db,
        goal="bind db",
        gateway=AutoApproveGateway(),
        prompt="hello",
        offline=True,
    )
    session_path = tmp_path / ".agent_os" / "terminal_session.json"
    raw = json.loads(session_path.read_text(encoding="utf-8"))
    raw["database"] = str((tmp_path / "forged.sqlite3").resolve())
    session_path.write_text(json.dumps(raw), encoding="utf-8")
    app2 = _agent_app(tmp_path, scripted=(("nope", ()),))
    with pytest.raises(AgentCLIError, match="database"):
        run_agent_cli(
            app=app2,
            workspace=tmp_path,
            database=db,
            goal="bind db",
            gateway=AutoApproveGateway(),
            prompt="hello again",
            resume=True,
            offline=True,
        )


def test_resume_rejects_correction_halted_run(tmp_path: Path) -> None:
    app = _agent_app(tmp_path, scripted=(("first", ()), ("second", ())))
    db = tmp_path / "agent-os.sqlite3"
    run_agent_cli(
        app=app,
        workspace=tmp_path,
        database=db,
        goal="halt me",
        gateway=AutoApproveGateway(),
        prompt="hello",
        offline=True,
    )
    saved = load_terminal_session(tmp_path)
    app.correct_task(saved.task_id, "review-debt halt fixture")
    with pytest.raises(AgentCLIError, match="correction-halted"):
        run_agent_cli(
            app=app,
            workspace=tmp_path,
            database=db,
            goal="halt me",
            gateway=AutoApproveGateway(),
            prompt="hello again",
            resume=True,
            offline=True,
        )


def test_resume_rejects_terminal_run_status(tmp_path: Path) -> None:
    app = _agent_app(tmp_path, scripted=(("first", ()), ("second", ())))
    db = tmp_path / "agent-os.sqlite3"
    run_agent_cli(
        app=app,
        workspace=tmp_path,
        database=db,
        goal="finish me",
        gateway=AutoApproveGateway(),
        prompt="hello",
        offline=True,
    )
    saved = load_terminal_session(tmp_path)
    status = app.tasks.get_task(saved.task_id).run.status
    if status is RunStatus.QUEUED:
        app.tasks.update_run_status(
            saved.task_id,
            RunStatus.CANCELLED,
            event_type=TaskEventType.RUN_CANCELLED,
        )
    else:
        if status is not RunStatus.RUNNING:
            app.tasks.update_run_status(
                saved.task_id,
                RunStatus.RUNNING,
                event_type=TaskEventType.RUN_STARTED,
            )
        app.tasks.update_run_status(
            saved.task_id,
            RunStatus.FAILED,
            event_type=TaskEventType.RUN_FAILED,
        )
    with pytest.raises(AgentCLIError, match="not resumable"):
        run_agent_cli(
            app=app,
            workspace=tmp_path,
            database=db,
            goal="finish me",
            gateway=AutoApproveGateway(),
            prompt="hello again",
            resume=True,
            offline=True,
        )


def test_ensure_local_rejects_database_mismatch(tmp_path: Path) -> None:
    first_db = tmp_path / "first.sqlite3"
    session, created = ensure_local_mandate_session(
        workspace=tmp_path,
        database=first_db,
        goal_statement="first",
    )
    assert created is True
    assert Path(session.database).resolve() == first_db.resolve()
    attach = load_attach_session(tmp_path)
    assert Path(attach.database).resolve() == first_db.resolve()
    with pytest.raises(MandateTerminalError, match="database"):
        ensure_local_mandate_session(
            workspace=tmp_path,
            database=tmp_path / "second.sqlite3",
            goal_statement="second",
        )
