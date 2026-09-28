from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path

from agent_os_contracts import ActionContract, CorrectionEpochVector, ResourceBudget
from agent_os_core import AutoApproveGateway, DeterministicProvider, run_agent_cli

from apps.api_server.app import AgentOSApplication
from apps.cli.__main__ import TerminalConfirmationGateway, _normalize_argv


NOW = datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc)


def _agent_app(root: Path) -> AgentOSApplication:
    app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
    app.provider = DeterministicProvider(
        scripted=(("ok", ()),),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def _action(capability_id: str = "workspace.edit") -> ActionContract:
    return ActionContract(
        action_id="action-product-surface",
        task_id="task-product-surface",
        run_id="run-product-surface",
        node_id="node-product-surface",
        principal_id="principal-product-surface",
        tenant_id="tenant-product-surface",
        workspace_id="workspace-product-surface",
        capability_id=capability_id,
        capability_version="1",
        arguments_json=json.dumps({"path": "fixture.txt"}),
        risk_tier=2,
        idempotency_key="idem-product-surface",
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0.01"),
            max_duration_seconds=5,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-product-surface",
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=0,
            run_epoch=0,
            capability_epoch=0,
        ),
        expected_outcome_id="expected-product-surface",
        candidate_envelope_id="envelope-product-surface",
        created_at=NOW,
    )


def test_bare_agent_command_opens_interactive_agent_surface() -> None:
    assert _normalize_argv(["agent"]) == ["agent", "agent"]
    assert _normalize_argv(["agent", "--workspace", "."]) == [
        "agent",
        "--workspace",
        ".",
        "agent",
    ]
    assert _normalize_argv(["agent", "--workspace", ".", "--offline"]) == [
        "agent",
        "--workspace",
        ".",
        "agent",
        "--offline",
    ]


def test_repl_banner_presents_product_surface_without_internal_run_ids(
    tmp_path: Path,
) -> None:
    stdout = StringIO()
    run_agent_cli(
        app=_agent_app(tmp_path),
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        goal="inspect workspace",
        gateway=AutoApproveGateway(),
        offline=True,
        input_stream=StringIO("/exit\n"),
        output_stream=stdout,
    )

    output = stdout.getvalue()
    assert "Agent OS" in output
    assert f"Workspace  {tmp_path.resolve()}" in output
    assert "Model      deterministic-v1" in output
    assert "you> " in output
    assert "mandate:" not in output
    assert "task " not in output.lower()
    assert "task_id" not in output
    assert "run_id" not in output
    assert "session_id" not in output


def test_status_command_is_user_status_not_internal_session_dump(
    tmp_path: Path,
) -> None:
    (tmp_path / "AGENTS.md").write_text("project guidance\n", encoding="utf-8")
    stdout = StringIO()
    run_agent_cli(
        app=_agent_app(tmp_path),
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        goal="status check",
        gateway=AutoApproveGateway(),
        offline=True,
        input_stream=StringIO("/status\n/exit\n"),
        output_stream=stdout,
    )

    output = stdout.getvalue()
    assert "Workspace  " in output
    assert "Model      deterministic-v1" in output
    assert "Session    active" in output
    assert "Context    1 messages" in output
    assert "Instructions  AGENTS.md" in output
    assert "mandate:" not in output
    assert '"agent_session"' not in output
    assert "task_id" not in output
    assert "run_id" not in output
    assert "session_id" not in output


def test_resume_command_does_not_print_internal_session_id(tmp_path: Path) -> None:
    first = run_agent_cli(
        app=_agent_app(tmp_path),
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        goal="resume check",
        gateway=AutoApproveGateway(),
        prompt="hello",
        offline=True,
    )
    assert first.exit_code == 0

    stdout = StringIO()
    run_agent_cli(
        app=_agent_app(tmp_path),
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        goal="resume check",
        gateway=AutoApproveGateway(),
        resume=True,
        offline=True,
        input_stream=StringIO("/resume\n/exit\n"),
        output_stream=stdout,
    )

    output = stdout.getvalue()
    assert "[resumed; " in output
    assert "resumed session" not in output
    assert "session_id" not in output
    assert "run_id" not in output
    assert "task_id" not in output


def test_terminal_approval_uses_inline_choices_without_capability_label(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "1")
    gateway = TerminalConfirmationGateway()

    assert gateway.confirm(_action(), "Would edit fixture.txt") is True

    output = capsys.readouterr().out
    assert "Approval requested" in output
    assert "Would edit fixture.txt" in output
    assert "[1] Allow once" in output
    assert "Allow edits for this session" in output
    assert "Reject" in output
    assert "workspace.edit" not in output
    assert "[approval required]" not in output


def test_terminal_approval_can_allow_edits_for_current_session(
    monkeypatch,
) -> None:
    replies = iter(["2"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(replies))
    gateway = TerminalConfirmationGateway()

    assert gateway.confirm(_action(), "First edit") is True
    assert gateway.confirm(_action(), "Second edit") is True
