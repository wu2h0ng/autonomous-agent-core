from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from itertools import combinations

from .contracts import (
    DirectedAncestryHypothesis,
    DiscoveryContractError,
    InterventionDataset,
    content_digest,
)


_MICROS = 1_000_000


@dataclass(frozen=True, slots=True)
class StabilityCalibration:
    exact_null_quantile_micros: int
    max_exact_combinations: int
    minimum_effect_micros: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.exact_null_quantile_micros, bool)
            or not isinstance(self.exact_null_quantile_micros, int)
            or not 0 < self.exact_null_quantile_micros <= _MICROS
        ):
            raise DiscoveryContractError("exact null quantile must be in (0, 1]")
        if (
            isinstance(self.max_exact_combinations, bool)
            or not isinstance(self.max_exact_combinations, int)
            or self.max_exact_combinations <= 0
        ):
            raise DiscoveryContractError("exact combination cap must be positive")
        if (
            isinstance(self.minimum_effect_micros, bool)
            or not isinstance(self.minimum_effect_micros, int)
            or self.minimum_effect_micros <= 0
        ):
            raise DiscoveryContractError("minimum effect must be a positive integer")

    @property
    def digest(self) -> str:
        return content_digest(
            "intervention-stability-calibration/v1",
            {
                "exact_null_quantile_micros": self.exact_null_quantile_micros,
                "max_exact_combinations": self.max_exact_combinations,
                "minimum_effect_micros": self.minimum_effect_micros,
            },
        )


def _partition_rows(
    rows: tuple[tuple[float, ...], ...], key_index: int
) -> tuple[tuple[tuple[float, ...], ...], ...]:
    keys = tuple(row[key_index] for row in rows)
    if len(keys) != len(set(keys)):
        raise DiscoveryContractError(
            "partition covariate must uniquely identify public rows"
        )
    ordered = tuple(sorted(rows, key=lambda row: row[key_index]))
    return ordered[::2], ordered[1::2]


def _signed_standardized_shift(
    control: tuple[float, ...], treated: tuple[float, ...]
) -> float:
    if not control or not treated:
        raise DiscoveryContractError("effect calculation requires both samples")
    difference = statistics.mean(treated) - statistics.mean(control)
    scale = statistics.pstdev(control + treated)
    if scale <= 1e-12:
        return 0.0
    effect = difference / scale
    if not math.isfinite(effect):
        raise DiscoveryContractError("effect calculation produced a non-finite value")
    return effect


def _column(rows: tuple[tuple[float, ...], ...], index: int) -> tuple[float, ...]:
    return tuple(row[index] for row in rows)


def _exact_permutation_null(
    control: tuple[tuple[float, ...], ...],
    treated: tuple[tuple[float, ...], ...],
    target_index: int,
    calibration: StabilityCalibration,
) -> tuple[float, int]:
    combined = control + treated
    control_size = len(control)
    combination_count = math.comb(len(combined), control_size)
    if combination_count > calibration.max_exact_combinations:
        raise DiscoveryContractError("exact permutation space exceeds frozen cap")
    nulls: list[float] = []
    all_indices = frozenset(range(len(combined)))
    for chosen in combinations(range(len(combined)), control_size):
        control_indices = frozenset(chosen)
        pseudo_control = tuple(combined[index] for index in chosen)
        pseudo_treated = tuple(
            combined[index] for index in sorted(all_indices - control_indices)
        )
        nulls.append(
            abs(
                _signed_standardized_shift(
                    _column(pseudo_control, target_index),
                    _column(pseudo_treated, target_index),
                )
            )
        )
    ordered = sorted(nulls)
    rank = math.ceil(calibration.exact_null_quantile_micros * len(ordered) / _MICROS)
    return ordered[max(0, rank - 1)], combination_count


def discover(
    dataset: InterventionDataset,
    calibration: StabilityCalibration,
) -> tuple[DirectedAncestryHypothesis, ...]:
    accepted: list[DirectedAncestryHypothesis] = []
    minimum = calibration.minimum_effect_micros / _MICROS
    for condition in dataset.conditions:
        source_index = dataset.variable_ids.index(condition.target)
        controls = _partition_rows(dataset.control_rows, source_index)
        treated = _partition_rows(condition.rows, source_index)
        for target_index, target in enumerate(dataset.variable_ids):
            if target_index == source_index:
                continue
            half_effects = tuple(
                _signed_standardized_shift(
                    _column(controls[partition], target_index),
                    _column(treated[partition], target_index),
                )
                for partition in (0, 1)
            )
            if half_effects[0] == 0.0 or half_effects[1] == 0.0:
                continue
            if math.copysign(1.0, half_effects[0]) != math.copysign(
                1.0, half_effects[1]
            ):
                continue
            null, permutation_count = _exact_permutation_null(
                dataset.control_rows,
                condition.rows,
                target_index,
                calibration,
            )
            threshold = max(minimum, null)
            stability = min(abs(value) for value in half_effects)
            if stability <= threshold:
                continue
            pooled = _signed_standardized_shift(
                _column(dataset.control_rows, target_index),
                _column(condition.rows, target_index),
            )
            evidence = content_digest(
                "intervention-stability-evidence/v1",
                {
                    "public_view_digest": dataset.public_view_digest,
                    "calibration_digest": calibration.digest,
                    "condition_id": condition.condition_id,
                    "source": condition.target,
                    "target": target,
                    "half_effects_micros": [
                        round(value * _MICROS) for value in half_effects
                    ],
                    "pooled_effect_micros": round(pooled * _MICROS),
                    "permutation_null_micros": round(null * _MICROS),
                    "exact_permutation_count": permutation_count,
                },
            )
            accepted.append(
                DirectedAncestryHypothesis(
                    source=condition.target,
                    target=target,
                    signed_effect_micros=round(pooled * _MICROS),
                    stability_micros=round(stability * _MICROS),
                    evidence_digest=evidence,
                )
            )
    accepted.sort(
        key=lambda item: (
            -item.stability_micros,
            -abs(item.signed_effect_micros),
            item.source,
            item.target,
        )
    )
    return tuple(accepted)
