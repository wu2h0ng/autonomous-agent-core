from __future__ import annotations

import json

import pytest

from research_tools.active_discovery.canonical import canonical_json
from research_tools.active_discovery.contracts import ProbeRequest
from research_tools.active_discovery.families.opaque_cli import (
    OpaqueCliFamily,
    OpaqueCliSemantics,
    RepeatMode,
    UnknownMode,
)


def test_source_precedence_requires_an_exact_permutation_without_duplicates() -> None:
    with pytest.raises(ValueError, match="permutation"):
        OpaqueCliSemantics(
            source_precedence=(
                "sequence",
                "map_one",
                "map_two",
                "sequence",
            ),  # type: ignore[arg-type]
            repeat_mode=RepeatMode.LAST,
            unknown_mode=UnknownMode.ERROR,
            empty_is_missing=True,
            atomic_on_error=True,
        )


def _probe(family: OpaqueCliFamily) -> ProbeRequest:
    descriptor = family.public_descriptor()
    schema = json.loads(descriptor.schema_json)
    sequence_field, map_one_field, map_two_field = [
        item["field_id"] for item in schema["input_fields"]
    ]
    setting_token = schema["tokens"]["setting"]
    payload = {
        sequence_field: [f"{setting_token}=from-sequence"],
        map_one_field: {setting_token: "from-map-one"},
        map_two_field: {setting_token: "from-map-two"},
    }
    return ProbeRequest.from_mapping(
        {
            "episode_id": "episode-opaque",
            "arm_id": "QUALIFY_DEV",
            "step_index": 0,
            "probe_id": "probe-precedence",
            "operation_id": descriptor.operation_id,
            "payload_json": canonical_json(payload),
            "expected_state_digest": family.state_digest(),
            "cost_units": 1,
        }
    )


def test_opaque_cli_descriptor_hides_semantic_names_and_snapshot_replays_exactly() -> (
    None
):
    family = OpaqueCliFamily(
        seed=17,
        semantics=OpaqueCliSemantics(
            source_precedence=("map_two", "sequence", "map_one"),
            repeat_mode=RepeatMode.LAST,
            unknown_mode=UnknownMode.ERROR,
            empty_is_missing=True,
            atomic_on_error=True,
        ),
    )
    descriptor = family.public_descriptor()
    actor_semantics = canonical_json(
        {
            "operation_id": descriptor.operation_id,
            "schema_json": descriptor.schema_json,
            "documentation_fragments": descriptor.documentation_fragments,
        }
    ).lower()
    for forbidden in (
        "precedence",
        "repeat",
        "unknown",
        "argv",
        "env",
        "config",
        "atomic",
    ):
        assert forbidden not in actor_semantics

    initial = family.snapshot()
    request = _probe(family)
    first = family.execute(request)
    family.restore(initial)
    second = family.execute(request)

    assert first == second
    output = json.loads(first.output_json)
    output_field = json.loads(family.public_descriptor().schema_json)["output_field"]
    assert output[output_field] == "from-map-two"


def test_opaque_cli_unknown_input_fails_atomically() -> None:
    family = OpaqueCliFamily(
        seed=23,
        semantics=OpaqueCliSemantics(
            source_precedence=("sequence", "map_one", "map_two"),
            repeat_mode=RepeatMode.LAST,
            unknown_mode=UnknownMode.ERROR,
            empty_is_missing=False,
            atomic_on_error=True,
        ),
    )
    descriptor = family.public_descriptor()
    schema = json.loads(descriptor.schema_json)
    sequence_field, map_one_field, map_two_field = [
        item["field_id"] for item in schema["input_fields"]
    ]
    setting_token = schema["tokens"]["setting"]
    initial = family.state_digest()
    request = ProbeRequest.from_mapping(
        {
            "episode_id": "episode-opaque",
            "arm_id": "QUALIFY_DEV",
            "step_index": 0,
            "probe_id": "probe-error",
            "operation_id": descriptor.operation_id,
            "payload_json": canonical_json(
                {
                    sequence_field: [
                        f"{setting_token}=would-change",
                        "opaque-decoy=value",
                    ],
                    map_one_field: {},
                    map_two_field: {},
                }
            ),
            "expected_state_digest": initial,
            "cost_units": 1,
        }
    )

    observation = family.execute(request)

    assert observation.status_code == 2
    assert observation.before_state_digest == observation.after_state_digest == initial
