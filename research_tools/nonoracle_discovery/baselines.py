from __future__ import annotations

import math
import statistics

from .contracts import (
    DirectedAncestryHypothesis,
    DiscoveryContractError,
    InterventionDataset,
    content_digest,
)


_MICROS = 1_000_000


def _column(rows: tuple[tuple[float, ...], ...], index: int) -> tuple[float, ...]:
    return tuple(row[index] for row in rows)


def _baseline_signed_standardized_shift(
    control: tuple[float, ...], treated: tuple[float, ...]
) -> float:
    if not control or not treated:
        raise DiscoveryContractError("baseline effect requires both samples")
    difference = statistics.mean(treated) - statistics.mean(control)
    scale = statistics.pstdev(control + treated)
    if scale <= 1e-12:
        return 0.0
    effect = difference / scale
    if not math.isfinite(effect):
        raise DiscoveryContractError("baseline effect produced a non-finite value")
    return effect


def _hypothesis(
    *,
    dataset: InterventionDataset,
    baseline_id: str,
    source: str,
    target: str,
    signed_effect_micros: int,
    stability_micros: int,
) -> DirectedAncestryHypothesis:
    return DirectedAncestryHypothesis(
        source=source,
        target=target,
        signed_effect_micros=signed_effect_micros,
        stability_micros=stability_micros,
        evidence_digest=content_digest(
            "nonoracle-cheap-baseline-evidence/v1",
            {
                "baseline_id": baseline_id,
                "public_view_digest": dataset.public_view_digest,
                "source": source,
                "target": target,
                "signed_effect_micros": signed_effect_micros,
                "stability_micros": stability_micros,
            },
        ),
    )


def correlation_baseline(
    dataset: InterventionDataset,
    *,
    k: int,
) -> tuple[DirectedAncestryHypothesis, ...]:
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("correlation baseline k must be a positive integer")
    candidates: list[tuple[DirectedAncestryHypothesis, str]] = []
    for source_index, source in enumerate(dataset.variable_ids):
        for target_index, target in enumerate(dataset.variable_ids):
            if source_index == target_index:
                continue
            source_values = _column(dataset.control_rows, source_index)
            target_values = _column(dataset.control_rows, target_index)
            try:
                correlation = statistics.correlation(source_values, target_values)
            except statistics.StatisticsError:
                correlation = 0.0
            hypothesis = _hypothesis(
                dataset=dataset,
                baseline_id="OBSERVATIONAL_ABS_CORRELATION_MATCHED_K",
                source=source,
                target=target,
                signed_effect_micros=round(correlation * _MICROS),
                stability_micros=round(abs(correlation) * _MICROS),
            )
            tie_key = content_digest(
                "observational-correlation-frozen-tie/v1",
                {
                    "control_rows": sorted(dataset.control_rows),
                    "source_index": source_index,
                    "target_index": target_index,
                },
            )
            candidates.append((hypothesis, tie_key))
    candidates.sort(key=lambda item: (-item[0].stability_micros, item[1]))
    return tuple(item[0] for item in candidates[: min(k, len(candidates))])


def pooled_shift_baseline(
    dataset: InterventionDataset,
    *,
    threshold_micros: int,
) -> tuple[DirectedAncestryHypothesis, ...]:
    if (
        isinstance(threshold_micros, bool)
        or not isinstance(threshold_micros, int)
        or threshold_micros <= 0
    ):
        raise ValueError("pooled shift threshold must be a positive integer")
    accepted: list[DirectedAncestryHypothesis] = []
    for condition in dataset.conditions:
        source_index = dataset.variable_ids.index(condition.target)
        for target_index, target in enumerate(dataset.variable_ids):
            if source_index == target_index:
                continue
            effect = _baseline_signed_standardized_shift(
                _column(dataset.control_rows, target_index),
                _column(condition.rows, target_index),
            )
            effect_micros = round(effect * _MICROS)
            if abs(effect_micros) < threshold_micros:
                continue
            accepted.append(
                _hypothesis(
                    dataset=dataset,
                    baseline_id="FIXED_THRESHOLD_POOLED_MEAN_SHIFT",
                    source=condition.target,
                    target=target,
                    signed_effect_micros=effect_micros,
                    stability_micros=abs(effect_micros),
                )
            )
    accepted.sort(key=lambda item: (-item.stability_micros, item.source, item.target))
    return tuple(accepted)


def finite_screen_baseline(
    dataset: InterventionDataset,
) -> tuple[DirectedAncestryHypothesis, ...]:
    values: list[DirectedAncestryHypothesis] = []
    for condition in dataset.conditions:
        for target in dataset.variable_ids:
            if target == condition.target:
                continue
            values.append(
                _hypothesis(
                    dataset=dataset,
                    baseline_id="FINITE_SCREEN_ALL_LEGAL_PAIRS",
                    source=condition.target,
                    target=target,
                    signed_effect_micros=0,
                    stability_micros=0,
                )
            )
    return tuple(values)
