"""Mandate terminal entry: durable status / attach / help without coding-agent chat."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_os_contracts import (
    EnvironmentBindingAuthorization,
    HelpRequest,
    MandateCommitmentContext,
    MandateOutcomeContext,
    MandateRelevanceContext,
    RatifiedMandateRef,
    RelevanceAssessorRef,
    canonical_json,
)
from agent_os_core.mandate_terminal import (
    MandateTerminalError,
    attach_mandate,
    bootstrap_mandate,
    emit_help_request,
    load_attach_session,
    mandate_status,
)
from apps.cli import __main__ as cli

NOW = datetime(2026, 7, 23, 4, 0, tzinfo=timezone.utc)
MANDATE_DIGEST = "a" * 64
BINDING_DIGEST = "b" * 64
POLICY_DIGEST = "c" * 64
OBS_DIGEST = "d" * 64
PROJ_DIGEST = "e" * 64
SOURCE_DIGEST = "f" * 64


def _binding() -> EnvironmentBindingAuthorization:
    return EnvironmentBindingAuthorization(
        environment_binding_id="binding:portfolio",
        version=1,
        binding_digest=BINDING_DIGEST,
    )


def _assessor() -> RelevanceAssessorRef:
    return RelevanceAssessorRef(
        assessor_id="assessor:terminal-v0",
        version=1,
        policy_digest=POLICY_DIGEST,
    )


def _mandate() -> RatifiedMandateRef:
    return RatifiedMandateRef(
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
        allowed_environment_bindings=(_binding(),),
        relevance_assessor=_assessor(),
    )


def _context() -> MandateRelevanceContext:
    return MandateRelevanceContext(
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
                outcome_id="outcome:hcw-substrate",
                statement="Provide a non-chat Mandate terminal substrate.",
            ),
        ),
        open_commitments=(
            MandateCommitmentContext(
                commitment_id="commitment:terminal-entry",
                statement="Ship mandate-status/attach/help-request CLI.",
                due_at=NOW + timedelta(days=2),
            ),
        ),
        permanent_constraints=("C7 non-bypassable", "no self-approval"),
    )


def _help_request() -> HelpRequest:
    return HelpRequest(
        help_request_id="help:terminal-1",
        source_binding_digest=SOURCE_DIGEST,
        mandate_id="mandate:meta-shadow-0",
        mandate_version=1,
        mandate_digest=MANDATE_DIGEST,
        environment_binding_id="binding:portfolio",
        environment_binding_version=1,
        environment_binding_digest=BINDING_DIGEST,
        correction_epoch=0,
        assessor=_assessor(),
        tenant_id="tenant:portfolio",
        workspace_id="workspace:founder",
        triggering_event_id="event:founder-escalation-1",
        event_observation_digest=OBS_DIGEST,
        projection_id="projection:terminal-1",
        projection_digest=PROJ_DIGEST,
        relevance_assessment_id="assessment:terminal-1",
        known_facts=("Mandate terminal entry is missing.",),
        unknown_facts=("Which founder decision is irreducible?",),
        acquisition_attempts=("Checked durable mandate store.",),
        bounded_options=("Authorize terminal slice", "Park Mandate HCW V0"),
        minimum_external_input="Choose A or B for Mandate terminal admission.",
        continuable_work=("Keep SELFDEV parked relative to this entry.",),
        rationale="Irreducible founder choice required before HCW measurement.",
        evidence_ids=("evidence:terminal-gap",),
        created_at=NOW,
        authority_granted=False,
        external_effects_authorized=False,
    )


def test_mandate_terminal_status_requires_attach(tmp_path: Path) -> None:
    with pytest.raises(MandateTerminalError, match="attach missing"):
        mandate_status(workspace=tmp_path)


def test_mandate_terminal_bootstrap_attach_status_and_help(tmp_path: Path) -> None:
    database = tmp_path / "situated.sqlite3"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    boot = bootstrap_mandate(
        database=database,
        mandate=_mandate(),
        relevance_context=_context(),
        workspace=workspace,
    )
    assert boot["mandate_id"] == "mandate:meta-shadow-0"
    assert boot["status"] == "ACTIVE"

    session = attach_mandate(
        workspace=workspace,
        database=database,
        mandate_id="mandate:meta-shadow-0",
        environment_binding_id="binding:portfolio",
        principal_id="user:founder",
        tenant_id="tenant:portfolio",
        workspace_id="workspace:founder",
        evaluated_at=NOW,
    )
    assert session.principal_id == "user:founder"
    loaded = load_attach_session(workspace)
    assert loaded.mandate_id == session.mandate_id

    status = mandate_status(workspace=workspace, evaluated_at=NOW)
    assert status["mission_statement"].startswith("Advance governed")
    assert status["open_commitments"][0]["commitment_id"] == "commitment:terminal-entry"
    assert status["environment_binding"]["environment_binding_id"] == "binding:portfolio"
    assert "NO_AUTONOMY" in status["claim_ceiling"]

    emitted = emit_help_request(
        workspace=workspace,
        help_request=_help_request(),
        evaluated_at=NOW,
    )
    assert emitted["emitted"] is True
    inbox = Path(emitted["inbox_path"])
    lines = inbox.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["help_request"]["help_request_id"] == "help:terminal-1"


def test_mandate_terminal_attach_fails_closed_wrong_principal(tmp_path: Path) -> None:
    database = tmp_path / "situated.sqlite3"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    bootstrap_mandate(database=database, mandate=_mandate())
    with pytest.raises(MandateTerminalError, match="attach denied"):
        attach_mandate(
            workspace=workspace,
            database=database,
            mandate_id="mandate:meta-shadow-0",
            environment_binding_id="binding:portfolio",
            principal_id="user:intruder",
            tenant_id="tenant:portfolio",
            workspace_id="workspace:founder",
            evaluated_at=NOW,
        )


def test_mandate_terminal_help_rejects_digest_mismatch(tmp_path: Path) -> None:
    database = tmp_path / "situated.sqlite3"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    bootstrap_mandate(database=database, mandate=_mandate())
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
    bad = _help_request().model_copy(update={"mandate_digest": "0" * 64})
    with pytest.raises(MandateTerminalError, match="mandate_digest mismatch"):
        emit_help_request(workspace=workspace, help_request=bad, evaluated_at=NOW)


def test_cli_mandate_status_and_help_route(tmp_path: Path, monkeypatch, capsys) -> None:
    database = tmp_path / "situated.sqlite3"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    mandate_path = tmp_path / "mandate.json"
    context_path = tmp_path / "context.json"
    help_path = tmp_path / "help.json"
    mandate_path.write_text(canonical_json(_mandate()) + "\n", encoding="utf-8")
    context_path.write_text(canonical_json(_context()) + "\n", encoding="utf-8")
    help_path.write_text(canonical_json(_help_request()) + "\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-os",
            "--database",
            str(database),
            "--workspace",
            str(workspace),
            "mandate-bootstrap",
            str(mandate_path),
            "--relevance-context",
            str(context_path),
        ],
    )
    cli.main()
    capsys.readouterr()
    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-os",
            "--database",
            str(database),
            "--workspace",
            str(workspace),
            "mandate-attach",
            "--mandate-id",
            "mandate:meta-shadow-0",
            "--environment-binding-id",
            "binding:portfolio",
            "--principal-id",
            "user:founder",
            "--tenant-id",
            "tenant:portfolio",
            "--workspace-id",
            "workspace:founder",
            "--evaluated-at",
            NOW.isoformat(),
        ],
    )
    cli.main()
    capsys.readouterr()
    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-os",
            "--database",
            str(database),
            "--workspace",
            str(workspace),
            "mandate-status",
            "--evaluated-at",
            NOW.isoformat(),
        ],
    )
    cli.main()
    status_out = json.loads(capsys.readouterr().out)
    assert status_out["open_commitments"][0]["commitment_id"] == (
        "commitment:terminal-entry"
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-os",
            "--database",
            str(database),
            "--workspace",
            str(workspace),
            "mandate-help-request",
            str(help_path),
            "--evaluated-at",
            NOW.isoformat(),
        ],
    )
    cli.main()
    help_out = json.loads(capsys.readouterr().out)
    assert help_out["emitted"] is True


def test_cli_mandate_status_without_attach_fails(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-os",
            "--database",
            str(tmp_path / "missing.sqlite3"),
            "--workspace",
            str(tmp_path),
            "mandate-status",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "attach missing" in err or "MandateTerminalError" in err or "mandate" in err
