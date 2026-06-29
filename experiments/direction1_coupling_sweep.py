"""Direction 1 cheap falsifier — confidence->temperature coupling vs non-stationarity rate.

NOT a mechanism, NOT a freeze, NOT a verdict. A deterministic sweep on the EXISTING
G10/P0 substrate (the confidence-gated subject-side policy, no organ), per
docs/research/route-selection-direction-1-policy-conversion-2026-06-27.md.

Question: is the OPTIMAL confidence->temperature coupling (gate_kappa, gate_temp_floor)
FLAT across non-stationarity rates, or RATE-SENSITIVE?
  - FLAT  (a single coupling is near-optimal at every rate) -> "G10/P0 is the whole story
    on this axis"; record-and-stop; Direction 1 does NOT earn an ADR.
  - RATE-SENSITIVE (the best coupling shifts systematically with the rate, and the frozen
    coupling leaves a growing gap) -> a multi-timescale coupling lever may exist;
    Direction 1 MAY earn a founder ADR (founder-reserved; not decided here).

Non-stationarity rate = 1/period (regimes shift every `period` steps). Coupling = the
frozen G9/G10 gate's (kappa, temp_floor). P0 area = post-shift regret area (lower better),
reusing the exact _area loop semantics from confidence_gated_g9.
"""
from __future__ import annotations

import random
import sys

from aac.agent import Agent
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.structured_regime import StructuredRegimeEnv

try:
    from experiments._g7_common import N_ACTIONS, STEPS, WINDOW
except ImportError:  # pragma: no cover
    from _g7_common import N_ACTIONS, STEPS, WINDOW  # type: ignore[no-redef]

FROZEN = (0.5, 0.1)  # G9/G10 GATE_FROZEN (gate_kappa, gate_temp_floor)
PERIODS = (10, 20, 40, 80, 160)  # rate = 1/period; 40 is the frozen-substrate default
KAPPAS = (0.25, 0.5, 1.0, 2.0, 4.0)
TEMP_FLOORS = (0.025, 0.05, 0.1, 0.2, 0.4)
SEEDS = tuple(range(24))


def area_at(seed: int, *, period: int, kappa: float, temp_floor: float) -> float:
    """Post-shift regret area for the P0 gated policy (no organ) at a given period+coupling.

    Exact _area loop from confidence_gated_g9, with the env period parameterized.
    """
    env = StructuredRegimeEnv(n_actions=N_ACTIONS, rng=random.Random(7000 + seed), period=period)
    shell = CorrigibilityShell()
    viability = ViabilityCore(budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0)
    agent = Agent(
        n_actions=N_ACTIONS,
        shell=shell,
        rng=random.Random(8000 + seed),
        viability=viability,
        prior_organ=None,  # P0 = no organ
        policy_gate=True,
        gate_kappa=kappa,
        gate_temp_floor=temp_floor,
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


def _mean_area(period: int, kappa: float, temp_floor: float) -> float:
    return sum(area_at(s, period=period, kappa=kappa, temp_floor=temp_floor) for s in SEEDS) / len(SEEDS)


def main() -> None:
    print(f"Direction 1 coupling falsifier | seeds={len(SEEDS)} steps={STEPS} window={WINDOW}")
    print("rate=1/period; coupling=(kappa,temp_floor); P0 post-shift area (lower=better)\n")
    print(f"{'period':>7} | {'best(kappa,tf)':>16} {'best_area':>10} | {'frozen_area':>11} {'gap%':>7}")
    best_by_period: dict[int, tuple[float, float]] = {}
    gaps: list[float] = []
    for p in PERIODS:
        rows = [((k, tf), _mean_area(p, k, tf)) for k in KAPPAS for tf in TEMP_FLOORS]
        rows.sort(key=lambda r: (r[1], r[0][0], r[0][1]))
        (bk, btf), barea = rows[0]
        frozen_area = _mean_area(p, *FROZEN)
        gap = (frozen_area - barea) / frozen_area * 100.0 if frozen_area else 0.0
        gaps.append(gap)
        best_by_period[p] = (bk, btf)
        print(f"{p:>7} | {f'({bk},{btf})':>16} {barea:>10.2f} | {frozen_area:>11.2f} {gap:>6.1f}%")

    distinct = sorted(set(best_by_period.values()))
    max_gap = max(gaps)
    print(f"\ndistinct optimal couplings across rates: {distinct}")
    print(f"max frozen-vs-best gap across rates: {max_gap:.1f}%")
    # Decision rule (pre-stated): flat if one coupling is near-optimal everywhere (frozen
    # leaves a small gap at every rate AND the optimum barely moves); rate-sensitive if the
    # optimum shifts systematically AND the frozen coupling leaves a large gap at some rate.
    FLAT_GAP_TOL = 8.0  # %
    flat = (len(distinct) == 1) or (max_gap <= FLAT_GAP_TOL)
    print(
        "\nVERDICT (cheap falsifier, NOT a verdict on Route C): "
        + (
            "FLAT -> G10/P0 is the whole story on this axis; record-and-stop; "
            "Direction 1 does NOT earn an ADR."
            if flat
            else "RATE-SENSITIVE candidate -> the optimal coupling shifts with rate and the "
            "frozen coupling leaves a large gap; Direction 1 MAY earn a founder ADR "
            "(founder-reserved; verify independently first)."
        )
    )


if __name__ == "__main__":
    main()
