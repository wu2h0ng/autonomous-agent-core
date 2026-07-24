"""Interactive Mandate terminal REPL (stdin/stdout agent entry)."""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_os_contracts import (
    EnvironmentBindingAuthorization,
    MandateCommitmentContext,
    MandateOutcomeContext,
    MandateRelevanceContext,
    RatifiedMandateRef,
    RelevanceAssessorRef,
)
from agent_os_core.mandate_repl import MandateRepl, run_mandate_repl
from agent_os_core.mandate_terminal import (
    MandateTerminalError,
    attach_mandate,
    bootstrap_mandate,
)
from agent_os_core.provider import DeterministicProvider
from apps.cli import __main__ as cli

NOW = datetime(2026, 7, 23, 5, 0, tzinfo=timezone.utc)
MANDATE_DIGEST = "a" * 64
BINDING_DIGEST = "b" * 64
POLICY_DIGEST = "c" * 64


def _setup(tmp_path: Path) -> Path:
    database = tmp_path / "situated.sqlite3"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    mandate = RatifiedMandateRef(
        mandate_id="mandate:meta-shadow-0",
        version=1,
        mandate_digest=MANDATE_DIGEST,
        ratification_receipt_id="ratification:founder-1",
        tenant_id="tenant:portfolio",
        workspace_id="workspace:founder",
        owner_principal_id="user:founder",
        ratified_by="user:founder",
        ratified_at=NOW - timedelta(hours=1),
        valid_from=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(days=7),
        correction_epoch=0,
        authority_envelope_digest="e" * 64,
        allowed_environment_bindings=(
            EnvironmentBindingAuthorization(
                environment_binding_id="binding:portfolio",
                version=1,
                binding_digest=BINDING_DIGEST,
            ),
        ),
        relevance_assessor=RelevanceAssessorRef(
            assessor_id="assessor:terminal-v0",
            version=1,
            policy_digest=POLICY_DIGEST,
        ),
    )
    context = MandateRelevanceContext(
        relevance_context_id="relevance:meta-shadow-0",
        version=1,
        mandate_id="mandate:meta-shadow-0",
        mandate_version=1,
        mandate_digest=MANDATE_DIGEST,
        tenant_id="tenant:portfolio",
        workspace_id="workspace:founder",
        mission_statement="Advance governed general intelligence under founder correction.",
        desired_outcomes=(
            MandateOutcomeContext(
                outcome_id="outcome:terminal",
                statement="Operate via terminal Mandate agent.",
            ),
        ),
        open_commitments=(
            MandateCommitmentContext(
                commitment_id="commitment:repl",
                statement="Ship interactive Mandate REPL.",
            ),
        ),
        permanent_constraints=("C7 non-bypassable",),
    )
    bootstrap_mandate(
        database=database,
        mandate=mandate,
        relevance_context=context,
        workspace=workspace,
    )
    attach_mandate(
        workspace=workspace,
        database=database,
        mandate_id="mandate:meta-shadow-0",
        environment_binding_id="binding:portfolio",
        principal_id="user:founder",
        tenant_id="tenant:portfolio",
        workspace_id="workspace:founder",
        evaluated_at=NOW,
    )
    return workspace


def test_repl_requires_attach(tmp_path: Path) -> None:
    with pytest.raises(MandateTerminalError, match="attach missing"):
        run_mandate_repl(
            workspace=tmp_path,
            provider=DeterministicProvider(text="x"),
            input_fn=lambda _p: "/quit",
            zero_config=False,
        )


def test_repl_loads_mandate_context_and_talks(tmp_path: Path) -> None:
    workspace = _setup(tmp_path)
    provider = DeterministicProvider(text="Under mandate: next step is status check.")
    lines = iter(["what should I do next?", "/status", "/quit"])
    out = io.StringIO()

    result = MandateRepl(
        workspace=workspace,
        provider=provider,
        provider_profile_id="provider-profile:test",
        input_fn=lambda _p: next(lines),
        stdout=out,
        clock=lambda: NOW,
    ).run()

    text = out.getvalue()
    assert "Agent OS Mandate Terminal" in text
    assert "mandate:meta-shadow-0" in text
    assert "Advance governed general intelligence" in text
    assert "commitment:repl" in text
    assert "Under mandate: next step is status check." in text
    assert result.quit_reason == "quit"
    assert result.provider_calls == 1
    assert len(provider.requests) == 1
    system = provider.requests[0].messages[0].content
    assert "MANDATE_CONTEXT_JSON" in system
    assert "mandate:meta-shadow-0" in system


def test_repl_help_emits_structured_inbox(tmp_path: Path) -> None:
    workspace = _setup(tmp_path)
    lines = iter(
        ["/help Should we expand SRL without HCW substrate?", "/quit"]
    )
    out = io.StringIO()
    result = MandateRepl(
        workspace=workspace,
        provider=DeterministicProvider(text="unused"),
        input_fn=lambda _p: next(lines),
        stdout=out,
        clock=lambda: NOW,
    ).run()
    assert result.help_emitted == 1
    assert "[help-request emitted]" in out.getvalue()
    inbox = workspace / ".agent_os" / "mandate_help_inbox.jsonl"
    record = json.loads(inbox.read_text(encoding="utf-8").splitlines()[0])
    assert "Should we expand SRL" in record["help_request"]["minimum_external_input"]
    assert record["help_request"]["mandate_digest"] == MANDATE_DIGEST


def test_cli_mandate_repl_offline(tmp_path: Path, monkeypatch, capsys) -> None:
    workspace = _setup(tmp_path)
    database = tmp_path / "situated.sqlite3"
    lines = iter(["hello", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _p: next(lines))
    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-os",
            "--database",
            str(database),
            "--workspace",
            str(workspace),
            "mandate",
            "--offline",
        ],
    )
    cli.main()
    out = capsys.readouterr().out
    assert "Agent OS Mandate Terminal" in out
    assert "bye" in out


def test_bare_agent_os_name_launches_repl(tmp_path: Path, monkeypatch, capsys) -> None:
    """Codex-style: typing the agent name alone enters the Mandate REPL."""
    workspace = _setup(tmp_path)
    database = tmp_path / "situated.sqlite3"
    lines = iter(["/quit"])
    monkeypatch.setattr("builtins.input", lambda _p: next(lines))
    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-os",
            "--database",
            str(database),
            "--workspace",
            str(workspace),
            "--offline",
        ],
    )
    cli.main()
    out = capsys.readouterr().out
    assert "Agent OS Mandate Terminal" in out
    assert "bye" in out


def test_normalize_argv_inserts_mandate_default() -> None:
    assert cli._normalize_argv(["agent-os"]) == ["agent-os", "mandate"]
    assert cli._normalize_argv(["agent-os", "--offline"]) == [
        "agent-os",
        "--offline",
        "mandate",
    ]
    assert cli._normalize_argv(["agent-os", "hello"]) == [
        "agent-os",
        "mandate",
        "hello",
    ]
    assert cli._normalize_argv(["agent-os", "mandate-status"])[1] == "mandate-status"


def test_initial_prompt_like_codex(tmp_path: Path) -> None:
    workspace = _setup(tmp_path)
    provider = DeterministicProvider(text="noted")
    out = io.StringIO()
    lines = iter(["/quit"])
    result = MandateRepl(
        workspace=workspace,
        provider=provider,
        input_fn=lambda _p: next(lines),
        stdout=out,
        clock=lambda: NOW,
        initial_prompt="summarize open commitments",
    ).run()
    assert result.provider_calls == 1
    assert "> summarize open commitments" in out.getvalue()
    assert provider.requests[0].messages[-1].content == "summarize open commitments"
