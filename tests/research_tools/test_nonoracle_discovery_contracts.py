from __future__ import annotations

import math

import pytest

from research_tools.nonoracle_discovery.contracts import (
    DirectedAncestryHypothesis,
    DiscoveryContractError,
    InterventionDataset,
)


VARIABLES = ("v0", "v1", "v2")
CONTROL = (
    (0.0, 0.0, 0.0),
    (1.0, 1.0, 1.0),
    (2.0, 2.0, 2.0),
    (3.0, 3.0, 3.0),
)
DO_ROWS = {
    "condition-0": (
        (0.0, 0.0, 2.0),
        (1.0, 1.0, 3.0),
        (2.0, 2.0, 4.0),
        (3.0, 3.0, 5.0),
    )
}
BINDINGS = {"condition-0": "v0"}


def test_dataset_create_is_closed_immutable_and_digest_stable() -> None:
    first = InterventionDataset.create(VARIABLES, CONTROL, DO_ROWS, BINDINGS)
    second = InterventionDataset.create(
        VARIABLES,
        tuple(reversed(CONTROL)),
        {"condition-0": tuple(reversed(DO_ROWS["condition-0"]))},
        BINDINGS,
    )

    assert first.public_view_digest == second.public_view_digest
    assert first.condition("condition-0").target == "v0"
    with pytest.raises(TypeError):
        first.variable_ids[0] = "changed"  # type: ignore[index]


@pytest.mark.parametrize(
    ("rows", "bindings"),
    [
        (DO_ROWS, {}),
        (DO_ROWS, {"condition-0": "v0", "unknown": "v1"}),
        (
            {
                "condition-0": DO_ROWS["condition-0"],
                "condition-1": DO_ROWS["condition-0"],
            },
            {"condition-0": "v0"},
        ),
    ],
)
def test_dataset_rejects_missing_or_extra_binding(rows, bindings) -> None:
    with pytest.raises(DiscoveryContractError, match="binding"):
        InterventionDataset.create(VARIABLES, CONTROL, rows, bindings)


def test_dataset_rejects_unknown_target_and_invalid_rows() -> None:
    with pytest.raises(DiscoveryContractError, match="target"):
        InterventionDataset.create(
            VARIABLES, CONTROL, DO_ROWS, {"condition-0": "missing"}
        )
    with pytest.raises(DiscoveryContractError, match="finite"):
        InterventionDataset.create(
            VARIABLES,
            CONTROL,
            {"condition-0": ((0.0, 0.0, math.nan),) * 4},
            BINDINGS,
        )
    with pytest.raises(DiscoveryContractError, match="at least four"):
        InterventionDataset.create(VARIABLES, CONTROL[:3], DO_ROWS, BINDINGS)


def test_dataset_from_mapping_rejects_unknown_fields() -> None:
    raw = InterventionDataset.create(VARIABLES, CONTROL, DO_ROWS, BINDINGS).to_mapping()
    raw["gold_graph"] = [["v0", "v2"]]
    with pytest.raises(DiscoveryContractError, match="unknown fields"):
        InterventionDataset.from_mapping(raw)


def test_hypothesis_contract_rejects_self_edge_and_bad_digest() -> None:
    with pytest.raises(DiscoveryContractError, match="self"):
        DirectedAncestryHypothesis("v0", "v0", 1, 1, "0" * 64)
    with pytest.raises(DiscoveryContractError, match="digest"):
        DirectedAncestryHypothesis("v0", "v1", 1, 1, "not-a-digest")


def test_hypothesis_mapping_is_closed() -> None:
    item = DirectedAncestryHypothesis("v0", "v1", 2_000_000, 1_000_000, "a" * 64)
    raw = item.to_mapping()
    assert DirectedAncestryHypothesis.from_mapping(raw) == item
    with pytest.raises(DiscoveryContractError, match="unknown fields"):
        DirectedAncestryHypothesis.from_mapping({**raw, "score": 1})
