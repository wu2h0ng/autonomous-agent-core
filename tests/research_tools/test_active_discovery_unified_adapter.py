from __future__ import annotations

import json
from dataclasses import asdict, replace

import pytest

from research_tools.active_discovery.canonical import canonical_json
from research_tools.active_discovery.contracts import ProbeRequest
from research_tools.active_discovery.families.manifest import FamilyCode
from research_tools.active_discovery.families.unified import (
    UnifiedAdapterError,
    UnifiedFamilyAdapter,
)


@pytest.mark.parametrize("family_code", tuple(FamilyCode))
def test_unified_adapter_binds_and_reconstructs_each_closed_family(
    family_code: FamilyCode,
) -> None:
    adapter = UnifiedFamilyAdapter.build(
        family_code=family_code,
        seed=53,
        probe_budget_units=4,
    )
    manifest = adapter.manifest

    assert manifest.mode == "NOT_EVIDENCE"
    assert manifest.family_code is family_code
    assert manifest.descriptor_digest == adapter.public_descriptor().descriptor_digest
    assert manifest.catalogue_digest == adapter.catalogue.catalogue_digest
    assert len(adapter.catalogue.candidates) >= 6
    assert {item.cost_units for item in adapter.catalogue.candidates} == {1}

    replay = UnifiedFamilyAdapter.from_manifest(manifest)
    assert replay.manifest == manifest
    assert replay.public_descriptor() == adapter.public_descriptor()
    assert replay.catalogue == adapter.catalogue


def test_unified_adapter_rejects_manifest_binding_tamper() -> None:
    adapter = UnifiedFamilyAdapter.build(
        family_code=FamilyCode.F2,
        seed=59,
        probe_budget_units=4,
    )
    tampered = replace(adapter.manifest, catalogue_digest="f" * 64)

    with pytest.raises(UnifiedAdapterError, match="manifest binding mismatch"):
        UnifiedFamilyAdapter.from_manifest(tampered)


def test_family_specific_catalogues_match_distinct_public_vocabularies() -> None:
    adapters = {
        code: UnifiedFamilyAdapter.build(
            family_code=code,
            seed=61,
            probe_budget_units=4,
        )
        for code in (FamilyCode.F2, FamilyCode.F3, FamilyCode.F4)
    }
    signatures: list[tuple[object, ...]] = []
    field_sets: list[set[str]] = []
    for adapter in adapters.values():
        schema = json.loads(adapter.public_descriptor().schema_json)
        input_ids = {item["field_id"] for item in schema["inputs"]}
        output_ids = {item["field_id"] for item in schema["outputs"]}
        field_sets.append(input_ids | output_ids)
        signatures.append(
            (
                tuple(item["shape"] for item in schema["inputs"]),
                tuple(item["shape"] for item in schema["outputs"]),
                tuple(schema.get("status_domain", ())),
                len(schema.get("command_tokens", ())),
            )
        )
        for candidate in adapter.catalogue.candidates:
            assert set(json.loads(candidate.payload_json)) == input_ids

    assert len(set(signatures)) == 3
    assert all(
        not left.intersection(right)
        for index, left in enumerate(field_sets)
        for right in field_sets[index + 1 :]
    )


@pytest.mark.parametrize("family_code", tuple(FamilyCode))
def test_actor_surface_excludes_hidden_manifest_and_semantic_vocabulary(
    family_code: FamilyCode,
) -> None:
    adapter = UnifiedFamilyAdapter.build(
        family_code=family_code,
        seed=67,
        probe_budget_units=4,
    )
    candidate = adapter.catalogue.candidates[0]
    descriptor = adapter.public_descriptor()
    observation = adapter.execute(
        ProbeRequest.from_mapping(
            {
                "episode_id": "leakage-check",
                "arm_id": "SYSTEMATIC",
                "step_index": 0,
                "probe_id": candidate.probe_id,
                "operation_id": descriptor.operation_id,
                "payload_json": candidate.payload_json,
                "expected_state_digest": adapter.state_digest(),
                "cost_units": 1,
            }
        )
    )
    actor_surface = canonical_json(
        {"descriptor": asdict(descriptor), "observation": asdict(observation)}
    ).lower()

    for forbidden in (
        "family_code",
        "manifest",
        "hidden_configuration",
        "source_precedence",
        "repeat_mode",
        "unknown_mode",
        "empty_is_missing",
        "atomic_on_error",
        "opaquecli",
        "lifetime_steps",
        "refresh_on_write",
        "expires_at_boundary",
        "capacity_units",
        "refill_per_step",
        "refill_before_request",
        "deny_consumes",
        "directed",
        "remove_missing_error",
        "allow_self_loop",
        "opaqueexpiry",
        "opaquequota",
        "opaquegraph",
    ):
        assert forbidden not in actor_surface
