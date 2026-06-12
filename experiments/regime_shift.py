"""Falsification measurement for claim 2 (relevance realization / re-framing).

Goldilocks design: both agents reliably survive the baseline, so the
discriminator is NOT survival but EFFICIENCY under non-stationarity —
cumulative regret (reward left on the table vs the best action) and recovery
time after each regime change. A relevance-modulated agent should re-frame
faster (lower post-shift recovery) and exploit harder when settled (lower
overall regret) than a fixed-explore ablation.

Reported measurement, not a unit test. If the modulated agent does not beat the
ablation here, RR-0001's Phase 0 gate is NOT met and the v0 relevance control
law returns to the bench (do not tune the mechanism to pass — diagnose it).

Run: PYTHONPATH=src python experiments/regime_shift.py
"""

from __future__ import annotations

import random

from aac.agent import Agent
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.survival import GridlessSurvival


def run(modulate: bool, seed: int = 0, max_steps: int = 1000, n_actions: int = 6) -> dict:
    rng = random.Random(seed)
    env = GridlessSurvival(
        n_actions=n_actions, rng=rng, regime_period=50,
        noise=0.3, reward_low=-1.0, reward_high=4.0,
    )
    shell = CorrigibilityShell()
    core = ViabilityCore(budget=60.0, metabolic_cost=1.0, capacity=100.0, safe_budget=50.0)
    agent = Agent(
        n_actions=n_actions, shell=shell, rng=rng,
        modulate_relevance=modulate, viability=core,
    )

    survived = 0
    regret_sum = 0.0
    last_regime = env.regime_index
    recovery: list[int] = []
    since_shift: int | None = None
    for _ in range(max_steps):
        rec = agent.step(env)
        if rec is None:
            break
        survived += 1
        regret_sum += env.last_regret
        if env.regime_index != last_regime:
            last_regime = env.regime_index
            since_shift = 0
        elif since_shift is not None:
            since_shift += 1
            if agent.model.best_action() == env.best_action:
                recovery.append(since_shift)
                since_shift = None
    return {
        "steps": survived,
        "regret_per_step": round(regret_sum / max(1, survived), 3),
        "mean_recovery": round(sum(recovery) / max(1, len(recovery)), 2),
        "recoveries": len(recovery),
    }


def main() -> None:
    seeds = list(range(10))
    mod_regret = abl_regret = 0.0
    mod_recov = abl_recov = 0.0
    mod_better = 0
    print(f"{'seed':>4}  {'modulated steps/regret/recov':>30}  {'ablation steps/regret/recov':>30}")
    for seed in seeds:
        m = run(True, seed=seed)
        a = run(False, seed=seed)
        mod_regret += m["regret_per_step"]
        abl_regret += a["regret_per_step"]
        mod_recov += m["mean_recovery"]
        abl_recov += a["mean_recovery"]
        mod_better += int(m["regret_per_step"] < a["regret_per_step"])
        print(
            f"{seed:>4}  {m['steps']:>6d} /{m['regret_per_step']:>7.3f} /{m['mean_recovery']:>6.2f}"
            f"   {a['steps']:>6d} /{a['regret_per_step']:>7.3f} /{a['mean_recovery']:>6.2f}"
        )
    n = len(seeds)
    print(
        f"\nmean regret/step  modulated={mod_regret / n:.3f}  ablation={abl_regret / n:.3f}"
        f"   |  mean recovery  modulated={mod_recov / n:.2f}  ablation={abl_recov / n:.2f}"
        f"   |  modulated lower-regret in {mod_better}/{n} seeds"
    )
    verdict = "MET" if mod_regret < abl_regret and mod_better >= 7 else "NOT MET"
    print(f"Phase-0 gate (modulated beats ablation on regret): {verdict}")


if __name__ == "__main__":
    main()
