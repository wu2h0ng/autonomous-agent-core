from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from .contracts import (
    DirectedAncestryHypothesis,
    DiscoveryContractError,
    InterventionDataset,
    content_digest,
)


_MICROS = 1_000_000


@dataclass(frozen=True, slots=True)
class StabilityCalibration:
    permutation_offsets: tuple[int, ...]
    minimum_effect_micros: int

    def __post_init__(self) -> None:
        if (
            len(self.permutation_offsets) < 2
            or len(self.permutation_offsets) != len(set(self.permutation_offsets))
            or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
                   for value in self.permutation_offsets)
        ):
            raise DiscoveryContractError("permutation offsets require unique positive integers")
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
                "permutation_offsets": list(self.permutation_offsets),
                "minimum_effect_micros": self.minimum_effect_micros,
            },
        )


def _canonical_rows(rows: tuple[tuple[float, ...], ...]) -> tuple[tuple[float, ...], ...]:
    return tuple(sorted(rows))


def _halves(rows: tuple[tuple[float, ...], ...]) -> tuple[tuple[tuple[float, ...], ...], ...]:
    ordered = _canonical_rows(rows)
    return ordered[::2], ordered[1::2]


def _signed_standardized_shift(control: tuple[float, ...], treated: tuple[float, ...]) -> float:
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


def _permutation_null(
    control: tuple[tuple[float, ...], ...],
    treated: tuple[tuple[float, ...], ...],
    target_index: int,
    offsets: tuple[int, ...],
) -> float:
    combined = tuple(sorted(control + treated))
    nulls: list[float] = []
    for offset in offsets:
        pseudo_control = tuple(
            row for index, row in enumerate(combined) if (index + offset) % 4 < 2
        )
        pseudo_treated = tuple(
            row for index, row in enumerate(combined) if (index + offset) % 4 >= 2
        )
        nulls.append(
            abs(
                _signed_standardized_shift(
                    _column(pseudo_control, target_index),
                    _column(pseudo_treated, target_index),
                )
            )
        )
    return max(nulls, default=0.0)


def discover(
    dataset: InterventionDataset,
    calibration: StabilityCalibration,
) -> tuple[DirectedAncestryHypothesis, ...]:
    controls = _halves(dataset.control_rows)
    accepted: list[DirectedAncestryHypothesis] = []
    minimum = calibration.minimum_effect_micros / _MICROS
    for condition in dataset.conditions:
        treated = _halves(condition.rows)
        source_index = dataset.variable_ids.index(condition.target)
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
            if math.copysign(1.0, half_effects[0]) != math.copysign(1.0, half_effects[1]):
                continue
            null = _permutation_null(
                dataset.control_rows,
                condition.rows,
                target_index,
                calibration.permutation_offsets,
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
                    "half_effects_micros": [round(value * _MICROS) for value in half_effects],
                    "pooled_effect_micros": round(pooled * _MICROS),
                    "permutation_null_micros": round(null * _MICROS),
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
