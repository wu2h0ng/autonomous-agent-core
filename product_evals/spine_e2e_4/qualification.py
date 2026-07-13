"""Combined provider and pinned-runner qualification for the fresh successor."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from product_evals.common import instrument_qualification
from product_evals.common import runner_contract_qualification
from product_evals.common.artifacts import canonical_sha256
from product_evals.common.bank_generator import canonical_json_bytes
from product_evals.common.spine_identity import SpineEvaluationIdentity


_QUALIFICATION_ERROR = "INVALID_INSTRUMENT_QUALIFICATION"


def _resolved(path: Path) -> Path:
    return Path(path).resolve()


def _require_non_alias(
    *,
    receipt_path: Path,
    runner_schema_path: Path,
    scratch_root: Path,
    formal_paths: tuple[Path, ...],
) -> None:
    """Reject both exact aliases and scratch/formal containment aliases."""

    outputs = tuple(
        _resolved(path)
        for path in (receipt_path, runner_schema_path, scratch_root, *formal_paths)
    )
    if len(set(outputs)) != len(outputs):
        raise ValueError("INVALID_QUALIFICATION_PATHS")

    scratch = outputs[2]
    for formal in outputs[3:]:
        if scratch == formal:
            raise ValueError("INVALID_QUALIFICATION_PATHS")
        try:
            formal.relative_to(scratch)
        except ValueError:
            pass
        else:
            raise ValueError("INVALID_QUALIFICATION_PATHS")
        try:
            scratch.relative_to(formal.parent)
        except ValueError:
            pass
        else:
            raise ValueError("INVALID_QUALIFICATION_PATHS")


def _require_genesis(formal_paths: tuple[Path, ...]) -> None:
    if any(Path(path).exists() for path in formal_paths):
        raise ValueError("INVALID_EVALUATION_GENESIS")


def _read_canonical_receipt(path: Path) -> dict[str, Any]:
    try:
        raw = Path(path).read_bytes()
        value = json.loads(raw)
        if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
            raise ValueError
        unsigned = {key: item for key, item in value.items() if key != "receipt_sha256"}
        if value.get("receipt_sha256") != canonical_sha256(unsigned):
            raise ValueError
        if not isinstance(value.get("runner_contract"), dict):
            raise ValueError
        return value
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(_QUALIFICATION_ERROR) from exc


def _write_once(path: Path, value: Mapping[str, Any]) -> None:
    data = canonical_json_bytes(value)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != data:
            raise ValueError(_QUALIFICATION_ERROR)
        return
    try:
        with destination.open("xb") as output:
            output.write(data)
    except FileExistsError as exc:
        if destination.read_bytes() != data:
            raise ValueError(_QUALIFICATION_ERROR) from exc


def _qualify_provider(
    identity: SpineEvaluationIdentity,
    *,
    template_path: Path,
    bank_path: Path,
    formal_phase_ledger: Path,
    formal_provider_ledger: Path,
) -> dict[str, Any]:
    """Execute the legacy provider canary without modifying its frozen source."""

    with tempfile.TemporaryDirectory(prefix="spine-provider-qualification-") as raw:
        receipt = instrument_qualification.qualify_instrument(
            identity,
            template_path=template_path,
            bank_path=bank_path,
            receipt_path=Path(raw) / "provider_receipt.json",
            formal_phase_ledger=formal_phase_ledger,
            formal_provider_ledger=formal_provider_ledger,
        )
    return dict(receipt)


def _runner_canary_root(scratch_root: Path) -> Path:
    root = _resolved(scratch_root)
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="runner-contract-", dir=root))


def _runner_arguments(
    *,
    identity: SpineEvaluationIdentity,
    runner_worktree: Path,
    runner_python: Path,
    expected_runner_branch: str,
    expected_runner_head: str,
    runner_schema_path: Path,
    scratch_workspace: Path,
    formal_paths: tuple[Path, ...],
    consumer_source_path: Path,
    authority_source_path: Path,
) -> dict[str, Any]:
    return {
        "runner_worktree": runner_worktree,
        "runner_python": runner_python,
        "expected_branch": expected_runner_branch,
        "expected_head": expected_runner_head,
        "canary_run_id": f"{identity.run_id}-runner-contract-canary",
        "schema_path": runner_schema_path,
        "scratch_workspace": scratch_workspace,
        "formal_paths": formal_paths,
        "consumer_source_path": consumer_source_path,
        "authority_source_path": authority_source_path,
    }


def _combined_receipt(
    provider_receipt: Mapping[str, Any], runner_receipt: Mapping[str, Any]
) -> dict[str, Any]:
    provider_unsigned = {
        key: value
        for key, value in provider_receipt.items()
        if key not in {"checks", "receipt_sha256"}
    }
    provider_checks = provider_receipt.get("checks")
    if not isinstance(provider_checks, Mapping) or not all(provider_checks.values()):
        raise ValueError(_QUALIFICATION_ERROR)
    unsigned: dict[str, Any] = {
        **provider_unsigned,
        "provider_receipt_sha256": provider_receipt.get("receipt_sha256"),
        "runner_contract": dict(runner_receipt),
        "checks": {
            **dict(provider_checks),
            "provider_canary": True,
            "runner_contract_canary": True,
        },
    }
    return {**unsigned, "receipt_sha256": canonical_sha256(unsigned)}


def _paths_and_gate(
    *,
    receipt_path: Path,
    runner_schema_path: Path,
    scratch_root: Path,
    formal_phase_ledger: Path,
    formal_provider_ledger: Path,
    formal_event_ledger: Path,
) -> tuple[Path, ...]:
    formal_paths = (
        Path(formal_phase_ledger),
        Path(formal_provider_ledger),
        Path(formal_event_ledger),
    )
    _require_non_alias(
        receipt_path=receipt_path,
        runner_schema_path=runner_schema_path,
        scratch_root=scratch_root,
        formal_paths=formal_paths,
    )
    _require_genesis(formal_paths)
    return formal_paths


def qualify_combined_instrument(
    identity: SpineEvaluationIdentity,
    *,
    template_path: Path,
    bank_path: Path,
    receipt_path: Path,
    formal_phase_ledger: Path,
    formal_provider_ledger: Path,
    formal_event_ledger: Path,
    runner_worktree: Path,
    runner_python: Path,
    expected_runner_branch: str,
    expected_runner_head: str,
    runner_schema_path: Path,
    scratch_root: Path,
    consumer_source_path: Path,
    authority_source_path: Path,
) -> dict[str, Any]:
    """Qualify both live producers and write one canonical stable receipt."""

    formal_paths = _paths_and_gate(
        receipt_path=receipt_path,
        runner_schema_path=runner_schema_path,
        scratch_root=scratch_root,
        formal_phase_ledger=formal_phase_ledger,
        formal_provider_ledger=formal_provider_ledger,
        formal_event_ledger=formal_event_ledger,
    )

    existing = (
        _read_canonical_receipt(receipt_path) if Path(receipt_path).exists() else None
    )
    provider_receipt = _qualify_provider(
        identity,
        template_path=template_path,
        bank_path=bank_path,
        formal_phase_ledger=formal_phase_ledger,
        formal_provider_ledger=formal_provider_ledger,
    )
    canary_root = _runner_canary_root(scratch_root)
    try:
        runner_arguments = _runner_arguments(
            identity=identity,
            runner_worktree=runner_worktree,
            runner_python=runner_python,
            expected_runner_branch=expected_runner_branch,
            expected_runner_head=expected_runner_head,
            runner_schema_path=runner_schema_path,
            scratch_workspace=canary_root,
            formal_paths=formal_paths,
            consumer_source_path=consumer_source_path,
            authority_source_path=authority_source_path,
        )
        if existing is None:
            runner_receipt = runner_contract_qualification.qualify_runner_contract(
                **runner_arguments
            )
        else:
            runner_receipt = (
                runner_contract_qualification.verify_runner_contract_receipt(
                    expected_receipt=existing["runner_contract"], **runner_arguments
                )
            )
    finally:
        shutil.rmtree(canary_root, ignore_errors=True)

    receipt = _combined_receipt(provider_receipt, runner_receipt)
    if existing is not None and receipt != existing:
        raise ValueError(_QUALIFICATION_ERROR)
    _require_genesis(formal_paths)
    _write_once(receipt_path, receipt)
    _require_genesis(formal_paths)
    return receipt


def verify_combined_qualification_receipt(
    identity: SpineEvaluationIdentity,
    *,
    template_path: Path,
    bank_path: Path,
    receipt_path: Path,
    formal_phase_ledger: Path,
    formal_provider_ledger: Path,
    formal_event_ledger: Path,
    runner_worktree: Path,
    runner_python: Path,
    expected_runner_branch: str,
    expected_runner_head: str,
    runner_schema_path: Path,
    scratch_root: Path,
    consumer_source_path: Path,
    authority_source_path: Path,
) -> dict[str, Any]:
    """Rerun both canaries and exact-compare every bound receipt field."""

    try:
        formal_paths = _paths_and_gate(
            receipt_path=receipt_path,
            runner_schema_path=runner_schema_path,
            scratch_root=scratch_root,
            formal_phase_ledger=formal_phase_ledger,
            formal_provider_ledger=formal_provider_ledger,
            formal_event_ledger=formal_event_ledger,
        )
        expected = _read_canonical_receipt(receipt_path)
        provider_receipt = _qualify_provider(
            identity,
            template_path=template_path,
            bank_path=bank_path,
            formal_phase_ledger=formal_phase_ledger,
            formal_provider_ledger=formal_provider_ledger,
        )
        canary_root = _runner_canary_root(scratch_root)
        try:
            runner_receipt = (
                runner_contract_qualification.verify_runner_contract_receipt(
                    expected_receipt=expected["runner_contract"],
                    **_runner_arguments(
                        identity=identity,
                        runner_worktree=runner_worktree,
                        runner_python=runner_python,
                        expected_runner_branch=expected_runner_branch,
                        expected_runner_head=expected_runner_head,
                        runner_schema_path=runner_schema_path,
                        scratch_workspace=canary_root,
                        formal_paths=formal_paths,
                        consumer_source_path=consumer_source_path,
                        authority_source_path=authority_source_path,
                    ),
                )
            )
        finally:
            shutil.rmtree(canary_root, ignore_errors=True)
        observed = _combined_receipt(provider_receipt, runner_receipt)
        _require_genesis(formal_paths)
        if observed != expected:
            raise ValueError(_QUALIFICATION_ERROR)
        return expected
    except ValueError as exc:
        if str(exc) in {"INVALID_QUALIFICATION_PATHS", "INVALID_EVALUATION_GENESIS"}:
            raise
        raise ValueError(_QUALIFICATION_ERROR) from exc
    except (KeyError, OSError, TypeError) as exc:
        raise ValueError(_QUALIFICATION_ERROR) from exc
