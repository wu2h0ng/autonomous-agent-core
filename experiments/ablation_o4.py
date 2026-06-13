"""P1-T2: O4 ablation study -- decompose LatentRegimeOrgan component contributions.

Five arms on StructuredRegimeEnv (default params, same as G7):
  O4-full         : complete LatentRegimeOrgan (G7 frozen params)
  O4-no-info      : info_weight=0 (remove information-directed shaping)
  O4-no-transition: departed_penalty=0 (remove transition prior)
  O4-oneshot      : continuous_inject=False (continuous -> one-shot injection)
  O4-no-posterior : bayesian_update=False (uniform posterior, no evidence accumulation)

Pre-registered design:
  - 30 seeds (0-29), same as G7 r-final
  - Metric: post-shift regret area
  - Statistics: paired one-sided Wilcoxon (O4-full vs each ablation)
    d_i = ablation_i - full_i (positive => full better => ablation hurts)
  - Gate: O4-full must significantly beat each ablation (p < 0.05)
    to claim the component contributes

Run: PYTHONPATH=src python -m experiments.ablation_o4
"""
from __future__ import annotations

from aac.prior_organ_latent import LatentRegimeOrgan

try:
    from experiments._g7_common import (
        O4_FROZEN,
        format_table,
        run_area,
        wilcoxon_one_sided,
    )
except ModuleNotFoundError:  # direct script execution: python experiments/...
    from _g7_common import (  # type: ignore[no-redef]
        O4_FROZEN,
        format_table,
        run_area,
        wilcoxon_one_sided,
    )

SEEDS = tuple(range(30))

def _with_overrides(**overrides: object) -> dict:
    p = dict(O4_FROZEN)
    p.update(overrides)
    return p


ARMS: dict[str, tuple[str, dict]] = {
    "O4-full": (
        "complete O4",
        dict(O4_FROZEN),
    ),
    "O4-no-info": (
        "info_weight=0",
        _with_overrides(info_weight=0.0),
    ),
    "O4-no-transition": (
        "departed_penalty=0",
        _with_overrides(departed_penalty=0.0),
    ),
    "O4-oneshot": (
        "continuous_inject=False",
        _with_overrides(continuous_inject=False),
    ),
    "O4-no-posterior": (
        "bayesian_update=False",
        _with_overrides(bayesian_update=False),
    ),
}

ABLATION_NAMES = list(ARMS.keys())


def ablation_study() -> None:
    """Run the full 5-arm ablation study and print results."""
    print(
        "P1-T2 O4 ablation study (ADR-0020 extension)\n"
        f"  arms: {' | '.join(ABLATION_NAMES)}\n"
        f"  seeds: {SEEDS[0]}..{SEEDS[-1]} ({len(SEEDS)} seeds, paired with G7 r-final)\n"
        "  metric: post-shift regret area (window=15)\n"
    )

    # Arm descriptions
    for name, (desc, params) in ARMS.items():
        print(f"  {name:20s} : {desc}")
    print()

    # Run all arms for all seeds
    areas: dict[str, list[float]] = {name: [] for name in ABLATION_NAMES}

    for seed in SEEDS:
        row_vals = {}
        for name, (_, params) in ARMS.items():
            a = run_area(seed, lambda p=params: LatentRegimeOrgan(**p))
            areas[name].append(a)
            row_vals[name] = a
        vals = " ".join(f"{row_vals[n]:9.1f}" for n in ABLATION_NAMES)
        print(f"  {seed:>2} | {vals}")

    # Aggregate
    n = len(SEEDS)
    means = {name: sum(v) / n for name, v in areas.items()}
    full_mean = means["O4-full"]

    # Per-ablation Wilcoxon: d_i = ablation_i - full_i (positive => full better)
    print("\nAGGREGATE:")
    headers = ["arm", "mean", "vs_full", "Wilcoxon_p", "sig?"]
    rows = []
    component_results: list[tuple[str, float, float, bool]] = []

    for name in ABLATION_NAMES:
        m = means[name]
        if name == "O4-full":
            rows.append([name, f"{m:.1f}", "--", "--", "--"])
            continue

        vs_full_pct = (m - full_mean) / full_mean * 100 if full_mean != 0 else 0.0
        diffs = [areas[name][i] - areas["O4-full"][i] for i in range(n)]
        p = wilcoxon_one_sided(diffs)
        sig = p < 0.05

        rows.append([
            name,
            f"{m:.1f}",
            f"{vs_full_pct:+.1f}%",
            f"{p:.4f}",
            "YES" if sig else "no",
        ])
        component_results.append((name, vs_full_pct, p, sig))

    print(format_table(headers, rows, alignments=["l", "r", "r", "r", "l"]))

    # Component contribution ranking (sorted by vs_full_pct descending)
    component_results.sort(key=lambda x: x[1], reverse=True)
    print("\nComponent contribution ranking:")
    for rank, (name, pct, p, sig) in enumerate(component_results, 1):
        sig_tag = "SIGNIFICANT" if sig else "not significant"
        print(f"  {rank}. {name}: {pct:+.1f}% (p={p:.4f}, {sig_tag})")

    # Ablation gate
    n_sig = sum(1 for _, _, _, sig in component_results if sig)
    total_abl = len(component_results)
    gate_pass = n_sig >= 1
    print("\nP1-T2 ABLATION GATE:")
    print(f"  O4-full significantly beats {n_sig}/{total_abl} ablation arms")
    print(f"  {'PASS' if gate_pass else 'FAIL'}")


if __name__ == "__main__":
    ablation_study()
