from __future__ import annotations

import math
from dataclasses import dataclass

from .baselines import FrozenQualificationConfig, SingleStoreConfig
from .contracts import OperationMeter


@dataclass(frozen=True)
class QualificationTrial:
    config: SingleStoreConfig
    score: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.score):
            raise ValueError("qualification score must be finite")


def freeze_strongest_single_store(
    *,
    qualification_seed_digest: str,
    baseline_trials: tuple[QualificationTrial, ...],
    candidate_search_trials: int,
    meter: OperationMeter,
) -> FrozenQualificationConfig:
    if not baseline_trials or len(baseline_trials) != candidate_search_trials:
        raise ValueError("candidate and baseline search trials must be exactly equal")
    for _ in baseline_trials:
        meter.search()
    best_score = max(trial.score for trial in baseline_trials)
    winners = [trial for trial in baseline_trials if trial.score == best_score]
    if len(winners) != 1:
        raise ValueError("qualification winner must be unique before freeze")
    return FrozenQualificationConfig.freeze(
        qualification_seed_digest,
        winners[0].config,
        search_trials=len(baseline_trials),
    )
