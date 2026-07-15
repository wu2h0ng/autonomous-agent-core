from __future__ import annotations

import pytest

from research_tools.active_discovery.contracts import (
    ContractValidationError,
    ProbeRequest,
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
