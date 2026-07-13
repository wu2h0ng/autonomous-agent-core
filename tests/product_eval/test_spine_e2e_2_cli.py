"""Successor evaluation-genesis preflight contract."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from product_evals.spine_e2e_2 import cli


def test_dependency_preflight_fails_before_evaluation_genesis(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    phase = tmp_path / "evaluation/phases.jsonl"
    provider = tmp_path / "evaluation/provider_calls.jsonl"
    run = SimpleNamespace(phase_ledger=phase, provider_ledger=provider)

    def fail(*args: object, **kwargs: object) -> object:
        raise subprocess.CalledProcessError(1, "python")

    monkeypatch.setattr(cli.subprocess, "run", fail)
    with pytest.raises(ValueError, match="INVALID_DEPENDENCY_PREFLIGHT"):
        cli.evaluation_genesis_preflight(run)
    assert not phase.exists()
    assert not provider.exists()


def test_preflight_uses_selected_product_and_fixed_runner_interpreters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, ...]] = []

    def capture(command: tuple[str, ...], **kwargs: object) -> object:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(cli.subprocess, "run", capture)
    cli.evaluation_genesis_preflight(
        SimpleNamespace(
            phase_ledger=tmp_path / "evaluation/phases.jsonl",
            provider_ledger=tmp_path / "evaluation/provider_calls.jsonl",
        )
    )
    assert calls == [
        (str(cli.PRODUCT_INTERPRETER), "-c", cli.PRODUCT_IMPORT_CHECK),
        (str(cli.RUNNER_INTERPRETER), "-c", "import yaml"),
    ]


def test_prepare_preflight_precedes_any_phase_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = SimpleNamespace()
    monkeypatch.setattr(
        cli,
        "evaluation_genesis_preflight",
        lambda value: (_ for _ in ()).throw(ValueError("INVALID_DEPENDENCY_PREFLIGHT")),
    )
    monkeypatch.setattr(
        cli,
        "_prior_anchor",
        lambda *args: pytest.fail("phase access preceded preflight"),
    )
    with pytest.raises(ValueError, match="INVALID_DEPENDENCY_PREFLIGHT"):
        cli._run_phase(run, "prepare")


def test_anchor_command_uses_preflighted_runner_interpreter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record = SimpleNamespace(
        phase="prepare_completed",
        record_sha256="a" * 64,
        payload_sha256="b" * 64,
        clock=SimpleNamespace(boot_hash="c" * 64, host_hash="d" * 64),
    )
    run = SimpleNamespace(
        phase_ledger=tmp_path / "phases.jsonl",
        provider_ledger=tmp_path / "provider_calls.jsonl",
        run_root=tmp_path,
        context_sha256="e" * 64,
        workspace=tmp_path / "workspace",
        runner=tmp_path / "runner",
    )
    run.phase_ledger.write_text("{}\n", encoding="utf-8")
    run.provider_ledger.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(cli, "read_phases", lambda *args: [record])
    monkeypatch.setattr(cli, "_completed_record", lambda *args: record)
    monkeypatch.setattr(
        cli, "_provider_ledger_rows", lambda *args: [{"record_sha256": "f" * 64}]
    )
    monkeypatch.setattr(cli, "sha256_file", lambda *args: "1" * 64)
    monkeypatch.setattr(cli, "write_json_once", lambda *args: "2" * 64)
    monkeypatch.setattr(cli, "_phase_anchor", lambda *args: None)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda command, **kwargs: calls.append(tuple(command)),
    )

    cli._record_runner_anchor(run)

    assert calls[0][0:3] == (
        "env",
        f"PYTHONPATH={run.runner / 'src'}",
        str(cli.RUNNER_INTERPRETER),
    )
