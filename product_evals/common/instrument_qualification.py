"""Pre-freeze semantic qualification for fresh SPINE instruments."""

from __future__ import annotations

import hashlib
import json
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Mapping

import product_evals.common.bank_generator as bank_generator_module
import product_evals.common.provider_bank as provider_bank_module
import product_evals.common.spine_identity as spine_identity_module
from product_evals.common.bank_generator import (
    build_provider_bank,
    canonical_json_bytes,
)
from product_evals.common.provider_bank import FrozenProviderServer
from product_evals.common.spine_identity import SpineEvaluationIdentity


def _json(path: Path) -> object:
    try:
        return json.loads(Path(path).read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON: {Path(path).name}") from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value).rstrip(b"\n")).hexdigest()


def _source_sha256() -> dict[str, str]:
    paths = {
        "bank_generator.py": Path(bank_generator_module.__file__),
        "instrument_qualification.py": Path(__file__),
        "provider_bank.py": Path(provider_bank_module.__file__),
        "spine_identity.py": Path(spine_identity_module.__file__),
    }
    return {name: _sha256(path) for name, path in paths.items()}


def _post(base_url: str, body: Mapping[str, object], bearer: str) -> tuple[int, object]:
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=canonical_json_bytes(body).rstrip(b"\n"),
        headers={
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _write_stable(path: Path, value: object) -> None:
    data = canonical_json_bytes(value)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != data:
            raise ValueError(
                "qualification receipt already exists with different bytes"
            )
        return
    destination.write_bytes(data)


def identity_bound_provider_server(
    identity: SpineEvaluationIdentity,
    bank_path: Path,
    *,
    ledger_path: Path,
    context_sha256: str,
) -> FrozenProviderServer:
    """Require a typed identity for every non-legacy replay server."""
    if not isinstance(identity, SpineEvaluationIdentity):
        raise ValueError("invalid evaluation identity")
    return FrozenProviderServer(
        bank_path,
        ledger_path=ledger_path,
        context_sha256=context_sha256,
        expected_bearer=identity.provider_bearer,
    )


def _run_canary(
    identity: SpineEvaluationIdentity,
    bank: Mapping[str, object],
    expected_bytes: bytes,
) -> None:
    entries = bank["entries"]
    with tempfile.TemporaryDirectory(prefix="spine-instrument-qual-") as raw:
        scratch = Path(raw)
        scratch_bank = scratch / "provider_responses.json"
        scratch_bank.write_bytes(expected_bytes)
        server = identity_bound_provider_server(
            identity,
            scratch_bank,
            ledger_path=scratch / "provider_calls.jsonl",
            context_sha256=identity.identity_sha256,
        )
        server.start()
        try:
            body = entries[0]["request"]
            wrong_status, wrong_payload = _post(server.base_url, body, "wrong")
            good_status, good_payload = _post(
                server.base_url, body, identity.provider_bearer
            )
            if (
                (wrong_status, wrong_payload) != (401, {"error": "UNAUTHORIZED"})
                or good_status != 200
                or good_payload != entries[0]["response"]
            ):
                raise ValueError("INVALID_PROVIDER_AUTH")
        finally:
            server.close(validate_counts=False)


def _expected_receipt(
    identity: SpineEvaluationIdentity,
    *,
    template_path: Path,
    bank_path: Path,
    bank: Mapping[str, object],
) -> dict[str, object]:
    entries = bank["entries"]
    unsigned: dict[str, object] = {
        "schema_version": identity.qualification_schema_version,
        "experiment_id": identity.experiment_id,
        "run_id": identity.run_id,
        "identity_sha256": identity.identity_sha256,
        "provider_model": identity.provider_model,
        "provider_api_key_env": identity.provider_api_key_env,
        "provider_bearer_sha256": hashlib.sha256(
            identity.provider_bearer.encode("utf-8")
        ).hexdigest(),
        "generator_version": identity.generator_version,
        "bank_schema_version": identity.bank_schema_version,
        "source_sha256": _source_sha256(),
        "template_sha256": _sha256(template_path),
        "provider_bank_sha256": _sha256(bank_path),
        "case_digests": {
            str(entry["case_id"]): str(entry["digest"]) for entry in entries
        },
        "checks": {
            "bank_byte_match": True,
            "bearer_handshake": True,
            "case_identity": True,
            "formal_ledgers_absent": True,
            "model_identity": True,
        },
    }
    return {**unsigned, "receipt_sha256": _canonical_sha256(unsigned)}


def qualify_instrument(
    identity: SpineEvaluationIdentity,
    *,
    template_path: Path,
    bank_path: Path,
    receipt_path: Path,
    formal_phase_ledger: Path,
    formal_provider_ledger: Path,
) -> dict[str, object]:
    input_paths = tuple(
        Path(path).resolve()
        for path in (
            template_path,
            bank_path,
            receipt_path,
            formal_phase_ledger,
            formal_provider_ledger,
        )
    )
    if len(set(input_paths)) != len(input_paths):
        raise ValueError("INVALID_QUALIFICATION_PATHS")
    formal_paths = (input_paths[3], input_paths[4])
    if any(path.exists() for path in formal_paths):
        raise ValueError("INVALID_EVALUATION_GENESIS")
    template = _json(template_path)
    if not isinstance(template, Mapping):
        raise ValueError("INVALID_PROVIDER_BANK")
    generated = build_provider_bank(identity, template)
    expected_bytes = canonical_json_bytes(generated)
    if Path(bank_path).read_bytes() != expected_bytes:
        raise ValueError("INVALID_PROVIDER_BANK")
    entries = generated["entries"]
    if not all(
        entry["request"]["model"]
        == entry["response"]["model"]
        == identity.provider_model
        for entry in entries
    ):
        raise ValueError("INVALID_PROVIDER_IDENTITY")
    _run_canary(identity, generated, expected_bytes)
    if any(path.exists() for path in formal_paths):
        raise ValueError("INVALID_EVALUATION_GENESIS")
    receipt = _expected_receipt(
        identity,
        template_path=Path(template_path),
        bank_path=Path(bank_path),
        bank=generated,
    )
    _write_stable(Path(receipt_path), receipt)
    if any(path.exists() for path in formal_paths):
        raise ValueError("INVALID_EVALUATION_GENESIS")
    return receipt


def verify_qualification_receipt(
    identity: SpineEvaluationIdentity,
    *,
    template_path: Path,
    bank_path: Path,
    receipt_path: Path,
) -> dict[str, object]:
    try:
        template = _json(template_path)
        receipt = _json(receipt_path)
        if not isinstance(template, Mapping) or not isinstance(receipt, dict):
            raise ValueError
        generated = build_provider_bank(identity, template)
        expected_bytes = canonical_json_bytes(generated)
        if Path(bank_path).read_bytes() != expected_bytes:
            raise ValueError
        _run_canary(identity, generated, expected_bytes)
        expected = _expected_receipt(
            identity,
            template_path=Path(template_path),
            bank_path=Path(bank_path),
            bank=generated,
        )
        if receipt != expected:
            raise ValueError
        return receipt
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValueError("INVALID_INSTRUMENT_QUALIFICATION") from exc
