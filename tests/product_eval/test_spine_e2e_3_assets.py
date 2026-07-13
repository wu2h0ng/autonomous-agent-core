from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

from product_evals.common.bank_generator import (
    build_provider_bank,
    canonical_json_bytes,
)
from product_evals.common.instrument_qualification import qualify_instrument
from product_evals.common.provider_bank import request_body_digest
from product_evals.common.spine_identity import SpineEvaluationIdentity
from product_evals.spine_e2e_3.identity import IDENTITY


REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = REPO_ROOT / "product_evals" / "spine_e2e_3"
TEMPLATE_PATH = ASSET_ROOT / "request_template.json"
BANK_PATH = ASSET_ROOT / "provider_responses.json"
RECEIPT_PATH = ASSET_ROOT / "instrument_qualification_receipt.json"
E2E_1_BANK_PATH = (
    REPO_ROOT / "product_evals" / "spine_e2e_1" / "provider_responses.json"
)
STALE_IDENTITY = re.compile(rb"(?:spine-e2e-[12]|SPINE_E2E_[12])")
HARDCODED_SUCCESSOR = re.compile(
    rb"(?:spine-e2e-\d+|SPINE-E2E-\d+|spine_e2e_\d+|SPINE_E2E_\d+)"
)


def _load_json(path: Path) -> object:
    return json.loads(path.read_bytes())


def _identity_free_e2e_1_template() -> dict[str, object]:
    source = deepcopy(_load_json(E2E_1_BANK_PATH))
    assert isinstance(source, dict)
    entries = source["entries"]
    assert isinstance(entries, list)
    for entry in entries:
        entry.pop("digest")
        entry["request"].pop("model")
        entry["response"].pop("model")
    return source


def test_identity_is_derived_from_one_sequence_and_date() -> None:
    assert IDENTITY == SpineEvaluationIdentity.create(sequence=3, run_date="20260713")
    assert IDENTITY.experiment_id == "SPINE-E2E-3"
    assert IDENTITY.run_id == "spine-e2e-3-20260713"
    assert IDENTITY.provider_model == "spine-e2e-3-frozen"
    assert IDENTITY.provider_bearer == "spine-e2e-3-local-dummy"


def test_template_preserves_e2e_1_semantics_without_bound_identity() -> None:
    template = _load_json(TEMPLATE_PATH)

    assert template == _identity_free_e2e_1_template()
    assert isinstance(template, dict)
    entries = template["entries"]
    assert len(entries) == 12
    for entry in entries:
        assert "digest" not in entry
        assert "model" not in entry["request"]
        assert "model" not in entry["response"]


def test_checked_in_bank_is_the_canonical_deterministic_generation() -> None:
    template = _load_json(TEMPLATE_PATH)

    first = build_provider_bank(IDENTITY, template)
    second = build_provider_bank(IDENTITY, template)
    expected_bytes = canonical_json_bytes(first)

    assert first == second
    assert canonical_json_bytes(second) == expected_bytes
    assert BANK_PATH.read_bytes() == expected_bytes


def test_all_twelve_bank_digests_bind_the_generated_request_bytes() -> None:
    bank = _load_json(BANK_PATH)
    assert isinstance(bank, dict)
    entries = bank["entries"]

    assert len(entries) == 12
    assert len({entry["case_id"] for entry in entries}) == 12
    for entry in entries:
        assert entry["digest"] == request_body_digest(entry["request"])
        assert entry["request"]["model"] == IDENTITY.provider_model
        assert entry["response"]["model"] == IDENTITY.provider_model


def test_qualification_receipt_is_reproducible_without_formal_ledgers(
    tmp_path: Path,
) -> None:
    first_receipt = tmp_path / "first-receipt.json"
    second_receipt = tmp_path / "second-receipt.json"

    first = qualify_instrument(
        IDENTITY,
        template_path=TEMPLATE_PATH,
        bank_path=BANK_PATH,
        receipt_path=first_receipt,
        formal_phase_ledger=tmp_path / "formal" / "phase_ledger.jsonl",
        formal_provider_ledger=tmp_path / "formal" / "provider_ledger.jsonl",
    )
    second = qualify_instrument(
        IDENTITY,
        template_path=TEMPLATE_PATH,
        bank_path=BANK_PATH,
        receipt_path=second_receipt,
        formal_phase_ledger=tmp_path / "other-formal" / "phase_ledger.jsonl",
        formal_provider_ledger=tmp_path / "other-formal" / "provider_ledger.jsonl",
    )

    assert first == second
    assert first_receipt.read_bytes() == second_receipt.read_bytes()
    assert RECEIPT_PATH.read_bytes() == first_receipt.read_bytes()
    assert (
        first["provider_bank_sha256"]
        == hashlib.sha256(BANK_PATH.read_bytes()).hexdigest()
    )
    assert set(first["source_sha256"]) == {
        "bank_generator.py",
        "instrument_qualification.py",
        "provider_bank.py",
        "spine_identity.py",
    }
    assert first["checks"] == {
        "bank_byte_match": True,
        "bearer_handshake": True,
        "case_identity": True,
        "formal_ledgers_absent": True,
        "model_identity": True,
    }


def test_e2e_3_assets_contain_no_stale_successor_identity_literal() -> None:
    checked = [
        path
        for path in ASSET_ROOT.iterdir()
        if path.is_file() and path.suffix in {".py", ".json"}
    ]

    assert {
        "__init__.py",
        "identity.py",
        "instrument_qualification_receipt.json",
        "provider_responses.json",
        "request_template.json",
    } <= {path.name for path in checked}
    for path in checked:
        assert STALE_IDENTITY.search(path.read_bytes()) is None, path


def test_successor_python_uses_identity_derivation_not_numbered_literals() -> None:
    for path in ASSET_ROOT.glob("*.py"):
        assert HARDCODED_SUCCESSOR.search(path.read_bytes()) is None, path
