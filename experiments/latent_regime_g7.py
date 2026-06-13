"""G7: does Bayesian latent-regime tracking beat the cheap reset decisively?
(T-P4.x, ADR-0020; no LLM, no spend, no new runtime dependency.)

Four arms share one subject; only the belief-only organ slot differs:
  O0 none | O1 ResetScaffoldOrgan | O2 RegimeLibraryOrgan | O4 LatentRegimeOrgan
on StructuredRegimeEnv (recurring regime library = transferable structure).

  calibrate : scan O4 params on disjoint seeds 200..219, print best.
  (no arg)  : the pre-committed r-final gate, seeds 0..29.

Gate criteria (ADR-0020 S4):
  G7-1  mean(O4) <= (1 - delta) * mean(O1)
  G7-2  O4 < O2 on >= 90% seeds
  G7-3  O4 < O1 on >= 29/30 seeds
  G7-4  paired one-sided Wilcoxon, O4 vs O1, p < 0.01
  G7-C6 organ-not-subject (unit tests)
  G7-C7 corrigibility undiminished (unit tests)

Run: PYTHONPATH=src python -m experiments.latent_regime_g7 [calibrate]
(G7-family scripts share experiments/_g7_common and import as a package, so they
must be run with -m, not as a bare path.)
"""
from __future__ import annotations

import itertools
import math
import sys

from aac.prior_organ_latent import LatentRegimeOrgan
from aac.prior_organ_library import RegimeLibraryOrgan
from aac.prior_organ_o1 import ResetScaffoldOrgan

try:
    from experiments._g7_common import (
        STEPS, O4_FROZEN,
        run_area, wilcoxon_one_sided,
    )
except ModuleNotFoundError:  # direct script execution: python experiments/...
    from _g7_common import (  # type: ignore[no-redef]
        STEPS, O4_FROZEN,
        run_area, wilcoxon_one_sided,
    )


# -- delta target (ADR-0020 S3) ------------------------------------------------

def _compute_delta(calib_o1: float, calib_o4: float) -> float:
    calib_reduction = 1.0 - calib_o4 / calib_o1
    if calib_reduction >= 0.20:
        return 0.20
    return math.floor(100 * 0.80 * calib_reduction) / 100


# -- calibration ---------------------------------------------------------------

def calibrate() -> None:
    seeds = tuple(range(200, 220))
    grid = {
        "sigma": (0.3, 0.5, 0.8),
        "inject_weight": (0.7, 0.85),
        "info_weight": (0.0, 0.3),
        "probe_confidence": (0.5, 0.7),
        "departed_penalty": (1.0, 2.0),
        "max_belief_delta": (1.5, 2.0),
    }
    keys = list(grid)
    print(f"G7 O4 calibration | seeds={seeds[0]}..{seeds[-1]}")

    o1_areas = [run_area(s, lambda: ResetScaffoldOrgan()) for s in seeds]
    o1_mean = sum(o1_areas) / len(seeds)
    print(f"O1 mean: {o1_mean:.1f}")

    rows: list[tuple[float, dict]] = []
    n_combos = 1
    for v in grid.values():
        n_combos *= len(v)
    print(f"Scanning {n_combos} param combos x {len(seeds)} seeds...")

    for combo in itertools.product(*(grid[k] for k in keys)):
        p = dict(zip(keys, combo))
        areas = [run_area(s, lambda p=p: LatentRegimeOrgan(**p)) for s in seeds]
        m = sum(areas) / len(seeds)
        rows.append((m, p))
        tag = "<O1" if m < o1_mean else ">=O1"
        print(f"  {p} -> {m:.1f}  ({tag})")

    rows.sort(key=lambda r: (r[0], tuple(r[1][k] for k in keys)))
    best_area, best_params = rows[0]
    calib_reduction = 1.0 - best_area / o1_mean
    delta = _compute_delta(o1_mean, best_area)

    print(f"\nFROZEN O4 params: {best_params}")
    print(f"  area: {best_area:.1f}  O1: {o1_mean:.1f}")
    print(f"  calib_reduction: {calib_reduction:.4f}")
    print(f"  delta target: {delta}")


# -- r-final gate --------------------------------------------------------------

def gate() -> None:
    seeds = tuple(range(30))
    arms = {
        "O0": lambda: None,
        "O1": lambda: ResetScaffoldOrgan(),
        "O2": lambda: RegimeLibraryOrgan(),
        "O4": lambda: LatentRegimeOrgan(**O4_FROZEN),
    }
    print(
        f"G7 latent-regime gate (ADR-0020) run=r-final "
        f"seeds=0..29 steps={STEPS}"
    )
    print(f"{'seed':>4} | {'O0':>9} {'O1':>9} {'O2':>9} {'O4':>9}")

    areas: dict[str, list[float]] = {k: [] for k in arms}
    for seed in seeds:
        row = {k: run_area(seed, f) for k, f in arms.items()}
        for k, v in row.items():
            areas[k].append(v)
        print(
            f"{seed:>4} | "
            f"{row['O0']:9.1f} {row['O1']:9.1f} "
            f"{row['O2']:9.1f} {row['O4']:9.1f}"
        )

    n = len(seeds)
    means = {k: sum(v) / n for k, v in areas.items()}

    # Per-seed comparisons
    o4_vs_o1_wins = sum(
        1 for i in range(n) if areas["O4"][i] < areas["O1"][i]
    )
    o4_vs_o2_wins = sum(
        1 for i in range(n) if areas["O4"][i] < areas["O2"][i]
    )

    # Wilcoxon: d_i = O1_i - O4_i (positive => O4 better)
    diffs = [areas["O1"][i] - areas["O4"][i] for i in range(n)]
    p_value = wilcoxon_one_sided(diffs)

    # Delta target frozen from calibration (2026-06-13, seeds 200-219).
    # calib O1=1311.5, calib O4=1194.0, calib_reduction=0.0896, delta=0.07.
    CALIB_O1 = 1311.5
    CALIB_O4 = 1194.0
    delta = _compute_delta(CALIB_O1, CALIB_O4)

    print("\nAGGREGATE:")
    for k in arms:
        print(f"  {k}: {means[k]:.1f}")

    print("\nG7 PRE-REGISTERED GATE:")
    print("  G7-1 decisive mean margin:")
    print(f"    mean(O4)={means['O4']:.1f} <= "
          f"{(1 - delta) * means['O1']:.1f}=(1-{delta})*mean(O1)")
    g7_1 = means["O4"] <= (1 - delta) * means["O1"]
    print(f"    {'PASS' if g7_1 else 'FAIL'}")

    print(f"  G7-2 O4 < O2: {o4_vs_o2_wins}/{n} "
          f"(need >={math.ceil(0.9 * n)})")
    g7_2 = o4_vs_o2_wins >= math.ceil(0.9 * n)
    print(f"    {'PASS' if g7_2 else 'FAIL'}")

    print(f"  G7-3 O4 < O1: {o4_vs_o1_wins}/{n} (need >=29)")
    g7_3 = o4_vs_o1_wins >= 29
    print(f"    {'PASS' if g7_3 else 'FAIL'}")

    print(f"  G7-4 Wilcoxon p={p_value:.6f} (need <0.01)")
    g7_4 = p_value < 0.01
    print(f"    {'PASS' if g7_4 else 'FAIL'}")

    print("  G7-C6 organ-not-subject: see unit tests")
    print("  G7-C7 corrigibility: see unit tests")

    all_pass = g7_1 and g7_2 and g7_3 and g7_4
    print(f"\n  G7: {'MET' if all_pass else 'NOT MET'}")

    if not all_pass:
        if not g7_1 or not g7_4:
            print(
                "\n  Even Bayesian latent-regime tracking with active "
                "disambiguation does not significantly beat the cheap reset "
                "at this prototype scale."
            )
        elif g7_1 and g7_4 and not g7_2:
            print(
                "\n  O4 beats O1 but fails O2 dominance: the added posterior "
                "machinery was not worth its complexity."
            )


if __name__ == "__main__":
    (calibrate if len(sys.argv) > 1 and sys.argv[1] == "calibrate" else gate)()
