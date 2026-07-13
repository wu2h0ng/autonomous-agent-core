"""Fresh successor CLI qualification and authority-binding contracts."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from product_evals.spine_e2e_3 import cli
from product_evals.spine_e2e_3.identity import IDENTITY


ROOT = Path(__file__).resolve().parents[2]
E2E3 = ROOT / "product_evals/spine_e2e_3"


def _run(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        phase_ledger=tmp_path / "formal/evaluation/phases.jsonl",
        provider_ledger=tmp_path / "formal/evaluation/provider_calls.jsonl",
        template_path=E2E3 / "request_template.json",
        bank_path=E2E3 / "provider_responses.json",
        qualification_receipt_path=E2E3 / "instrument_qualification_receipt.json",
        context_sha256="c" * 64,
    )


def test_authority_is_bound_only_to_the_fresh_successor_permission(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = _run(tmp_path)
    cli._assert_authority_bound()
    assert cli.APPROVAL_REQUEST_ID == "perm_6be957f2b552ccd7"
    assert cli.REQUEST_ROW_SHA256 == (
        "f42209feaa630e99e02901e2128d6ccfba606b3217d7021686d766bb95e25239"
    )
    assert cli.APPROVAL_ROW_SHA256 == (
        "cb7af0b5ef52e545430664272050db3950036029b413e91a72d0bf2493ca7606"
    )
    monkeypatch.setattr(cli, "APPROVAL_REQUEST_ID", None)
    with pytest.raises(ValueError, match="UNBOUND_SUCCESSOR_AUTHORITY"):
        cli._assert_authority_bound()
    assert not run.phase_ledger.exists()
    assert not run.provider_ledger.exists()


def test_context_binding_algorithm_tracks_the_actual_mapping_size() -> None:
    assert cli._context_algorithm({"a": "1"}) == "canonical_sha256(exact_1_key_mapping)"
    assert cli._context_algorithm({"a": "1", "b": "2"}) == (
        "canonical_sha256(exact_2_key_mapping)"
    )


def test_genesis_verifies_receipt_before_dependencies_or_ledgers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = _run(tmp_path)
    monkeypatch.setattr(
        cli,
        "verify_qualification_receipt",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("INVALID_INSTRUMENT_QUALIFICATION")
        ),
    )
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("dependency check preceded receipt"),
    )

    with pytest.raises(ValueError, match="INVALID_INSTRUMENT_QUALIFICATION"):
        cli.evaluation_genesis_preflight(run)
    assert not run.phase_ledger.exists()
    assert not run.provider_ledger.exists()


def test_genesis_uses_identity_assets_and_explicit_temporary_ledgers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = _run(tmp_path)
    verified: list[dict[str, object]] = []
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        cli,
        "verify_qualification_receipt",
        lambda identity, **kwargs: verified.append({"identity": identity, **kwargs}),
    )
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda command, **kwargs: (
            calls.append(tuple(command)) or subprocess.CompletedProcess(command, 0)
        ),
    )

    cli.evaluation_genesis_preflight(run)

    assert verified == [
        {
            "identity": IDENTITY,
            "template_path": run.template_path,
            "bank_path": run.bank_path,
            "receipt_path": run.qualification_receipt_path,
        }
    ]
    assert calls == [
        (str(cli.PRODUCT_INTERPRETER), "-c", cli.PRODUCT_IMPORT_CHECK),
        (str(cli.RUNNER_INTERPRETER), "-c", "import yaml"),
    ]
    assert not run.phase_ledger.exists()
    assert not run.provider_ledger.exists()


def test_provider_server_receives_the_identity_derived_bearer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed: dict[str, object] = {}

    class Server:
        base_url = "http://127.0.0.1:1234/v1"

        def start(self) -> None:
            observed["started"] = True

    def build_server(identity: object, bank_path: Path, **kwargs: object) -> Server:
        observed.update({"identity": identity, "bank_path": bank_path, **kwargs})
        return Server()

    configured: list[str] = []
    monkeypatch.setattr(cli, "identity_bound_provider_server", build_server)
    monkeypatch.setattr(
        cli, "configure_provider_environment", lambda value: configured.append(value)
    )
    run = _run(tmp_path)

    server = cli._provider(run)

    assert server.base_url == "http://127.0.0.1:1234/v1"
    assert observed == {
        "identity": IDENTITY,
        "bank_path": run.bank_path,
        "ledger_path": run.provider_ledger,
        "context_sha256": run.context_sha256,
        "started": True,
    }
    assert configured == [server.base_url]
