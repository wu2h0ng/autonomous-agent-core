"""Scratch-only formal-path contracts; this file must never open the formal run."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from product_evals.common.artifacts import canonical_sha256, sha256_file
from product_evals.common.authority_binding import AuthorityBinding
from product_evals.common.json_schema_contract import validate_closed_record
from product_evals.spine_e2e_4.identity import IDENTITY


ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT.parents[2]
FORMAL_ROOT = WORKSPACE / ".agent_runs" / IDENTITY.run_id
RUNNER_WORKTREE = (
    WORKSPACE
    / "ai-agent-engineering-workflow/.worktrees/team-event-contract-v1-20260713"
)
RUNNER_PYTHON = WORKSPACE / "ai-agent-engineering-workflow/.venv/bin/python"


def _cli() -> Any:
    return importlib.import_module("product_evals.spine_e2e_4.cli")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


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
        runner_schema_path=tmp_path / "runner_team_event_schema.json",
        context_sha256="c" * 64,
        context_bindings={
            "spec_sha256": "s" * 64,
            "prereg_lock_sha256": "l" * 64,
            "corpus_sha256": "a" * 64,
            "evaluator_sha256": "b" * 64,
            "provider_bank_sha256": "d" * 64,
        },
    )


def _authority(cli: Any) -> AuthorityBinding:
    return AuthorityBinding(
        request_sha256="1" * 64,
        approval_sha256="2" * 64,
        request_id="permission-e2e4",
        action="team.event.record",
        affected_path=f".agent_runs/{IDENTITY.run_id}/agent_events.jsonl",
        decision="approved_session",
        decided_by="founder",
        source_decision_id="decision-e2e4",
        source_goal_id="goal-e2e4",
        source_decision_type="founder_authorization",
        evidence_refs=tuple(
            f"evaluation/anchor_requests/{phase}.json" for phase in cli.PHASES
        ),
        request_ts=cli.datetime.fromisoformat("2026-07-13T00:00:00+00:00"),
        approval_ts=cli.datetime.fromisoformat("2026-07-13T00:00:01+00:00"),
    )


def _runner_contract_value(script: str, payload: object | None = None) -> Any:
    completed = subprocess.run(
        [str(RUNNER_PYTHON), "-c", script],
        cwd=RUNNER_WORKTREE,
        env={**os.environ, "PYTHONPATH": str(RUNNER_WORKTREE / "src")},
        input=None if payload is None else json.dumps(payload),
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(completed.stdout)


def _real_runner_event(binding: AuthorityBinding) -> dict[str, Any]:
    value = _runner_contract_value(
        "import json,sys; "
        "from agent_workflow_runner.team_event_contract import "
        "build_team_event_record; "
        "json.dump(build_team_event_record(**json.load(sys.stdin)), sys.stdout)",
        {
            "ts": "2026-07-13T00:00:02+00:00",
            "event_type": "EVIDENCE_APPENDED",
            "agent_id": "codex-cto",
            "task_id": None,
            "summary": "anchor summary",
            "artifact": "evaluation/anchor_requests/prepare.json",
            "stream_file": None,
            "permission_action": binding.action,
            "approval_request_id": binding.request_id,
            "evidence_refs": ["evaluation/anchor_requests/prepare.json"],
            "source_decision_id": binding.source_decision_id,
            "source_goal_id": binding.source_goal_id,
            "source_decision_type": binding.source_decision_type,
        },
    )
    assert isinstance(value, dict)
    return value


def _real_runner_schema() -> dict[str, Any]:
    value = _runner_contract_value(
        "import json; "
        "from agent_workflow_runner.team_event_contract import "
        "get_team_event_schema; "
        "print(json.dumps(get_team_event_schema()))"
    )
    assert isinstance(value, dict)
    return value


def test_scratch_fixture_is_disjoint_from_the_forbidden_formal_root(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path)
    for path in (
        run.run_root,
        run.phase_ledger,
        run.provider_ledger,
        run.event_ledger,
    ):
        assert not path.is_relative_to(FORMAL_ROOT)
    assert not FORMAL_ROOT.exists()


def test_anchor_fixture_is_built_by_the_pinned_runner_public_builder() -> None:
    binding = _authority(
        SimpleNamespace(
            datetime=datetime,
            PHASES=(
                "prepare",
                "interrupt_batch",
                "probe_active_lease",
                "resume",
                "adjudicate",
            ),
        )
    )
    event = _real_runner_event(binding)
    schema = _real_runner_schema()

    validate_closed_record(event, schema)
    assert event["approval_request_id"] == binding.request_id
    assert event["source_decision_id"] == binding.source_decision_id
    assert event["source_goal_id"] == binding.source_goal_id
    assert event["source_decision_type"] == binding.source_decision_type


def test_phase_order_requires_the_immediately_prior_schema_driven_anchor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = _cli()
    run = _run(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(cli, "_phase_anchor", lambda value, phase: calls.append(phase))

    cli._prior_anchor(run, "prepare")
    assert calls == []
    for index, phase in enumerate(cli.PHASES[1:], start=1):
        cli._prior_anchor(run, phase)
        assert calls[-1] == cli.PHASES[index - 1]


def test_run_phase_is_write_once_and_binds_exact_timing_gates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = _cli()
    run = _run(tmp_path)
    bound: list[str] = []
    observed_gates: list[tuple[Any, ...]] = []

    class Guard:
        def bind_payload(self, digest: str) -> None:
            bound.append(digest)

    @contextmanager
    def guard(*args: object, **kwargs: Any):
        assert args[0] == run.phase_ledger
        observed_gates.append(tuple(kwargs["elapsed_gates"]))
        yield Guard()

    output = {"schema_version": IDENTITY.schema("resume"), "cases": {}}
    monkeypatch.setattr(cli, "evaluation_genesis_preflight", lambda value: None)
    monkeypatch.setattr(cli, "_prior_anchor", lambda value, phase: None)
    monkeypatch.setattr(cli, "_execute_phase", lambda value, phase: output)
    monkeypatch.setattr(cli, "phase_guard", guard)

    cli._run_phase(run, "resume")

    payload = run.data_root / "phases/resume.json"
    assert json.loads(payload.read_text()) == output
    assert bound == [canonical_sha256(output)]
    assert [(gate.start_phase, gate.start_state) for gate in observed_gates[0]] == [
        ("interrupt_batch", "completed"),
        ("prepare", "started"),
    ]
    with pytest.raises(FileExistsError):
        cli._run_phase(run, "resume")


def test_phase_anchor_invokes_closed_schema_consumer_and_typed_authority(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = _cli()
    run = _run(tmp_path)
    binding = _authority(cli)
    observed: list[tuple[dict[str, Any], dict[str, Any]]] = []
    event = _real_runner_event(binding)
    schema = _real_runner_schema()
    monkeypatch.setattr(cli, "_authority_binding", lambda value: binding)
    monkeypatch.setattr(cli, "_expected_anchor", lambda *args: {"phase": "prepare"})
    monkeypatch.setattr(
        cli,
        "_json_file",
        lambda path: schema if path == run.runner_schema_path else {"phase": "prepare"},
    )
    monkeypatch.setattr(cli, "_jsonl", lambda path: [event])
    monkeypatch.setattr(cli, "_verify_runner", lambda *args: None)
    monkeypatch.setattr(
        cli,
        "validate_closed_record",
        lambda record, contract: observed.append((dict(record), dict(contract))),
    )

    cli._phase_anchor(run, "prepare")

    assert observed == [(event, schema)]


@pytest.mark.parametrize("mutation", ["extra", "missing-source", "duplicate"])
def test_phase_anchor_fails_closed_for_unknown_partial_or_duplicate_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
) -> None:
    cli = _cli()
    run = _run(tmp_path)
    binding = _authority(cli)
    event = _real_runner_event(binding)
    rows = [event]
    if mutation == "extra":
        event = {**event, "predecessor_only": True}
        rows = [event]
    elif mutation == "missing-source":
        event = dict(event)
        event.pop("source_goal_id")
        rows = [event]
    else:
        rows = [event, dict(event)]
    monkeypatch.setattr(cli, "_authority_binding", lambda value: binding)
    monkeypatch.setattr(cli, "_expected_anchor", lambda *args: {"phase": "prepare"})
    monkeypatch.setattr(cli, "_json_file", lambda path: {"phase": "prepare"})
    monkeypatch.setattr(cli, "_jsonl", lambda path: rows)
    monkeypatch.setattr(cli, "_verify_runner", lambda *args: None)
    if mutation == "duplicate":
        monkeypatch.setattr(cli, "validate_closed_record", lambda *args: None)

    with pytest.raises(ValueError, match="INVALID_RUNNER_ANCHOR"):
        cli._phase_anchor(run, "prepare")


def test_record_anchor_uses_real_pinned_runner_and_all_authority_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = _cli()
    run = _run(tmp_path)
    binding = _authority(cli)
    record = SimpleNamespace(
        phase="prepare_completed",
        record_sha256="a" * 64,
        payload_sha256="b" * 64,
        clock=SimpleNamespace(boot_hash="c" * 64, host_hash="d" * 64),
    )
    run.phase_ledger.parent.mkdir(parents=True)
    run.phase_ledger.write_text("phase\n", encoding="utf-8")
    run.provider_ledger.write_text("provider\n", encoding="utf-8")
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(cli, "read_phases", lambda *args: [record])
    monkeypatch.setattr(cli, "_completed_record", lambda *args: record)
    monkeypatch.setattr(
        cli, "_provider_ledger_rows", lambda value: [{"record_sha256": "e" * 64}]
    )
    monkeypatch.setattr(cli, "_authority_binding", lambda value: binding)
    monkeypatch.setattr(cli, "_phase_anchor", lambda *args: {})
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda command, **kwargs: commands.append(tuple(command)),
    )

    cli._record_runner_anchor(run)

    command = commands[0]
    assert str(cli.RUNNER_INTERPRETER) in command
    assert "agent_workflow_runner.cli" in command
    for option, value in (
        ("--source-decision-id", binding.source_decision_id),
        ("--source-goal-id", binding.source_goal_id),
        ("--source-decision-type", binding.source_decision_type),
        ("--approval-request-id", binding.request_id),
    ):
        assert command[command.index(option) + 1] == value


def test_finalize_rejects_partial_phases_and_writes_result_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = _cli()
    run = _run(tmp_path)
    monkeypatch.setattr(
        cli,
        "read_phases",
        lambda *args: [SimpleNamespace(phase="prepare_started")],
    )
    with pytest.raises(ValueError, match="INVALID_PARTIAL_PHASE"):
        cli._finalize_result(run)

    phases = [
        f"{phase}_{suffix}"
        for phase in cli.PHASES
        for suffix in ("started", "completed")
    ]
    payload = {"payload": "scratch"}
    run.phase_ledger.parent.mkdir(parents=True, exist_ok=True)
    run.phase_ledger.write_text("phase\n", encoding="utf-8")
    run.provider_ledger.write_text("provider\n", encoding="utf-8")
    _write_json(run.data_root / "phases/adjudication_payload.json", payload)
    monkeypatch.setattr(
        cli,
        "read_phases",
        lambda *args: [SimpleNamespace(phase=phase) for phase in phases],
    )
    monkeypatch.setattr(cli, "_phase_anchor", lambda value, phase: {"phase": phase})
    monkeypatch.setattr(
        cli,
        "_completed_record",
        lambda *args: SimpleNamespace(payload_sha256=canonical_sha256(payload)),
    )
    monkeypatch.setattr(
        cli,
        "adjudicate_spine",
        lambda value: {
            "schema_version": IDENTITY.schema("adjudication-result"),
            "verdict": "PASS",
        },
    )

    cli._finalize_result(run)
    result = run.data_root / "result.json"
    assert json.loads(result.read_text())["run_id"] == IDENTITY.run_id
    assert sha256_file(result)
    with pytest.raises(FileExistsError):
        cli._finalize_result(run)
