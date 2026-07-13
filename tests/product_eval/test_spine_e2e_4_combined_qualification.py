from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import shutil
from typing import Any, Callable

import pytest

from product_evals.common.artifacts import canonical_sha256
from product_evals.common.bank_generator import (
    build_provider_bank,
    canonical_json_bytes,
)
from product_evals.common.spine_identity import SpineEvaluationIdentity


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = REPO_ROOT.parents[2]
ASSET_ROOT = REPO_ROOT / "product_evals/spine_e2e_4"
RUNNER_WORKTREE = (
    WORKSPACE_ROOT
    / "ai-agent-engineering-workflow/.worktrees/team-event-contract-v1-20260713"
)
RUNNER_PYTHON = WORKSPACE_ROOT / "ai-agent-engineering-workflow/.venv/bin/python"
RUNNER_BRANCH = "codex/team-event-contract-v1-20260713"
RUNNER_HEAD = "50eb4d27b17688f0943f80207dddb702983afd51"
CONSUMER_SOURCE = REPO_ROOT / "product_evals/common/json_schema_contract.py"
AUTHORITY_SOURCE = REPO_ROOT / "product_evals/common/authority_binding.py"
RUNNER_QUALIFICATION_SOURCE = (
    REPO_ROOT / "product_evals/common/runner_contract_qualification.py"
)
LEGACY_QUALIFICATION_SOURCE = (
    REPO_ROOT / "product_evals/common/instrument_qualification.py"
)
E2E3_RECEIPT = (
    REPO_ROOT / "product_evals/spine_e2e_3/instrument_qualification_receipt.json"
)


def _module() -> Any:
    return importlib.import_module("product_evals.spine_e2e_4.qualification")


def _legacy_module() -> Any:
    return importlib.import_module("product_evals.common.instrument_qualification")


def _runner_module() -> Any:
    return importlib.import_module("product_evals.common.runner_contract_qualification")


def _identity() -> SpineEvaluationIdentity:
    identity_module = importlib.import_module("product_evals.spine_e2e_4.identity")
    return identity_module.IDENTITY


def _paths(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "fixture"
    root.mkdir(parents=True, exist_ok=True)
    template_path = root / "request_template.json"
    bank_path = root / "provider_responses.json"
    consumer_source = root / "json_schema_contract.py"
    authority_source = root / "authority_binding.py"
    template = json.loads((ASSET_ROOT / "request_template.json").read_bytes())
    template_path.write_bytes(canonical_json_bytes(template))
    bank_path.write_bytes(
        canonical_json_bytes(build_provider_bank(_identity(), template))
    )
    shutil.copyfile(CONSUMER_SOURCE, consumer_source)
    shutil.copyfile(AUTHORITY_SOURCE, authority_source)
    return {
        "template": template_path,
        "bank": bank_path,
        "receipt": root / "instrument_qualification_receipt.json",
        "schema": root / "runner_team_event_schema.json",
        "scratch": root / "qualification-scratch",
        "phase_ledger": root / "formal/evaluation/phases.jsonl",
        "provider_ledger": root / "formal/evaluation/provider_calls.jsonl",
        "event_ledger": root / "formal/agent_events.jsonl",
        "consumer_source": consumer_source,
        "authority_source": authority_source,
    }


def _arguments(paths: dict[str, Path]) -> dict[str, Any]:
    return {
        "identity": _identity(),
        "template_path": paths["template"],
        "bank_path": paths["bank"],
        "receipt_path": paths["receipt"],
        "formal_phase_ledger": paths["phase_ledger"],
        "formal_provider_ledger": paths["provider_ledger"],
        "formal_event_ledger": paths["event_ledger"],
        "runner_worktree": RUNNER_WORKTREE,
        "runner_python": RUNNER_PYTHON,
        "expected_runner_branch": RUNNER_BRANCH,
        "expected_runner_head": RUNNER_HEAD,
        "runner_schema_path": paths["schema"],
        "scratch_root": paths["scratch"],
        "consumer_source_path": paths["consumer_source"],
        "authority_source_path": paths["authority_source"],
    }


def _qualify(paths: dict[str, Path], **overrides: Any) -> dict[str, Any]:
    arguments = _arguments(paths)
    arguments.update(overrides)
    return _module().qualify_combined_instrument(**arguments)


def _verify(paths: dict[str, Path], **overrides: Any) -> dict[str, Any]:
    arguments = _arguments(paths)
    arguments.update(overrides)
    return _module().verify_combined_qualification_receipt(**arguments)


def test_legacy_qualification_source_remains_bound_to_e2e3_receipt() -> None:
    receipt = json.loads(E2E3_RECEIPT.read_bytes())

    assert (
        hashlib.sha256(LEGACY_QUALIFICATION_SOURCE.read_bytes()).hexdigest()
        == (receipt["source_sha256"]["instrument_qualification.py"])
    )


def test_combined_receipt_is_canonical_stable_and_write_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = _paths(tmp_path)
    request_ids: list[str] = []
    original_runner_canary = _runner_module()._run_scratch_canary

    def runner_spy(*args: Any, **kwargs: Any) -> Any:
        event = original_runner_canary(*args, **kwargs)
        request_ids.append(event["approval_request_id"])
        return event

    monkeypatch.setattr(_runner_module(), "_run_scratch_canary", runner_spy)

    first = _qualify(paths)
    first_bytes = paths["receipt"].read_bytes()
    second = _qualify(paths)

    assert first == second
    assert paths["receipt"].read_bytes() == first_bytes == canonical_json_bytes(first)
    unsigned = {key: value for key, value in first.items() if key != "receipt_sha256"}
    assert first["receipt_sha256"] == canonical_sha256(unsigned)
    assert first["runner_contract"]["checks"] == {
        "authority_binding_exact": True,
        "formal_ledgers_absent": True,
        "runner_clean": True,
        "runner_import_bound": True,
        "scratch_formal_non_alias": True,
        "schema_closed": True,
    }
    assert first["checks"]["provider_canary"] is True
    assert first["checks"]["runner_contract_canary"] is True
    assert (
        first["runner_contract"]["authority_semantic_sha256"]
        == second["runner_contract"]["authority_semantic_sha256"]
    )
    assert len(first["runner_contract"]["authority_semantic_sha256"]) == 64
    assert (
        first["runner_contract"]["source_sha256"]["runner_contract_qualification.py"]
        == hashlib.sha256(RUNNER_QUALIFICATION_SOURCE.read_bytes()).hexdigest()
    )
    assert len(request_ids) == 2
    assert request_ids[0] != request_ids[1]
    assert all(request_id.encode() not in first_bytes for request_id in request_ids)

    paths["receipt"].write_bytes(first_bytes + b" ")
    with pytest.raises(ValueError, match="INVALID_INSTRUMENT_QUALIFICATION"):
        _qualify(paths)


def test_reverification_reexecutes_both_canaries_and_exact_compares(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = _paths(tmp_path)
    expected = _qualify(paths)
    provider_calls = 0
    runner_calls = 0
    original_provider_canary = _legacy_module()._run_canary
    original_runner_canary = _runner_module()._run_scratch_canary

    def provider_spy(*args: Any, **kwargs: Any) -> Any:
        nonlocal provider_calls
        provider_calls += 1
        return original_provider_canary(*args, **kwargs)

    def runner_spy(*args: Any, **kwargs: Any) -> Any:
        nonlocal runner_calls
        runner_calls += 1
        return original_runner_canary(*args, **kwargs)

    monkeypatch.setattr(_legacy_module(), "_run_canary", provider_spy)
    monkeypatch.setattr(_runner_module(), "_run_scratch_canary", runner_spy)

    assert _verify(paths) == expected
    assert provider_calls == 1
    assert runner_calls == 1


@pytest.mark.parametrize(
    ("constant", "drifted"),
    [
        ("_CANARY_REQUEST_NOTE", "drifted request note"),
        ("_CANARY_DECISION_NOTE", "drifted approval note"),
        ("_CANARY_DECIDER", "independent-founder-delegate"),
    ],
)
def test_reverification_rejects_authority_semantic_drift_not_present_in_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    constant: str,
    drifted: str,
) -> None:
    paths = _paths(tmp_path)
    _qualify(paths)
    monkeypatch.setattr(_runner_module(), constant, drifted)

    with pytest.raises(ValueError, match="INVALID_INSTRUMENT_QUALIFICATION"):
        _verify(paths)


class _BearerDriftIdentity(SpineEvaluationIdentity):
    @property
    def provider_bearer(self) -> str:
        return super().provider_bearer + "-drift"


def _drift_bearer(paths: dict[str, Path]) -> dict[str, Any]:
    identity = _identity()
    return {
        "identity": _BearerDriftIdentity(
            sequence=identity.sequence,
            run_date=identity.run_date,
        )
    }


def _drift_bank(paths: dict[str, Path]) -> dict[str, Any]:
    bank = json.loads(paths["bank"].read_bytes())
    bank["entries"][0]["digest"] = "0" * 64
    paths["bank"].write_bytes(canonical_json_bytes(bank))
    return {}


def _drift_template(paths: dict[str, Path]) -> dict[str, Any]:
    template = json.loads(paths["template"].read_bytes())
    template["entries"][0]["request"]["messages"][0]["content"] += " drift"
    paths["template"].write_bytes(canonical_json_bytes(template))
    return {}


def _drift_schema(paths: dict[str, Path]) -> dict[str, Any]:
    schema = json.loads(paths["schema"].read_bytes())
    schema["title"] += "-drift"
    paths["schema"].write_bytes(canonical_json_bytes(schema))
    return {}


def _drift_runner(paths: dict[str, Path]) -> dict[str, Any]:
    return {"expected_runner_head": "0" * 40}


def _drift_consumer_source(paths: dict[str, Path]) -> dict[str, Any]:
    paths["consumer_source"].write_text(
        paths["consumer_source"].read_text(encoding="utf-8") + "\n# drift\n",
        encoding="utf-8",
    )
    return {}


def _drift_authority_source(paths: dict[str, Path]) -> dict[str, Any]:
    paths["authority_source"].write_text(
        paths["authority_source"].read_text(encoding="utf-8") + "\n# drift\n",
        encoding="utf-8",
    )
    return {}


@pytest.mark.parametrize(
    "drift",
    [
        _drift_bearer,
        _drift_bank,
        _drift_template,
        _drift_schema,
        _drift_runner,
        _drift_consumer_source,
        _drift_authority_source,
    ],
    ids=[
        "bearer",
        "bank",
        "template",
        "schema",
        "runner",
        "consumer-source",
        "authority-source",
    ],
)
def test_reverification_rejects_every_bound_input_drift(
    tmp_path: Path,
    drift: Callable[[dict[str, Path]], dict[str, Any]],
) -> None:
    paths = _paths(tmp_path)
    _qualify(paths)

    overrides = drift(paths)

    with pytest.raises(ValueError, match="INVALID_INSTRUMENT_QUALIFICATION"):
        _verify(paths, **overrides)


@pytest.mark.parametrize(
    "preexisting",
    ["phase_ledger", "provider_ledger", "event_ledger"],
)
def test_qualification_rejects_any_preexisting_formal_ledger_before_canaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    preexisting: str,
) -> None:
    paths = _paths(tmp_path)
    paths[preexisting].parent.mkdir(parents=True, exist_ok=True)
    paths[preexisting].write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        _legacy_module(),
        "_run_canary",
        lambda *args, **kwargs: pytest.fail("provider canary ran before genesis gate"),
    )
    monkeypatch.setattr(
        _runner_module(),
        "qualify_runner_contract",
        lambda *args, **kwargs: pytest.fail("runner canary ran before genesis gate"),
    )

    with pytest.raises(ValueError, match="INVALID_EVALUATION_GENESIS"):
        _qualify(paths)

    assert not paths["receipt"].exists()


@pytest.mark.parametrize(
    ("alias_source", "alias_target"),
    [
        ("receipt", "phase_ledger"),
        ("schema", "provider_ledger"),
        ("scratch", "event_ledger"),
    ],
)
def test_qualification_rejects_formal_path_aliases_without_output(
    tmp_path: Path,
    alias_source: str,
    alias_target: str,
) -> None:
    paths = _paths(tmp_path)
    paths[alias_source] = paths[alias_target]

    with pytest.raises(ValueError, match="INVALID_QUALIFICATION_PATHS"):
        _qualify(paths)

    assert not paths["receipt"].exists()
