from __future__ import annotations

import hashlib
from pathlib import Path

from .baselines import (
    FrozenQualificationConfig,
    SingleStoreConfig,
    SingleStoreReplayStabilityArm,
)
from .contracts import ArmBudget, stable_digest
from .fixture import EpisodeConfig, EvaluatorFixture
from .harness import EpisodeExecutor
from .scorer import HiddenScorer


QUALIFICATION_SEEDS = (1103, 1217, 1321, 1433, 1549, 1663, 1777, 1889)


def freeze_strongest_single_store(
    *,
    budget: ArmBudget,
    baseline_configs: tuple[SingleStoreConfig, ...],
    candidate_search_trials: int,
) -> FrozenQualificationConfig:
    if not baseline_configs or len(baseline_configs) != candidate_search_trials:
        raise ValueError("candidate and baseline search trials must be exactly equal")
    scored: list[tuple[float, SingleStoreConfig]] = []
    for config in baseline_configs:
        values = []
        for seed in QUALIFICATION_SEEDS:
            plan = EvaluatorFixture.build(seed, EpisodeConfig(blocks_per_phase=2))
            arm = SingleStoreReplayStabilityArm(
                config, budget, qualification_search_trials=len(baseline_configs)
            )
            result = HiddenScorer.score(plan, EpisodeExecutor().execute(plan, arm))
            values.append(
                result.metrics.quality
                + result.metrics.return_a_retention
                - result.metrics.adaptation_speed
                / max(1, result.metrics.b_changed_exposures)
            )
        scored.append((sum(values) / len(values), config))
    # Equal empirical scores remain an empirical tie; a stable config digest is
    # only a reproducibility tie-break and must not be narrated as superiority.
    scored.sort(key=lambda item: (item[0], repr(item[1])), reverse=True)
    root = Path(__file__).parent
    source_hashes = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in ("fixture.py", "harness.py", "scorer.py")
    }
    digest = stable_digest(
        "cls-f1-qualification-selection/v2",
        {
            "seeds": QUALIFICATION_SEEDS,
            "configs": [repr(config) for config in baseline_configs],
            "source_hashes": source_hashes,
        },
    )
    return FrozenQualificationConfig.freeze(
        digest, scored[0][1], search_trials=len(baseline_configs)
    )
