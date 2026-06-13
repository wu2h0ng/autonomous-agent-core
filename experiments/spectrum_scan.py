"""P1-T1: Structure-transferability spectrum scan.

Vary StructuredRegimeEnv's n_regimes and noise to find the phase boundary
where O4 (LatentRegimeOrgan) loses its decisive advantage over O1 (cheap reset).

Pre-registered design:
  - Grid: n_regimes in {2, 5, 10, 20} x noise in {0.1, 0.3, 0.5, 1.0}
  - 16 conditions, 2 arms (O1, O4), 10 seeds (0-9) per condition
  - Metric: post-shift regret area (same as G7)
  - Decision: O4 advantage = 1 - mean(O4)/mean(O1)
    advantage > 0 => O4 better; <= 0 => O4 no longer wins
  - Significance: paired Wilcoxon (one-sided, p < 0.05)

Run: PYTHONPATH=src python experiments/spectrum_scan.py
"""
from __future__ import annotations

from typing import Any

from aac.prior_organ_latent import LatentRegimeOrgan
from aac.prior_organ_o1 import ResetScaffoldOrgan

from experiments._g7_common import (
    O4_FROZEN,
    format_table,
    run_area,
    wilcoxon_one_sided,
)

N_REGIMES_GRID = [2, 5, 10, 20]
NOISE_GRID = [0.1, 0.3, 0.5, 1.0]
SEEDS = tuple(range(10))


def _scan_condition(
    n_regimes: int,
    noise: float,
    seeds: tuple[int, ...],
) -> dict[str, Any]:
    """Run one (n_regimes, noise) condition and return results."""
    env_kwargs = {"n_regimes": n_regimes, "noise": noise}
    o1_areas = [
        run_area(s, lambda: ResetScaffoldOrgan(), env_kwargs=env_kwargs)
        for s in seeds
    ]
    o4_areas = [
        run_area(s, lambda: LatentRegimeOrgan(**O4_FROZEN), env_kwargs=env_kwargs)
        for s in seeds
    ]
    o1_mean = sum(o1_areas) / len(seeds)
    o4_mean = sum(o4_areas) / len(seeds)
    advantage = 1.0 - o4_mean / o1_mean if o1_mean != 0 else 0.0

    diffs = [o1_areas[i] - o4_areas[i] for i in range(len(seeds))]
    p_value = wilcoxon_one_sided(diffs)

    return {
        "n_regimes": n_regimes,
        "noise": noise,
        "o1_areas": o1_areas,
        "o4_areas": o4_areas,
        "o1_mean": o1_mean,
        "o4_mean": o4_mean,
        "advantage": advantage,
        "p_value": p_value,
        "significant": advantage > 0 and p_value < 0.05,
    }


def spectrum_scan() -> None:
    """Run the full 4x4 spectrum scan and print results."""
    print(
        "P1-T1 Structure-transferability spectrum scan\n"
        f"  grid: n_regimes={N_REGIMES_GRID} x noise={NOISE_GRID}\n"
        "  arms: O1 (ResetScaffoldOrgan) vs O4 (LatentRegimeOrgan)\n"
        f"  seeds: {SEEDS[0]}..{SEEDS[-1]} ({len(SEEDS)} seeds per condition)\n"
        "  metric: post-shift regret area (window=15)\n"
    )

    results: list[dict[str, Any]] = []
    total = len(N_REGIMES_GRID) * len(NOISE_GRID)
    done = 0

    for nr in N_REGIMES_GRID:
        for ns in NOISE_GRID:
            done += 1
            print(f"  [{done}/{total}] n_regimes={nr}, noise={ns} ...", end=" ")
            r = _scan_condition(nr, ns, SEEDS)
            results.append(r)
            sig_tag = "YES" if r["significant"] else "no"
            print(
                f"O1={r['o1_mean']:.1f}  O4={r['o4_mean']:.1f}  "
                f"adv={r['advantage']:.3f}  p={r['p_value']:.4f}  sig={sig_tag}"
            )

    # Print table
    headers = ["n_regimes", "noise", "O1", "O4", "advantage", "p", "sig?"]
    rows = []
    for r in results:
        rows.append([
            str(r["n_regimes"]),
            f"{r['noise']:.2f}",
            f"{r['o1_mean']:.1f}",
            f"{r['o4_mean']:.1f}",
            f"{r['advantage']:.3f}",
            f"{r['p_value']:.4f}",
            "YES" if r["significant"] else "no",
        ])
    print()
    print(format_table(headers, rows, alignments=["r", "r", "r", "r", "r", "r", "l"]))

    # Phase boundary summary
    wins = sum(1 for r in results if r["significant"])
    losses = [r for r in results if not r["significant"]]
    print(f"\nPhase boundary summary:")
    print(f"  O4 wins in {wins}/{total} conditions")
    if losses:
        first_loss = losses[0]
        print(
            f"  First loss at: n_regimes={first_loss['n_regimes']}, "
            f"noise={first_loss['noise']:.2f}"
        )
    else:
        print("  O4 wins in all conditions (no phase boundary found)")


if __name__ == "__main__":
    spectrum_scan()
