from __future__ import annotations

import json

from research_tools.active_discovery.canonical import canonical_json
from research_tools.active_discovery.contracts import ProbeRequest
from research_tools.active_discovery.families.opaque_expiry import (
    OpaqueExpiryFamily,
    OpaqueExpirySemantics,
)
from research_tools.active_discovery.families.opaque_quota import (
    OpaqueQuotaFamily,
    OpaqueQuotaSemantics,
)
from research_tools.active_discovery.families.opaque_graph import (
    OpaqueGraphFamily,
    OpaqueGraphSemantics,
)


def _request(
    family: object,
    *,
    step_index: int,
    probe_id: str,
    payload: dict[str, object],
) -> ProbeRequest:
    descriptor = family.public_descriptor()  # type: ignore[attr-defined]
    return ProbeRequest.from_mapping(
        {
            "episode_id": "opaque-family-episode",
            "arm_id": "QUALIFY_DEV",
            "step_index": step_index,
            "probe_id": probe_id,
            "operation_id": descriptor.operation_id,
            "payload_json": canonical_json(payload),
            "expected_state_digest": family.state_digest(),  # type: ignore[attr-defined]
            "cost_units": 1,
        }
    )


def _expiry_payloads(
    family: OpaqueExpiryFamily,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    schema = json.loads(family.public_descriptor().schema_json)
    action, slot, value, steps = [item["field_id"] for item in schema["inputs"]]
    put, get, advance = schema["command_tokens"]
    return (
        {action: put, slot: "slot-a", value: "value-a", steps: 0},
        {action: get, slot: "slot-a", value: "", steps: 0},
        {action: advance, slot: "", value: "", steps: 1},
    )


def test_f2_logical_expiry_boundary_and_snapshot_replay() -> None:
    family = OpaqueExpiryFamily(
        seed=31,
        semantics=OpaqueExpirySemantics(
            lifetime_steps=2,
            refresh_on_write=True,
            expires_at_boundary=True,
        ),
    )
    put, get, advance = _expiry_payloads(family)
    output_fields = [
        item["field_id"]
        for item in json.loads(family.public_descriptor().schema_json)["outputs"]
    ]
    present_field = output_fields[0]

    family.execute(_request(family, step_index=0, probe_id="put", payload=put))
    snapshot = family.snapshot()
    first_advance = family.execute(
        _request(family, step_index=1, probe_id="advance-one", payload=advance)
    )
    family.restore(snapshot)
    replay_advance = family.execute(
        _request(family, step_index=1, probe_id="advance-one", payload=advance)
    )
    before_boundary = family.execute(
        _request(family, step_index=2, probe_id="get-one", payload=get)
    )
    family.execute(
        _request(family, step_index=3, probe_id="advance-two", payload=advance)
    )
    at_boundary = family.execute(
        _request(family, step_index=4, probe_id="get-two", payload=get)
    )

    assert first_advance == replay_advance
    assert json.loads(before_boundary.output_json)[present_field] is True
    assert json.loads(at_boundary.output_json)[present_field] is False


def _quota_payload(
    family: OpaqueQuotaFamily, *, amount: int, progress: int
) -> dict[str, object]:
    schema = json.loads(family.public_descriptor().schema_json)
    amount_field, progress_field = [item["field_id"] for item in schema["inputs"]]
    return {amount_field: amount, progress_field: progress}


def test_f3_quota_denial_refill_and_snapshot_replay() -> None:
    family = OpaqueQuotaFamily(
        seed=37,
        semantics=OpaqueQuotaSemantics(
            capacity_units=5,
            refill_per_step=2,
            refill_before_request=True,
            deny_consumes=False,
        ),
    )
    output_fields = [
        item["field_id"]
        for item in json.loads(family.public_descriptor().schema_json)["outputs"]
    ]
    accepted_field, remaining_field = output_fields

    first = family.execute(
        _request(
            family,
            step_index=0,
            probe_id="consume-four",
            payload=_quota_payload(family, amount=4, progress=0),
        )
    )
    denied = family.execute(
        _request(
            family,
            step_index=1,
            probe_id="deny-two",
            payload=_quota_payload(family, amount=2, progress=0),
        )
    )
    snapshot = family.snapshot()
    refilled = family.execute(
        _request(
            family,
            step_index=2,
            probe_id="refill-two",
            payload=_quota_payload(family, amount=2, progress=1),
        )
    )
    family.restore(snapshot)
    replay = family.execute(
        _request(
            family,
            step_index=2,
            probe_id="refill-two",
            payload=_quota_payload(family, amount=2, progress=1),
        )
    )

    assert json.loads(first.output_json) == {
        accepted_field: True,
        remaining_field: 1,
    }
    assert denied.status_code == 3
    assert json.loads(denied.output_json) == {
        accepted_field: False,
        remaining_field: 1,
    }
    assert json.loads(refilled.output_json) == {
        accepted_field: True,
        remaining_field: 1,
    }
    assert refilled == replay


def _graph_payloads(
    family: OpaqueGraphFamily,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    schema = json.loads(family.public_descriptor().schema_json)
    action, left, right = [item["field_id"] for item in schema["inputs"]]
    add, remove, query = schema["command_tokens"]
    return (
        {action: add, left: "node-a", right: "node-b"},
        {action: add, left: "node-b", right: "node-c"},
        {action: query, left: "node-a", right: "node-c"},
        {action: query, left: "node-c", right: "node-a"},
        {action: remove, left: "node-b", right: "node-c"},
    )


def test_f4_directed_multi_hop_mutation_and_snapshot_replay() -> None:
    family = OpaqueGraphFamily(
        seed=41,
        semantics=OpaqueGraphSemantics(
            directed=True,
            remove_missing_error=False,
            allow_self_loop=False,
        ),
    )
    add_ab, add_bc, query_ac, query_ca, remove_bc = _graph_payloads(family)
    reachable_field, _, hops_field = [
        item["field_id"]
        for item in json.loads(family.public_descriptor().schema_json)["outputs"]
    ]

    family.execute(_request(family, step_index=0, probe_id="add-ab", payload=add_ab))
    family.execute(_request(family, step_index=1, probe_id="add-bc", payload=add_bc))
    forward = family.execute(
        _request(family, step_index=2, probe_id="query-ac", payload=query_ac)
    )
    reverse = family.execute(
        _request(family, step_index=3, probe_id="query-ca", payload=query_ca)
    )
    snapshot = family.snapshot()
    removed = family.execute(
        _request(family, step_index=4, probe_id="remove-bc", payload=remove_bc)
    )
    after_remove = family.execute(
        _request(family, step_index=5, probe_id="query-after", payload=query_ac)
    )
    family.restore(snapshot)
    replay_remove = family.execute(
        _request(family, step_index=4, probe_id="remove-bc", payload=remove_bc)
    )

    assert json.loads(forward.output_json)[reachable_field] is True
    assert json.loads(forward.output_json)[hops_field] == 2
    assert json.loads(reverse.output_json)[reachable_field] is False
    assert json.loads(after_remove.output_json)[reachable_field] is False
    assert removed == replay_remove
