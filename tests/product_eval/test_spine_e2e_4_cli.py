"""Static and pre-genesis contracts for the corrected SPINE successor CLI."""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from product_evals.common.authority_binding import AuthorityBinding
from product_evals.spine_e2e_4.identity import IDENTITY


ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT.parents[2]
E2E4 = ROOT / "product_evals/spine_e2e_4"
FORMAL_ROOT = WORKSPACE / ".agent_runs" / IDENTITY.run_id


def _cli() -> Any:
    return importlib.import_module("product_evals.spine_e2e_4.cli")


def _run(tmp_path: Path) -> SimpleNamespace:
    data_root = tmp_path / "scratch/evaluation"
    return SimpleNamespace(
        workspace=tmp_path / "workspace",
        target=tmp_path / "target",
        runner=tmp_path / "runner",
        run_root=tmp_path / "scratch",
        data_root=data_root,
        phase_ledger=data_root / "phases.jsonl",
        provider_ledger=data_root / "provider_calls.jsonl",
        event_ledger=tmp_path / "scratch/agent_events.jsonl",
        template_path=E2E4 / "request_template.json",
        bank_path=E2E4 / "provider_responses.json",
        qualification_receipt_path=E2E4 / "instrument_qualification_receipt.json",
        runner_schema_path=E2E4 / "runner_team_event_schema.json",
        qualification_scratch_root=tmp_path / "qualification-scratch",
        context_sha256="c" * 64,
    )


def test_cli_identity_and_runner_are_successor_owned_not_predecessor_copies() -> None:
    cli = _cli()

    assert cli.RUN_ID == IDENTITY.run_id
    assert cli.EXPERIMENT_ID == IDENTITY.experiment_id
    assert cli.RUNNER_HEAD == "087f5907cd181c6e071fb24f135292abd9681ca7"
    assert cli.RUNNER_BRANCH == "codex/team-event-contract-v1-20260713"
    source = inspect.getsource(cli)
    assert "spine_e2e_3" not in source
    assert "spine-e2e-3" not in source
    assert "_verify_permission_rows" not in source
    assert "event_fields" not in source
    assert "set(row)" not in source


def test_genesis_reverifies_combined_receipt_before_dependencies_or_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = _cli()
    run = _run(tmp_path)
    calls: list[dict[str, Any]] = []

    def reject_after_observation(identity: object, **kwargs: Any) -> None:
        calls.append({"identity": identity, **kwargs})
        raise ValueError("INVALID_INSTRUMENT_QUALIFICATION")

    monkeypatch.setattr(
        cli, "verify_combined_qualification_receipt", reject_after_observation
    )
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("dependency ran before receipt verify"),
    )

    with pytest.raises(ValueError, match="INVALID_INSTRUMENT_QUALIFICATION"):
        cli.evaluation_genesis_preflight(run)

    assert len(calls) == 1
    call = calls[0]
    assert call["identity"] is IDENTITY
    assert call["receipt_path"] == run.qualification_receipt_path
    assert call["runner_schema_path"] == run.runner_schema_path
    assert call["formal_phase_ledger"] == run.phase_ledger
    assert call["formal_provider_ledger"] == run.provider_ledger
    assert call["formal_event_ledger"] == run.event_ledger
    assert not run.phase_ledger.exists()
    assert not run.provider_ledger.exists()
    assert not run.event_ledger.exists()


def test_formal_authority_is_a_typed_binding_not_a_dictionary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = _cli()
    run = _run(tmp_path)
    expected = AuthorityBinding(
        request_sha256="a" * 64,
        approval_sha256="b" * 64,
        request_id="permission-request",
        action="team.event.record",
        affected_path=f".agent_runs/{IDENTITY.run_id}/agent_events.jsonl",
        decision="approved_session",
        decided_by="founder",
        source_decision_id="decision-e2e4",
        source_goal_id="goal-e2e4",
        source_decision_type="founder_authorization",
        evidence_refs=("evaluation/anchor_requests/prepare.json",),
        request_ts=cli.datetime.fromisoformat("2026-07-13T00:00:00+00:00"),
        approval_ts=cli.datetime.fromisoformat("2026-07-13T00:00:01+00:00"),
    )
    observed: dict[str, Any] = {}

    def verify(path: Path, **kwargs: Any) -> AuthorityBinding:
        observed.update(path=path, **kwargs)
        return expected

    monkeypatch.setattr(cli, "verify_authority_binding", verify)

    binding = cli._authority_binding(run)

    assert binding is expected
    assert isinstance(binding, AuthorityBinding)
    assert observed == {
        "path": run.run_root,
        "run_id": IDENTITY.run_id,
        "action": "team.event.record",
        "affected_path": expected.affected_path,
    }


def test_cli_parser_dispatches_every_frozen_command_to_one_resolved_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = _cli()
    run = _run(tmp_path)
    observed: list[tuple[str, str | None, object]] = []
    monkeypatch.setattr(cli, "resolve_frozen_run", lambda: run)
    monkeypatch.setattr(
        cli,
        "_run_phase",
        lambda value, phase: observed.append(("phase", phase, value)),
    )
    monkeypatch.setattr(
        cli,
        "_record_runner_anchor",
        lambda value: observed.append(("anchor", None, value)),
    )
    monkeypatch.setattr(
        cli,
        "_finalize_result",
        lambda value: observed.append(("finalize", None, value)),
    )

    expected = {
        "prepare": ("phase", "prepare"),
        "interrupt-batch": ("phase", "interrupt_batch"),
        "probe-active-lease": ("phase", "probe_active_lease"),
        "resume": ("phase", "resume"),
        "adjudicate": ("phase", "adjudicate"),
        "record-runner-anchor": ("anchor", None),
        "finalize-result": ("finalize", None),
    }
    for command, prefix in expected.items():
        assert cli.main([command]) == 0
        assert observed.pop(0) == (*prefix, run)
    assert not run.data_root.is_relative_to(FORMAL_ROOT)
