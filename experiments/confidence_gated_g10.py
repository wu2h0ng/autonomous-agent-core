"""G10 (ADR-0024): fresh-seed confirmation of the decisive subject-side win.

G9 discovered that P0 (the confidence-gated policy, no organ) decisively beats
the baselines, but P0 was NOT the pre-registered G9 candidate (P4 was), so per
ENGINEERING.md s4 item 6 the P0 claim must be confirmed on FRESH seeds with P0
as the pre-specified candidate — never claimed post-hoc on G9's own seeds.

Pure confirmatory measurement: the confidence gate is reused exactly as frozen in
G9 ({gate_kappa=0.5, gate_temp_floor=0.1}); no mechanism changes here.

Arms (StructuredRegimeEnv, same harness/metric as G7/G9):
  A0 baseline policy + none  (bitter-lesson guard)
  A1 baseline policy + O1    (the cheap baseline to beat)
  P0 gated policy + none     (THE pre-specified candidate)

Seeds 800..829 — disjoint from every prior run (0..29 r-final, 700..719 calib, ...).

Gate (ADR-0024 s4): G10-1 mean(P0)<=0.8*mean(A1); G10-2 P0<A0 >=27/30 & p<0.01;
G10-3 P0<A1 >=27/30 & p<0.01; G10-4 effect size + bootstrap 95% CI (lower>0);
G10-C6/C7 = tests/test_confidence_gated_g10.py.

Run: PYTHONPATH=src python -m experiments.confidence_gated_g10
"""

from __future__ import annotations

import math
import random

from aac.prior_organ_o1 import ResetScaffoldOrgan

try:
    from experiments.confidence_gated_g9 import GATE_FROZEN, _area
    from experiments._g7_common import STEPS, wilcoxon_one_sided
except ModuleNotFoundError:  # direct script execution
    from confidence_gated_g9 import GATE_FROZEN, _area  # type: ignore[no-redef]
    from _g7_common import STEPS, wilcoxon_one_sided  # type: ignore[no-redef]

RFINAL_SEEDS = tuple(range(800, 830))
DELTA = 0.20  # decisive-margin target, fixed by ADR-0024 (not derived from results)


def _bootstrap_ci_mean(
    values: list[float], *, n_boot: int = 10000, alpha: float = 0.05, seed: int = 12345
) -> tuple[float, float]:
    """Percentile bootstrap CI for the mean of ``values`` (pure stdlib)."""
    rng = random.Random(seed)
    n = len(values)
    means = sorted(
        sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot)
    )
    lo = means[int((alpha / 2) * n_boot)]
    hi = means[int((1 - alpha / 2) * n_boot)]
    return lo, hi


def gate() -> None:
    seeds = RFINAL_SEEDS
    k, tf = GATE_FROZEN["gate_kappa"], GATE_FROZEN["gate_temp_floor"]
    arms = {
        "A0": lambda s: _area(s, lambda: None),
        "A1": lambda s: _area(s, lambda: ResetScaffoldOrgan()),
        "P0": lambda s: _area(s, lambda: None, gate=True, kappa=k, temp_floor=tf),
    }
    print(f"G10 P0 confirmation (ADR-0024) run=r-final seeds=800..829 steps={STEPS}")
    print(f"{'seed':>4} | {'A0':>9} {'A1':>9} {'P0':>9}")
    areas: dict[str, list[float]] = {x: [] for x in arms}
    for seed in seeds:
        row = {x: f(seed) for x, f in arms.items()}
        for x, v in row.items():
            areas[x].append(v)
        print(f"{seed:>4} | " + " ".join(f"{row[x]:9.1f}" for x in arms))

    n = len(seeds)
    mean = {x: sum(v) / n for x, v in areas.items()}
    p0_lt_a0 = sum(1 for i in range(n) if areas["P0"][i] < areas["A0"][i])
    p0_lt_a1 = sum(1 for i in range(n) if areas["P0"][i] < areas["A1"][i])
    p_a0 = wilcoxon_one_sided([areas["A0"][i] - areas["P0"][i] for i in range(n)])
    p_a1 = wilcoxon_one_sided([areas["A1"][i] - areas["P0"][i] for i in range(n)])
    need = math.ceil(0.9 * n)

    # Effect size on the A1->P0 paired reduction (positive = P0 better).
    red = [areas["A1"][i] - areas["P0"][i] for i in range(n)]
    red_sorted = sorted(red)
    median_red = (
        red_sorted[n // 2]
        if n % 2
        else (red_sorted[n // 2 - 1] + red_sorted[n // 2]) / 2
    )
    pct_red = 1 - mean["P0"] / mean["A1"]
    ci_lo, ci_hi = _bootstrap_ci_mean(red)

    print("\nAGGREGATE:")
    for x in arms:
        print(f"  {x}: {mean[x]:.1f}")
    print(f"  per-seed: P0<A0 {p0_lt_a0}/{n}  P0<A1 {p0_lt_a1}/{n}")
    print(
        f"  effect size (A1-P0): mean {mean['A1'] - mean['P0']:.1f}  median {median_red:.1f}  "
        f"pct {pct_red:.1%}  bootstrap95%CI [{ci_lo:.1f}, {ci_hi:.1f}]"
    )

    print("\nG10 PRE-REGISTERED GATE:")
    g1 = mean["P0"] <= (1 - DELTA) * mean["A1"]
    print(
        f"  G10-1 mean(P0)={mean['P0']:.1f} <= {(1 - DELTA) * mean['A1']:.1f}=(1-{DELTA})*A1: "
        f"{'PASS' if g1 else 'FAIL'}"
    )
    g2 = p0_lt_a0 >= need and p_a0 < 0.01
    print(
        f"  G10-2 P0<A0 {p0_lt_a0}/{n}(>= {need}) & Wilcoxon p={p_a0:.6f}<0.01: "
        f"{'PASS' if g2 else 'FAIL'}"
    )
    g3 = p0_lt_a1 >= need and p_a1 < 0.01
    print(
        f"  G10-3 P0<A1 {p0_lt_a1}/{n}(>= {need}) & Wilcoxon p={p_a1:.6f}<0.01: "
        f"{'PASS' if g3 else 'FAIL'}"
    )
    g4 = ci_lo > 0
    print(
        f"  G10-4 effect size reported & bootstrap95%CI lower={ci_lo:.1f} > 0: "
        f"{'PASS' if g4 else 'FAIL'}"
    )
    print("  G10-C6/C7: see tests/test_confidence_gated_g10.py")

    met = g1 and g2 and g3 and g4
    print(f"\n  G10: {'MET' if met else 'NOT MET'}")
    if not met:
        print(
            "\n  P0 did not replicate the decisive subject-side win on fresh seeds — "
            "treat the G9 P0 result as a seed artifact (ADR-0024 s6); do not retune."
        )


if __name__ == "__main__":
    gate()
