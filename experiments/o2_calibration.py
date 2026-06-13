"""O2 adaptive-organ calibration scan (T-P4.4, ADR-0016).

Freezes O2's one free adaptation-speed constant (tau_lambda) on the SAME
disjoint calibration seeds used for O1 (200-204), without peeking at the G5
r-final seeds (0-9). rs_c and k_ref_tau are kept at the collapse-to-O1 values so
O2 still reduces to frozen O1 at the average hazard (clean G5-2 interpretation);
only the adaptation rate is tuned. Metric = post-shift regret area (lower is
faster reconvergence).

Run: PYTHONPATH=src python experiments/o2_calibration.py
"""
from __future__ import annotations

import random

from aac.agent import Agent
from aac.prior_organ_o2 import AdaptiveHazardOrgan
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.staleness import StalenessEnv

CALIB_SEEDS = (200, 201, 202, 203, 204)
STEPS = 1500
WINDOW = 15
N_ACTIONS = 8
TAU_LAMBDA_GRID = (0.15, 0.3, 0.45)


def post_shift_regret_area(seed: int, organ) -> float:
    env = StalenessEnv(n_actions=N_ACTIONS, rng=random.Random(7000 + seed))
    shell = CorrigibilityShell()
    viability = ViabilityCore(budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0)
    agent = Agent(
        n_actions=N_ACTIONS, shell=shell, rng=random.Random(8000 + seed),
        viability=viability, prior_organ=organ,
    )
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


def _mean(tau_lambda: float) -> float:
    return sum(
        post_shift_regret_area(s, AdaptiveHazardOrgan(tau_lambda=tau_lambda))
        for s in CALIB_SEEDS
    ) / len(CALIB_SEEDS)


def main() -> None:
    print(f"O2 calibration | seeds={CALIB_SEEDS} steps={STEPS} window={WINDOW}")
    rows = sorted((_mean(tl), tl) for tl in TAU_LAMBDA_GRID)
    for mean, tl in rows:
        print(f"  tau_lambda={tl}  ->  {mean:.2f}")
    best_mean, best = rows[0]
    print(f"\nFROZEN O2 tau_lambda = {best}  (area {best_mean:.2f})")
    print("Set as AdaptiveHazardOrgan.tau_lambda default and record in ADR-0016.")


if __name__ == "__main__":
    main()
