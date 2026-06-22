"""G5 falsification experiment for the P4 prior organ (T-P4.4, ADR-0016).

Run:
    PYTHONPATH=src python experiments/prior_organ_g5.py

This is the pre-committed r-final gate run. Do not tune the organs, the
environment, or the criteria after seeing results.

Three arms share the SAME subject (viability + policy + shell); only the organ
slot differs, and all are measured by the identical post-shift regret area here:
  O0  no organ
  O1  ResetScaffoldOrgan (deterministic faster-reset, calibration-frozen)
  O2  AdaptiveHazardOrgan (learned hazard-adaptive reset, calibration-frozen)

Statistical criteria (ADR-0016 §4):
  G5-1  O2 post-shift regret area < O0 in >=7/10 seeds (organ gain is real).
  G5-2  O2 < O1 in >=7/10 seeds (learning necessity; the bitter-lesson guard —
        O1~=O2 means "faster reset suffices, learned priors unnecessary").
The structural criteria G5-3 (organ-not-subject, C6) and G5-4 (corrigibility
unweakened, C7) are deterministic unit tests in tests/test_g5_guards.py, not
statistics; G5 MET requires all four.
"""

from __future__ import annotations

import random

from aac.agent import Agent
from aac.prior_organ_o1 import ResetScaffoldOrgan
from aac.prior_organ_o2 import AdaptiveHazardOrgan
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.staleness import StalenessEnv

RUN_LABEL = "r-final"
SEEDS = tuple(range(10))
STEPS = 1500
WINDOW = 15
N_ACTIONS = 8


def _post_shift_area(seed: int, organ_factory) -> float:
    env = StalenessEnv(n_actions=N_ACTIONS, rng=random.Random(7000 + seed))
    shell = CorrigibilityShell()
    viability = ViabilityCore(
        budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0
    )
    agent = Agent(
        n_actions=N_ACTIONS,
        shell=shell,
        rng=random.Random(8000 + seed),
        viability=viability,
        prior_organ=organ_factory(),
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


def main() -> None:
    arms = {
        "O0": lambda: None,
        "O1": lambda: ResetScaffoldOrgan(),
        "O2": lambda: AdaptiveHazardOrgan(),
    }
    print(
        f"G5 prior-organ gate (ADR-0016, T-P4.4) run={RUN_LABEL} "
        f"seeds={SEEDS[0]}-{SEEDS[-1]} steps={STEPS} window={WINDOW}"
    )
    print(f"{'seed':>4} | {'O0':>9} {'O1':>9} {'O2':>9}")
    areas = {name: [] for name in arms}
    for seed in SEEDS:
        row = {name: _post_shift_area(seed, f) for name, f in arms.items()}
        for name, a in row.items():
            areas[name].append(a)
        print(f"{seed:>4} | {row['O0']:9.2f} {row['O1']:9.2f} {row['O2']:9.2f}")

    n = len(SEEDS)
    o2_beats_o0 = sum(1 for i in range(n) if areas["O2"][i] < areas["O0"][i])
    o2_beats_o1 = sum(1 for i in range(n) if areas["O2"][i] < areas["O1"][i])
    o1_beats_o0 = sum(1 for i in range(n) if areas["O1"][i] < areas["O0"][i])

    print("\nAGGREGATE (mean post-shift regret area, lower=better):")
    for name in arms:
        print(f"  {name}: {sum(areas[name]) / n:.2f}")
    print(f"  (context) O1 beats O0 in {o1_beats_o0}/{n} seeds")

    print("\nG5 PRE-REGISTERED GATE:")
    print(f"  G5-1 O2 < O0 (organ gain real):       {o2_beats_o0}/{n} (need >=7)")
    print(f"  G5-2 O2 < O1 (learning necessity):    {o2_beats_o1}/{n} (need >=7)")
    print("  G5-3 organ-not-subject (C6):          see tests/test_g5_guards.py")
    print("  G5-4 corrigibility unweakened (C7):   see tests/test_g5_guards.py")
    stat_met = o2_beats_o0 >= 7 and o2_beats_o1 >= 7
    print(
        f"\n  G5 (statistical G5-1 & G5-2): {'MET' if stat_met else 'NOT MET'}"
        " (final MET also requires G5-3 & G5-4 tests green)"
    )


if __name__ == "__main__":
    main()
