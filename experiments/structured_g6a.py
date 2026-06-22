"""G6a: does a structure-exploiting learned organ beat a cheap reset WHEN
structure exists? (T-P4.x.2, ADR-0017; no LLM, no spend.)

Three arms share one subject; only the belief-only organ slot differs:
  O0 none | O1 ResetScaffoldOrgan (cheap reset) | O2 RegimeLibraryOrgan (learned)
on StructuredRegimeEnv (recurring regime library = transferable structure).

  calibrate : scan O2 match params on disjoint seeds 200-204, print best.
  (no arg)  : the pre-committed r-final gate, seeds 0-9.

G6a (ADR-0017 §5): O2 < O0 AND O2 < O1 on post-shift regret area, >=7/10.
G6a MET => learned prior earns its cost given structure (escalate LLM step).
G6a NOT MET => even with structure, learning doesn't beat cheap reset (don't
spend on an LLM).

Run: PYTHONPATH=src python experiments/structured_g6a.py [calibrate]
"""

from __future__ import annotations

import itertools
import random
import sys

from aac.agent import Agent
from aac.prior_organ_library import RegimeLibraryOrgan
from aac.prior_organ_o1 import ResetScaffoldOrgan
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.structured_regime import StructuredRegimeEnv

STEPS = 2000
WINDOW = 15
N_ACTIONS = 8


def _area(seed: int, organ_factory) -> float:
    env = StructuredRegimeEnv(n_actions=N_ACTIONS, rng=random.Random(7000 + seed))
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


def calibrate() -> None:
    seeds = (200, 201, 202, 203, 204)
    grid = {"match_threshold": (0.5, 1.0, 2.0), "inject_weight": (0.7, 0.85)}
    keys = list(grid)
    print(f"G6a O2 calibration | seeds={seeds}")
    o0 = sum(_area(s, lambda: None) for s in seeds) / len(seeds)
    o1 = sum(_area(s, lambda: ResetScaffoldOrgan()) for s in seeds) / len(seeds)
    print(f"O0 {o0:.1f} | O1 {o1:.1f}")
    rows = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        p = dict(zip(keys, combo))
        m = sum(_area(s, lambda p=p: RegimeLibraryOrgan(**p)) for s in seeds) / len(
            seeds
        )
        rows.append((m, p))
        print(f"  {p} -> {m:.1f}  ({'<O1' if m < o1 else '>=O1'})")
    rows.sort(key=lambda r: r[0])
    print(f"\nFROZEN O2 params: {rows[0][1]}  (area {rows[0][0]:.1f})")


def gate() -> None:
    seeds = tuple(range(10))
    arms = {
        "O0": lambda: None,
        "O1": lambda: ResetScaffoldOrgan(),
        "O2": lambda: RegimeLibraryOrgan(),
    }
    print(f"G6a structured gate (ADR-0017) run=r-final seeds=0-9 steps={STEPS}")
    print(f"{'seed':>4} | {'O0':>9} {'O1':>9} {'O2':>9}")
    areas = {k: [] for k in arms}
    for seed in seeds:
        row = {k: _area(seed, f) for k, f in arms.items()}
        for k, v in row.items():
            areas[k].append(v)
        print(f"{seed:>4} | {row['O0']:9.1f} {row['O1']:9.1f} {row['O2']:9.1f}")
    n = len(seeds)
    o2_o0 = sum(1 for i in range(n) if areas["O2"][i] < areas["O0"][i])
    o2_o1 = sum(1 for i in range(n) if areas["O2"][i] < areas["O1"][i])
    print("\nAGGREGATE:")
    for k in arms:
        print(f"  {k}: {sum(areas[k]) / n:.1f}")
    print("\nG6a PRE-REGISTERED GATE:")
    print(f"  O2 < O0: {o2_o0}/{n} (need >=7)")
    print(f"  O2 < O1: {o2_o1}/{n} (need >=7)")
    print(f"\n  G6a: {'MET' if (o2_o0 >= 7 and o2_o1 >= 7) else 'NOT MET'}")


if __name__ == "__main__":
    (calibrate if len(sys.argv) > 1 and sys.argv[1] == "calibrate" else gate)()
