from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

import product_evals.common.instrument_qualification as qualification_module

from product_evals.common.bank_generator import (
    build_provider_bank,
    canonical_json_bytes,
)
from product_evals.common.instrument_qualification import (
    qualify_instrument,
    verify_qualification_receipt,
)
from product_evals.common.provider_bank import FrozenProviderServer, request_body_digest
from product_evals.common.spine_identity import SpineEvaluationIdentity


ROOT = Path(__file__).resolve().parents[2]
LEGACY_BANK = ROOT / "product_evals/spine_e2e_1/provider_responses.json"


def _identity() -> SpineEvaluationIdentity:
    return SpineEvaluationIdentity.create(sequence=3, run_date="20260713")


def _template() -> dict[str, object]:
    bank = json.loads(LEGACY_BANK.read_text(encoding="utf-8"))
    entries = []
    for source in bank["entries"]:
        request = deepcopy(source["request"])
        response = deepcopy(source["response"])
        request.pop("model")
        response.pop("model")
        entries.append(
            {
                "case_id": source["case_id"],
                "request": request,
                "expected_calls": source["expected_calls"],
                "response": response,
            }
        )
    return {"entries": entries}


def test_identity_derives_every_correlated_value_from_sequence_and_date() -> None:
    identity = _identity()

    assert identity.experiment_id == "SPINE-E2E-3"
    assert identity.run_id == "spine-e2e-3-20260713"
    assert identity.module_slug == "spine_e2e_3"
    assert identity.provider_model == "spine-e2e-3-frozen"
    assert identity.provider_api_key_env == "SPINE_E2E_3_PROVIDER_KEY"
    assert identity.provider_bearer == "spine-e2e-3-local-dummy"
    assert identity.bank_schema_version == "spine-e2e-3-provider-bank-v1"
    assert identity.generator_version == "spine-bank-generator-v1"
    assert len(identity.identity_sha256) == 64
    assert identity.provider_environment("http://127.0.0.1:1234/v1") == {
        "AGENT_OS_PROVIDER_BASE_URL": "http://127.0.0.1:1234/v1",
        "AGENT_OS_PROVIDER_MODEL": identity.provider_model,
        "AGENT_OS_PROVIDER_TEMPERATURE": "0",
        "AGENT_OS_PROVIDER_API_KEY_ENV": identity.provider_api_key_env,
        identity.provider_api_key_env: identity.provider_bearer,
    }


@pytest.mark.parametrize(
    ("sequence", "run_date"),
    [(0, "20260713"), (-1, "20260713"), (3, "2026-07-13"), (3, ""), (3, "20261301")],
)
def test_identity_rejects_invalid_source_values(sequence: int, run_date: str) -> None:
    with pytest.raises(ValueError):
        SpineEvaluationIdentity.create(sequence=sequence, run_date=run_date)


def test_generator_owns_models_and_digests_and_loads_under_replay_server(
    tmp_path: Path,
) -> None:
    identity = _identity()
    bank = build_provider_bank(identity, _template())
    bank_path = tmp_path / "provider_responses.json"
    bank_path.write_bytes(canonical_json_bytes(bank))

    server = FrozenProviderServer(
        bank_path,
        ledger_path=tmp_path / "provider_calls.jsonl",
        context_sha256="a" * 64,
        expected_bearer=identity.provider_bearer,
    )
    assert len(server._entries) == 12
    for entry in bank["entries"]:
        assert entry["digest"] == request_body_digest(entry["request"])
        assert entry["request"]["model"] == identity.provider_model
        assert entry["response"]["model"] == identity.provider_model


def test_generator_rejects_model_or_digest_fields_in_source_template() -> None:
    for field, value in (("model", "stale-model"), ("digest", "0" * 64)):
        template = _template()
        template["entries"][0]["request"][field] = value
        with pytest.raises(ValueError, match="template"):
            build_provider_bank(_identity(), template)


@pytest.mark.parametrize(
    "literal",
    [
        "spine-e2e-3",
        "SPINE-E2E-4",
        "spine_e2e_3",
        "SPINE_E2E_4_PROVIDER_KEY",
    ],
)
def test_generator_rejects_any_experiment_identity_literal_in_template(
    literal: str,
) -> None:
    template = _template()
    template["entries"][0]["request"]["messages"][0]["content"] += literal
    with pytest.raises(ValueError, match="stale successor identity"):
        build_provider_bank(_identity(), template)


def test_generated_bank_mutations_fail_closed(tmp_path: Path) -> None:
    identity = _identity()
    pristine = build_provider_bank(identity, _template())
    mutations = []
    stale_digest = deepcopy(pristine)
    stale_digest["entries"][0]["digest"] = "0" * 64
    mutations.append(stale_digest)
    stale_model = deepcopy(pristine)
    stale_model["entries"][0]["response"]["model"] = "spine-e2e-2-frozen"
    mutations.append(stale_model)
    duplicate_case = deepcopy(pristine)
    duplicate_case["entries"][1]["case_id"] = duplicate_case["entries"][0]["case_id"]
    mutations.append(duplicate_case)

    for index, mutated in enumerate(mutations):
        path = tmp_path / f"mutated-{index}.json"
        path.write_bytes(canonical_json_bytes(mutated))
        with pytest.raises(ValueError):
            FrozenProviderServer(
                path,
                ledger_path=tmp_path / f"ledger-{index}.jsonl",
                context_sha256="b" * 64,
                expected_bearer=identity.provider_bearer,
            )


def test_qualification_is_deterministic_and_never_writes_formal_ledgers(
    tmp_path: Path,
) -> None:
    identity = _identity()
    template_path = tmp_path / "request_template.json"
    bank_path = tmp_path / "provider_responses.json"
    receipt_a = tmp_path / "receipt-a.json"
    receipt_b = tmp_path / "receipt-b.json"
    phase_ledger = tmp_path / "formal/evaluation/phases.jsonl"
    provider_ledger = tmp_path / "formal/evaluation/provider_calls.jsonl"
    template_path.write_bytes(canonical_json_bytes(_template()))
    bank_path.write_bytes(
        canonical_json_bytes(build_provider_bank(identity, _template()))
    )

    first = qualify_instrument(
        identity,
        template_path=template_path,
        bank_path=bank_path,
        receipt_path=receipt_a,
        formal_phase_ledger=phase_ledger,
        formal_provider_ledger=provider_ledger,
    )
    second = qualify_instrument(
        identity,
        template_path=template_path,
        bank_path=bank_path,
        receipt_path=receipt_b,
        formal_phase_ledger=phase_ledger,
        formal_provider_ledger=provider_ledger,
    )

    assert first == second
    assert receipt_a.read_bytes() == receipt_b.read_bytes()
    assert first["checks"] == {
        "bank_byte_match": True,
        "bearer_handshake": True,
        "case_identity": True,
        "formal_ledgers_absent": True,
        "model_identity": True,
    }
    assert set(first["source_sha256"]) == {
        "bank_generator.py",
        "instrument_qualification.py",
        "provider_bank.py",
        "spine_identity.py",
    }
    assert all(len(value) == 64 for value in first["source_sha256"].values())
    assert (
        verify_qualification_receipt(
            identity,
            template_path=template_path,
            bank_path=bank_path,
            receipt_path=receipt_a,
        )
        == first
    )
    assert not phase_ledger.exists()
    assert not provider_ledger.exists()


def test_qualification_rejects_stale_generated_bank_before_canary(
    tmp_path: Path,
) -> None:
    identity = _identity()
    template_path = tmp_path / "request_template.json"
    bank_path = tmp_path / "provider_responses.json"
    template_path.write_bytes(canonical_json_bytes(_template()))
    stale = build_provider_bank(identity, _template())
    stale["entries"][0]["digest"] = "0" * 64
    bank_path.write_bytes(canonical_json_bytes(stale))

    with pytest.raises(ValueError, match="INVALID_PROVIDER_BANK"):
        qualify_instrument(
            identity,
            template_path=template_path,
            bank_path=bank_path,
            receipt_path=tmp_path / "receipt.json",
            formal_phase_ledger=tmp_path / "formal/phases.jsonl",
            formal_provider_ledger=tmp_path / "formal/provider_calls.jsonl",
        )


def test_receipt_verification_rejects_tampering(tmp_path: Path) -> None:
    identity = _identity()
    template_path = tmp_path / "request_template.json"
    bank_path = tmp_path / "provider_responses.json"
    receipt_path = tmp_path / "receipt.json"
    template_path.write_bytes(canonical_json_bytes(_template()))
    bank_path.write_bytes(
        canonical_json_bytes(build_provider_bank(identity, _template()))
    )
    qualify_instrument(
        identity,
        template_path=template_path,
        bank_path=bank_path,
        receipt_path=receipt_path,
        formal_phase_ledger=tmp_path / "formal/phases.jsonl",
        formal_provider_ledger=tmp_path / "formal/provider_calls.jsonl",
    )
    value = json.loads(receipt_path.read_text(encoding="utf-8"))
    value["provider_model"] = "spine-e2e-2-frozen"
    receipt_path.write_bytes(canonical_json_bytes(value))

    with pytest.raises(ValueError, match="INVALID_INSTRUMENT_QUALIFICATION"):
        verify_qualification_receipt(
            identity,
            template_path=template_path,
            bank_path=bank_path,
            receipt_path=receipt_path,
        )


def test_receipt_verification_reexecutes_the_canary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    identity = _identity()
    template_path = tmp_path / "request_template.json"
    bank_path = tmp_path / "provider_responses.json"
    receipt_path = tmp_path / "receipt.json"
    template_path.write_bytes(canonical_json_bytes(_template()))
    bank_path.write_bytes(
        canonical_json_bytes(build_provider_bank(identity, _template()))
    )
    qualify_instrument(
        identity,
        template_path=template_path,
        bank_path=bank_path,
        receipt_path=receipt_path,
        formal_phase_ledger=tmp_path / "formal/phases.jsonl",
        formal_provider_ledger=tmp_path / "formal/provider_calls.jsonl",
    )

    class BrokenServer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("canary disabled")

    monkeypatch.setattr(qualification_module, "FrozenProviderServer", BrokenServer)
    with pytest.raises(ValueError, match="INVALID_INSTRUMENT_QUALIFICATION"):
        verify_qualification_receipt(
            identity,
            template_path=template_path,
            bank_path=bank_path,
            receipt_path=receipt_path,
        )


def test_qualification_rejects_receipt_and_formal_ledger_path_alias(
    tmp_path: Path,
) -> None:
    identity = _identity()
    template_path = tmp_path / "request_template.json"
    bank_path = tmp_path / "provider_responses.json"
    aliased = tmp_path / "formal/phases.jsonl"
    template_path.write_bytes(canonical_json_bytes(_template()))
    bank_path.write_bytes(
        canonical_json_bytes(build_provider_bank(identity, _template()))
    )

    with pytest.raises(ValueError, match="INVALID_QUALIFICATION_PATHS"):
        qualify_instrument(
            identity,
            template_path=template_path,
            bank_path=bank_path,
            receipt_path=aliased,
            formal_phase_ledger=aliased,
            formal_provider_ledger=tmp_path / "formal/provider_calls.jsonl",
        )
    assert not aliased.exists()
