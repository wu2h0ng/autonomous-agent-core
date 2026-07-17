from __future__ import annotations

import inspect

from research_tools.nonoracle_discovery.contracts import InterventionDataset
from research_tools.nonoracle_discovery.mechanism import (
    StabilityCalibration,
    discover,
)


def _dataset() -> InterventionDataset:
    control = tuple((float(index), float(index % 2), 0.0) for index in range(8))
    stable = tuple((float(index), float(index % 2), 4.0 + 0.1 * (index % 2)) for index in range(8))
    unstable = tuple(
        (float(index), float(index % 2), 5.0 if index % 2 == 0 else 0.0)
        for index in range(8)
    )
    return InterventionDataset.create(
        ("v0", "v1", "v2"),
        control,
        {"do-v0": stable, "do-v1": unstable},
        {"do-v0": "v0", "do-v1": "v1"},
    )


def _calibration() -> StabilityCalibration:
    return StabilityCalibration(permutation_offsets=(1, 3, 5), minimum_effect_micros=500_000)


def test_stability_keeps_consistent_effect_and_rejects_one_partition_artifact() -> None:
    found = discover(_dataset(), _calibration())
    pairs = {(item.source, item.target) for item in found}

    assert ("v0", "v2") in pairs
    assert ("v1", "v2") not in pairs


def test_row_and_condition_order_do_not_change_output() -> None:
    dataset = _dataset()
    reordered = InterventionDataset.create(
        tuple(dataset.variable_ids),
        tuple(reversed(dataset.control_rows)),
        {
            condition.condition_id: tuple(reversed(condition.rows))
            for condition in reversed(dataset.conditions)
        },
        {condition.condition_id: condition.target for condition in reversed(dataset.conditions)},
    )

    assert discover(dataset, _calibration()) == discover(reordered, _calibration())


def test_output_is_ranked_and_bound_to_public_evidence() -> None:
    found = discover(_dataset(), _calibration())

    assert found
    assert [item.stability_micros for item in found] == sorted(
        (item.stability_micros for item in found), reverse=True
    )
    assert all(item.evidence_digest != _dataset().public_view_digest for item in found)


def test_mechanism_api_has_no_gold_or_scorer_parameter() -> None:
    assert tuple(inspect.signature(discover).parameters) == ("dataset", "calibration")


def test_calibration_digest_depends_on_offsets_and_floor() -> None:
    first = _calibration()
    second = StabilityCalibration(permutation_offsets=(1, 3, 7), minimum_effect_micros=500_000)
    third = StabilityCalibration(permutation_offsets=(1, 3, 5), minimum_effect_micros=600_000)

    assert first.digest != second.digest
    assert first.digest != third.digest
