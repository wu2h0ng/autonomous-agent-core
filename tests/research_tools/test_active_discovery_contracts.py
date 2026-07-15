from __future__ import annotations

import pytest

from research_tools.active_discovery.contracts import (
    ContractValidationError,
    ProbeRequest,
    PublicEnvironmentDescriptor,
)


def _request_mapping() -> dict[str, object]:
    return {
        "episode_id": "episode-1",
        "arm_id": "ACTIVE_VOI",
        "step_index": 0,
        "probe_id": "probe-1",
        "operation_id": "op_a91f",
        "payload_json": '{"f_1":[]}',
        "expected_state_digest": "0" * 64,
        "cost_units": 1,
    }


def test_probe_request_rejects_unknown_fields() -> None:
    raw = _request_mapping()
    raw["hidden_version"] = "v2"

    with pytest.raises(ContractValidationError, match="unknown fields"):
        ProbeRequest.from_mapping(raw)


def test_probe_request_direct_construction_cannot_bypass_validation() -> None:
    raw = _request_mapping()
    raw["payload_json"] = '{"z":1, "a":2}'

    with pytest.raises(ContractValidationError, match="canonical JSON"):
        ProbeRequest(**raw)  # type: ignore[arg-type]


def _descriptor(
    *,
    environment_id: str = "environment-1",
    operation_id: str = "operation-1",
    schema: dict[str, object] | None = None,
    documentation_fragments: tuple[str, ...] = ("fragment-a", "fragment-b"),
    initial_state_digest: str = "1" * 64,
) -> PublicEnvironmentDescriptor:
    return PublicEnvironmentDescriptor.create(
        environment_id=environment_id,
        operation_id=operation_id,
        schema=schema or {"alpha": 1, "beta": 2},
        documentation_fragments=documentation_fragments,
        initial_state_digest=initial_state_digest,
    )


def test_descriptor_digest_is_stable_and_binds_every_descriptor_field() -> None:
    baseline = _descriptor()
    equivalent = _descriptor(schema={"beta": 2, "alpha": 1})
    variants = (
        _descriptor(environment_id="environment-2"),
        _descriptor(operation_id="operation-2"),
        _descriptor(schema={"alpha": 1, "beta": 3}),
        _descriptor(documentation_fragments=("fragment-a", "fragment-c")),
        _descriptor(initial_state_digest="2" * 64),
    )

    assert equivalent.descriptor_digest == baseline.descriptor_digest
    assert all(
        variant.descriptor_digest != baseline.descriptor_digest for variant in variants
    )
