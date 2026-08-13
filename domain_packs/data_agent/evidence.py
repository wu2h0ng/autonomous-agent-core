from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DataConfidenceDerivation:
    score: float
    flags: tuple[str, ...]


def derive_data_confidence(
    *,
    row_count: int,
    source_age_seconds: float | None = None,
    freshness_tau_seconds: float | None = None,
    template_verified: bool = False,
) -> DataConfidenceDerivation:
    """Derive bounded confidence without treating missing evidence as positive."""
    flags: list[str] = []
    freshness_factor = 1.0
    cap = 0.97
    if source_age_seconds is None:
        freshness_factor = 0.60
        cap = min(cap, 0.60)
        flags.append("freshness_unknown")
    elif (
        freshness_tau_seconds is not None
        and source_age_seconds > freshness_tau_seconds * 1.10
    ):
        freshness_factor = max(
            0.30,
            freshness_tau_seconds / source_age_seconds,
        )
        cap = min(cap, 0.50)
        flags.extend(("stale", "tau_inconsistency"))

    template_factor = 1.0
    if not template_verified:
        template_factor = 0.60
        cap = min(cap, 0.55)
        flags.append("unverified_template")

    if row_count <= 0:
        row_factor = 0.0
        flags.append("no_rows")
    else:
        row_factor = 0.60 + 0.40 * (min(row_count, 10) / 10)
        if row_count < 10:
            flags.append("low_row_count")

    score = 0.95 * freshness_factor * row_factor * template_factor
    if row_count <= 0:
        score = max(score, 0.30)
    else:
        score = max(score, 0.05)
    return DataConfidenceDerivation(
        score=round(min(score, cap), 6),
        flags=tuple(flags),
    )
