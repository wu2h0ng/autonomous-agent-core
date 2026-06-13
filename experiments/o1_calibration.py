"""O1 reset-scaffold calibration scan (T-P4.2, ADR-0016).

Picks O1's parameters on CALIBRATION seeds (disjoint from G5's 0-9), so the
frozen O1 is a strong baseline rather than a strawman, without peeking at the
G5 r-final seeds. The metric is post-shift regret area (lower = faster
reconvergence). The winning param set is then FROZEN as ResetScaffoldOrgan's
defaults; do not retune after seeing G5.

Run: PYTHONPATH=src python experiments/o1_calibration.py
"""
from __future__ import annotations

import itertools
import random

from aac.agent import Agent
from aac.prior_organ_o1 import ResetScaffoldOrgan
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.staleness import StalenessEnv

CALIB_SEEDS = (200, 201, 202, 203, 204)
STEPS = 1500
WINDOW = 15
N_ACTIONS = 8

GRID = {
    "spike_k": (1.5, 2.5),
    "reset_strength": (0.5, 1.0),
    "mu_decay": (0.3, 0.6),
}


def _subject(seed: int, organ) -> tuple[Agent, StalenessEnv]:
    env = StalenessEnv(n_actions=N_ACTIONS, rng=random.Random(7000 + seed))
    shell = CorrigibilityShell()
    # Survival is irrelevant here; we measure staleness regret, so the subject
    # never starves (metabolic_cost 0, huge budget).
    viability = ViabilityCore(budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0)
    agent = Agent(
        n_actions=N_ACTIONS,
        shell=shell,
        rng=random.Random(8000 + seed),
        viability=viability,
        prior_organ=organ,
    )
    return agent, env


def post_shift_regret_area(seed: int, organ) -> float:
    agent, env = _subject(seed, organ)
    area = 0.0
    window_left = 0
    for _ in range(STEPS):
        agent.step(env)
        if env.just_shifted:
            window_left = WINDOW
        if window_left > 0:
            area += env.last_regret
            window_left -= 1
    return area


def _mean_area(organ_factory) -> float:
    return sum(
        post_shift_regret_area(seed, organ_factory()) for seed in CALIB_SEEDS
    ) / len(CALIB_SEEDS)


def main() -> None:
    print(f"O1 calibration | seeds={CALIB_SEEDS} steps={STEPS} window={WINDOW}")
    o0 = _mean_area(lambda: None)
    print(f"O0 (no organ) mean post-shift regret area: {o0:.2f}\n")

    rows = []
    keys = list(GRID)
    for combo in itertools.product(*(GRID[k] for k in keys)):
        params = dict(zip(keys, combo))
        mean = _mean_area(lambda p=params: ResetScaffoldOrgan(**p))
        rows.append((mean, params))
        print(f"  {params}  ->  {mean:.2f}  ({'beats O0' if mean < o0 else 'NOT < O0'})")

    rows.sort(key=lambda r: r[0])
    best_mean, best = rows[0]
    print(f"\nFROZEN O1 params: {best}  (area {best_mean:.2f}, O0 {o0:.2f}, "
          f"delta {o0 - best_mean:+.2f})")
    print("Set these as ResetScaffoldOrgan defaults and record in ADR-0016.")


if __name__ == "__main__":
    main()
