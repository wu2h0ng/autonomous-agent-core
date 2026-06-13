"""G8: does an O2+O4 belief ensemble beat both, decisively over the cheap reset?
(ADR-0022; no LLM, no spend, no new runtime dependency.)

Four arms share one subject; only the belief-only organ slot differs:
  O1 ResetScaffoldOrgan | O2 RegimeLibraryOrgan | O4 LatentRegimeOrgan
  | O5 EnsembleRegimeOrgan
on StructuredRegimeEnv (recurring regime library = transferable structure).

  calibrate : scan O5 params on disjoint seeds 500..519, print best.
  (no arg)  : the pre-committed r-final gate, seeds 600..629.

Gate criteria (ADR-0022 S4):
  G8-1  mean(O5) <= (1 - delta) * mean(O1)
  G8-2  O5 < O2 on >= 90% seeds
  G8-3  mean(O5) < mean(O4) AND Wilcoxon one-sided O5 vs O4 p < 0.05
  G8-4  Wilcoxon one-sided O5 vs O1 AND O5 vs O2 both p < 0.01
  G8-C6 organ-not-subject (unit tests)
  G8-C7 corrigibility undiminished (unit tests)

Run: PYTHONPATH=src python -m experiments.ensemble_regime_g8 [calibrate]
(G8 shares experiments/_g7_common and imports as a package, so run with -m.)
"""
from __future__ import annotations

import itertools
import math
import sys

from aac.prior_organ_ensemble import EnsembleRegimeOrgan
from aac.prior_organ_latent import LatentRegimeOrgan
from aac.prior_organ_library import RegimeLibraryOrgan
from aac.prior_organ_o1 import ResetScaffoldOrgan

try:
    from experiments._g7_common import STEPS, run_area, wilcoxon_one_sided
except ModuleNotFoundError:  # direct script execution: python experiments/...
    from _g7_common import STEPS, run_area, wilcoxon_one_sided  # type: ignore[no-redef]

CAL_SEEDS = tuple(range(500, 520))
RFINAL_SEEDS = tuple(range(600, 630))

# FROZEN via calibrate (2026-06-14, seeds 500..519); lowest mean O5 area.
O5_FROZEN = dict(delta_cap=2.0, o2_weight=0.5, o4_weight=1.0)
# Calibration anchors for the G8-1 delta target (frozen with the params above).
CALIB_O1 = 1247.8
CALIB_O5 = 1138.0


def _compute_delta(calib_o1: float, calib_o5: float) -> float:
    calib_reduction = 1.0 - calib_o5 / calib_o1
    if calib_reduction >= 0.20:
        return 0.20
    return math.floor(100 * 0.80 * calib_reduction) / 100


def calibrate() -> None:
    seeds = CAL_SEEDS
    grid = {
        "delta_cap": (1.5, 2.0, 3.0),
        "o2_weight": (0.5, 1.0),
        "o4_weight": (0.5, 1.0),
    }
    keys = list(grid)
    print(f"G8 O5 calibration | seeds={seeds[0]}..{seeds[-1]}")

    o1_areas = [run_area(s, lambda: ResetScaffoldOrgan()) for s in seeds]
    o1_mean = sum(o1_areas) / len(seeds)
    print(f"O1 mean: {o1_mean:.1f}")

    rows: list[tuple[float, dict]] = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        p = dict(zip(keys, combo))
        areas = [run_area(s, lambda p=p: EnsembleRegimeOrgan(**p)) for s in seeds]
        m = sum(areas) / len(seeds)
        rows.append((m, p))
        tag = "<O1" if m < o1_mean else ">=O1"
        print(f"  {p} -> {m:.1f}  ({tag})")

    rows.sort(key=lambda r: (r[0], tuple(r[1][k] for k in keys)))
    best_area, best_params = rows[0]
    calib_reduction = 1.0 - best_area / o1_mean
    delta = _compute_delta(o1_mean, best_area)
    print(f"\nFROZEN O5 params: {best_params}")
    print(f"  area: {best_area:.1f}  O1: {o1_mean:.1f}")
    print(f"  calib_reduction: {calib_reduction:.4f}")
    print(f"  delta target: {delta}")
    print(f"  (set O5_FROZEN, CALIB_O1={o1_mean:.1f}, CALIB_O5={best_area:.1f})")


def gate() -> None:
    seeds = RFINAL_SEEDS
    arms = {
        "O1": lambda: ResetScaffoldOrgan(),
        "O2": lambda: RegimeLibraryOrgan(),
        "O4": lambda: LatentRegimeOrgan(),
        "O5": lambda: EnsembleRegimeOrgan(**O5_FROZEN),
    }
    print(
        f"G8 ensemble gate (ADR-0022) run=r-final "
        f"seeds={seeds[0]}..{seeds[-1]} steps={STEPS}"
    )
    print(f"{'seed':>4} | {'O1':>9} {'O2':>9} {'O4':>9} {'O5':>9}")

    areas: dict[str, list[float]] = {k: [] for k in arms}
    for seed in seeds:
        row = {k: run_area(seed, f) for k, f in arms.items()}
        for k, v in row.items():
            areas[k].append(v)
        print(
            f"{seed:>4} | {row['O1']:9.1f} {row['O2']:9.1f} "
            f"{row['O4']:9.1f} {row['O5']:9.1f}"
        )

    n = len(seeds)
    means = {k: sum(v) / n for k, v in areas.items()}
    o5_vs_o2_wins = sum(1 for i in range(n) if areas["O5"][i] < areas["O2"][i])
    o5_vs_o4_wins = sum(1 for i in range(n) if areas["O5"][i] < areas["O4"][i])
    o5_vs_o1_wins = sum(1 for i in range(n) if areas["O5"][i] < areas["O1"][i])

    p_o1 = wilcoxon_one_sided([areas["O1"][i] - areas["O5"][i] for i in range(n)])
    p_o2 = wilcoxon_one_sided([areas["O2"][i] - areas["O5"][i] for i in range(n)])
    p_o4 = wilcoxon_one_sided([areas["O4"][i] - areas["O5"][i] for i in range(n)])

    delta = _compute_delta(CALIB_O1, CALIB_O5)

    print("\nAGGREGATE:")
    for k in arms:
        print(f"  {k}: {means[k]:.1f}")
    print(
        f"  per-seed: O5<O1 {o5_vs_o1_wins}/{n}  "
        f"O5<O2 {o5_vs_o2_wins}/{n}  O5<O4 {o5_vs_o4_wins}/{n}"
    )

    print("\nG8 PRE-REGISTERED GATE:")
    g8_1 = means["O5"] <= (1 - delta) * means["O1"]
    print(f"  G8-1 mean(O5)={means['O5']:.1f} <= "
          f"{(1 - delta) * means['O1']:.1f}=(1-{delta})*mean(O1): "
          f"{'PASS' if g8_1 else 'FAIL'}")

    need = math.ceil(0.9 * n)
    g8_2 = o5_vs_o2_wins >= need
    print(f"  G8-2 O5<O2 {o5_vs_o2_wins}/{n} (need >={need}): "
          f"{'PASS' if g8_2 else 'FAIL'}")

    g8_3 = means["O5"] < means["O4"] and p_o4 < 0.05
    print(f"  G8-3 mean(O5)<mean(O4) and Wilcoxon O5vsO4 p={p_o4:.6f}<0.05: "
          f"{'PASS' if g8_3 else 'FAIL'}")

    g8_4 = p_o1 < 0.01 and p_o2 < 0.01
    print(f"  G8-4 Wilcoxon O5vsO1 p={p_o1:.6f} and O5vsO2 p={p_o2:.6f} both<0.01: "
          f"{'PASS' if g8_4 else 'FAIL'}")

    print("  G8-C6 organ-not-subject: see unit tests")
    print("  G8-C7 corrigibility: see unit tests")

    all_pass = g8_1 and g8_2 and g8_3 and g8_4
    print(f"\n  G8: {'MET' if all_pass else 'NOT MET'}")


if __name__ == "__main__":
    (calibrate if len(sys.argv) > 1 and sys.argv[1] == "calibrate" else gate)()
