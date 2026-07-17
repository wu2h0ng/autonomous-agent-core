from __future__ import annotations

import inspect

from research_tools.nonoracle_discovery.contracts import InterventionDataset
from research_tools.nonoracle_discovery.mechanism import (
    StabilityCalibration,
    _exact_permutation_null,
    _partition_rows,
    discover,
)


def _dataset() -> InterventionDataset:
    control = tuple((float(index), float(index), 0.0) for index in range(8))
    stable = tuple((float(index), float(index), 4.0 + 0.1 * (index % 2)) for index in range(8))
    unstable = tuple(
        (float(index), float(index), 5.0 if index % 2 == 0 else 0.0)
        for index in range(8)
    )
    return InterventionDataset.create(
        ("v0", "v1", "v2"),
        control,
        {"do-v0": stable, "do-v1": unstable},
        {"do-v0": "v0", "do-v1": "v1"},
    )


def _calibration() -> StabilityCalibration:
    return StabilityCalibration(
        exact_null_quantile_micros=950_000,
        max_exact_combinations=20_000,
        minimum_effect_micros=500_000,
    )


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


def test_partition_membership_uses_source_covariate_not_outcome_rank() -> None:
    rows = (
        (0.0, 0.0, 100.0),
        (1.0, 0.0, -100.0),
        (2.0, 0.0, 50.0),
        (3.0, 0.0, -50.0),
    )
    outcome_rank_reversed = tuple((row[0], row[1], -row[2]) for row in reversed(rows))

    first = _partition_rows(rows, key_index=0)
    second = _partition_rows(outcome_rank_reversed, key_index=0)

    assert tuple(tuple(row[0] for row in half) for half in first) == tuple(
        tuple(row[0] for row in half) for half in second
    )


def test_exact_permutation_null_enumerates_distinct_exchangeable_labelings() -> None:
    control = ((0.0, 0.0), (1.0, 1.0))
    treated = ((2.0, 2.0), (3.0, 3.0))

    first_threshold, first_count = _exact_permutation_null(
        control, treated, target_index=1, calibration=_calibration()
    )
    second_threshold, second_count = _exact_permutation_null(
        treated, control, target_index=1, calibration=_calibration()
    )

    assert first_count == 6
    assert second_count == 6
    assert first_threshold == second_threshold


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
    second = StabilityCalibration(
        exact_null_quantile_micros=900_000,
        max_exact_combinations=20_000,
        minimum_effect_micros=500_000,
    )
    third = StabilityCalibration(
        exact_null_quantile_micros=950_000,
        max_exact_combinations=20_000,
        minimum_effect_micros=600_000,
    )

    assert first.digest != second.digest
    assert first.digest != third.digest
