"""G9: confidence-gated policy temperature (ADR-0023) — C6-preserving subject-side gate.

Does letting a confident belief collapse the policy temperature remove the
post-shift exploration ceiling WITHOUT putting an organ in the control path?

Arms (StructuredRegimeEnv, same harness/metric as G7):
  A0 baseline policy + none | A1 + O1 cheap reset | A4 + O4 (belief-only ceiling)
  P0 gated policy + none   | P4 gated policy + O4 (belief + coupling = candidate)

  calibrate : scan {kappa, temp_floor} on disjoint seeds 700..719, print best.
  (no arg)  : the pre-committed r-final gate, seeds 0..29.

Gate (ADR-0023 S6): G9-1 mean(P4)<=(1-delta)*mean(A1); G9-2 P4<A4 >=90% & p<0.01;
G9-3 P0<A0 >=90% & p<0.05; G9-4 Wilcoxon P4 vs A1 p<0.01; C6/C7 = unit tests.

Run: PYTHONPATH=src python -m experiments.confidence_gated_g9 [calibrate]
"""

from __future__ import annotations

import itertools
import math
import random
import sys

from aac.agent import Agent
from aac.prior_organ_latent import LatentRegimeOrgan
from aac.prior_organ_o1 import ResetScaffoldOrgan
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.structured_regime import StructuredRegimeEnv

try:
    from experiments._g7_common import N_ACTIONS, STEPS, WINDOW, wilcoxon_one_sided
except ModuleNotFoundError:  # direct script execution
    from _g7_common import N_ACTIONS, STEPS, WINDOW, wilcoxon_one_sided  # type: ignore[no-redef]

CAL_SEEDS = tuple(range(700, 720))
RFINAL_SEEDS = tuple(range(30))

# FROZEN via calibrate (2026-06-14, seeds 700..719): lowest mean P4 area.
GATE_FROZEN = dict(gate_kappa=0.5, gate_temp_floor=0.1)
CALIB_O1 = 1327.8
CALIB_P4 = 899.0


def _area(
    seed: int,
    organ_factory,
    *,
    gate: bool = False,
    kappa: float = 1.0,
    temp_floor: float = 0.1,
) -> float:
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
        policy_gate=gate,
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


def _o4():
    return LatentRegimeOrgan()


def _compute_delta(calib_o1: float, calib_p4: float) -> float:
    r = 1.0 - calib_p4 / calib_o1
    return 0.20 if r >= 0.20 else math.floor(100 * 0.80 * r) / 100


def calibrate() -> None:
    seeds = CAL_SEEDS
    grid = {"gate_kappa": (0.5, 1.0, 2.0), "gate_temp_floor": (0.05, 0.1, 0.2)}
    print(f"G9 P4 calibration | seeds={seeds[0]}..{seeds[-1]}")
    o1 = sum(_area(s, lambda: ResetScaffoldOrgan()) for s in seeds) / len(seeds)
    print(f"A1 (O1 cheap reset) mean: {o1:.1f}")
    rows: list[tuple[float, dict]] = []
    for k, tf in itertools.product(grid["gate_kappa"], grid["gate_temp_floor"]):
        m = sum(_area(s, _o4, gate=True, kappa=k, temp_floor=tf) for s in seeds) / len(
            seeds
        )
        rows.append((m, {"gate_kappa": k, "gate_temp_floor": tf}))
        print(
            f"  kappa={k} temp_floor={tf} -> P4 {m:.1f}  ({'<A1' if m < o1 else '>=A1'})"
        )
    rows.sort(key=lambda r: (r[0], r[1]["gate_kappa"], r[1]["gate_temp_floor"]))
    best_area, best = rows[0]
    delta = _compute_delta(o1, best_area)
    print(f"\nFROZEN gate params: {best}")
    print(
        f"  P4 area {best_area:.1f}  A1 {o1:.1f}  reduction {1 - best_area / o1:.4f}  delta {delta}"
    )
    print(f"  (set GATE_FROZEN, CALIB_O1={o1:.1f}, CALIB_P4={best_area:.1f})")


def gate() -> None:
    seeds = RFINAL_SEEDS
    k, tf = GATE_FROZEN["gate_kappa"], GATE_FROZEN["gate_temp_floor"]
    arms = {
        "A0": lambda s: _area(s, lambda: None),
        "A1": lambda s: _area(s, lambda: ResetScaffoldOrgan()),
        "A4": lambda s: _area(s, _o4),
        "P0": lambda s: _area(s, lambda: None, gate=True, kappa=k, temp_floor=tf),
        "P4": lambda s: _area(s, _o4, gate=True, kappa=k, temp_floor=tf),
    }
    print(f"G9 confidence-gated gate (ADR-0023) run=r-final seeds=0..29 steps={STEPS}")
    print(f"{'seed':>4} | {'A0':>9} {'A1':>9} {'A4':>9} {'P0':>9} {'P4':>9}")
    areas: dict[str, list[float]] = {x: [] for x in arms}
    for seed in seeds:
        row = {x: f(seed) for x, f in arms.items()}
        for x, v in row.items():
            areas[x].append(v)
        print(f"{seed:>4} | " + " ".join(f"{row[x]:9.1f}" for x in arms))

    n = len(seeds)
    mean = {x: sum(v) / n for x, v in areas.items()}
    p4_lt_a4 = sum(1 for i in range(n) if areas["P4"][i] < areas["A4"][i])
    p0_lt_a0 = sum(1 for i in range(n) if areas["P0"][i] < areas["A0"][i])
    p4_lt_a1 = sum(1 for i in range(n) if areas["P4"][i] < areas["A1"][i])
    p_a4 = wilcoxon_one_sided([areas["A4"][i] - areas["P4"][i] for i in range(n)])
    p_a0 = wilcoxon_one_sided([areas["A0"][i] - areas["P0"][i] for i in range(n)])
    p_a1 = wilcoxon_one_sided([areas["A1"][i] - areas["P4"][i] for i in range(n)])
    delta = _compute_delta(CALIB_O1, CALIB_P4)
    need = math.ceil(0.9 * n)

    print("\nAGGREGATE:")
    for x in arms:
        print(f"  {x}: {mean[x]:.1f}")
    print(
        f"  per-seed: P4<A1 {p4_lt_a1}/{n}  P4<A4 {p4_lt_a4}/{n}  P0<A0 {p0_lt_a0}/{n}"
    )

    print("\nG9 PRE-REGISTERED GATE:")
    g1 = mean["P4"] <= (1 - delta) * mean["A1"]
    print(
        f"  G9-1 mean(P4)={mean['P4']:.1f} <= {(1 - delta) * mean['A1']:.1f}=(1-{delta})*A1: "
        f"{'PASS' if g1 else 'FAIL'}"
    )
    g2 = p4_lt_a4 >= need and p_a4 < 0.01
    print(
        f"  G9-2 P4<A4 {p4_lt_a4}/{n}(>= {need}) & Wilcoxon p={p_a4:.6f}<0.01: "
        f"{'PASS' if g2 else 'FAIL'}"
    )
    g3 = p0_lt_a0 >= need and p_a0 < 0.05
    print(
        f"  G9-3 P0<A0 {p0_lt_a0}/{n}(>= {need}) & Wilcoxon p={p_a0:.6f}<0.05: "
        f"{'PASS' if g3 else 'FAIL'}"
    )
    g4 = p_a1 < 0.01
    print(f"  G9-4 Wilcoxon P4 vs A1 p={p_a1:.6f}<0.01: {'PASS' if g4 else 'FAIL'}")
    print("  G9-C6/C7: see tests/test_confidence_gated_policy.py")

    met = g1 and g2 and g3 and g4
    print(f"\n  G9: {'MET' if met else 'NOT MET'}")
    if not met:
        if not g3:
            print(
                "\n  Confidence-gating the policy temperature adds nothing over the "
                "relevance-field schedule (P0 ~= A0) — 6th bitter-lesson occurrence."
            )
        elif not (g1 and g2):
            print(
                "\n  The post-shift ceiling is not removable by subject-side temperature "
                "control at this scale; genuine C6 relaxation stays founder-reserved (ADR-0023 S8)."
            )


if __name__ == "__main__":
    (calibrate if len(sys.argv) > 1 and sys.argv[1] == "calibrate" else gate)()
