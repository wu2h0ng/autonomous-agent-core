"""Stage 3 adjudicator for the strong-locus structure crossover.

Loads the Stage 3 result JSON and spec, drops INVALID seeds, computes per-k and
pooled bootstrap CIs, runs the pre-registered Spearman one-sided trend test, and
emits a verdict JSON.

Pure stdlib. Run from autonomous-agent-core root:
    PYTHONPATH=src python experiments/strong_locus_stage3_adjudicate.py \
        --result experiments/strong_locus_stage3.result.json \
        --spec experiments/strong_locus_stage3.spec.json \
        --output experiments/strong_locus_stage3.verdict.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from itertools import permutations
from typing import Any

sys.path.insert(0, "src")
sys.path.insert(0, "experiments")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 3 strong-locus adjudicator")
    parser.add_argument("--result", required=True, help="Stage 3 result JSON")
    parser.add_argument("--spec", required=True, help="Stage 3 spec JSON")
    parser.add_argument("--output", required=True, help="Output verdict JSON")
    parser.add_argument(
        "--n-bootstrap", type=int, default=2000, help="Bootstrap replicates"
    )
    parser.add_argument(
        "--alpha", type=float, default=0.05, help="Significance level"
    )
    return parser.parse_args()


def _load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _is_valid_seed(row: dict[str, Any], stub_only: bool = False) -> bool:
    """A seed is INVALID if placebo fails, no detectable signal, or organ plumbing failed.

    When stub_only is True, organ_alone failures are expected (the stub does not
    return real edges) and are ignored for seed validity; organ_tools and
    organ_tools_externalized still must not report plumbing failures.
    """
    if not row.get("placebo_passes", False):
        return False
    if row.get("n_true", 0) == 0:
        return False
    plumbing = row.get("plumbing", {})
    organ_arms = ["organ_tools", "organ_tools_externalized"]
    if not stub_only:
        organ_arms.append("organ_alone")
    for arm in organ_arms:
        if plumbing.get(arm, {}).get("has_plumbing_failure", False):
            return False
    return True


def _delta_for_row(row: dict[str, Any], use_organ_alone_stub: bool) -> float:
    loop_ap = row["arm_results"]["governed_loop"]["ap"]
    if use_organ_alone_stub:
        return loop_ap - row["arm_results"]["organ_alone"]["ap"]
    return loop_ap - row["arm_results"]["organ_tools"]["ap"]


def _median(values: list[float]) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def _bootstrap_ci(
    values: list[float], n_boot: int = 2000, alpha: float = 0.05, rng_seed: int = 0
) -> tuple[float, float]:
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(rng_seed)
    n = len(values)
    stats: list[float] = []
    for _ in range(n_boot):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        stats.append(sum(sample) / n)
    stats.sort()
    lo_idx = int((alpha / 2) * n_boot)
    hi_idx = int((1 - alpha / 2) * n_boot)
    lo_idx = max(0, min(lo_idx, n_boot - 1))
    hi_idx = max(0, min(hi_idx, n_boot - 1))
    return (stats[lo_idx], stats[hi_idx])


def _spearman_rho(x: list[float], y: list[float]) -> float:
    """Spearman rank correlation (simple ranks, ties broken by first occurrence)."""
    if len(x) != len(y) or len(x) < 2:
        return 0.0

    def _ranks(vals: list[float]) -> list[int]:
        indexed = sorted(enumerate(vals), key=lambda kv: kv[1])
        ranks = [0] * len(vals)
        for rank, (idx, _) in enumerate(indexed, start=1):
            ranks[idx] = rank
        return ranks

    rx = _ranks(x)
    ry = _ranks(y)
    n = len(x)
    d2 = sum((rx[i] - ry[i]) ** 2 for i in range(n))
    return 1.0 - (6.0 * d2) / (n * (n * n - 1))


def _spearman_one_sided_p(x: list[float], y: list[float]) -> tuple[float, float]:
    """Exact one-sided p-value for positive Spearman correlation (permutation test)."""
    if len(x) != len(y) or len(x) < 2:
        return 0.0, 1.0
    obs_rho = _spearman_rho(x, y)
    if math.isnan(obs_rho):
        return obs_rho, 1.0
    count = 0
    total = 0
    for perm in permutations(y):
        total += 1
        if _spearman_rho(x, list(perm)) >= obs_rho:
            count += 1
    return obs_rho, count / total if total > 0 else 1.0


def _apply_kill_conditions(
    result: dict[str, Any],
    spec: dict[str, Any],
    valid_rows: list[dict[str, Any]],
    by_k: dict[int, list[dict[str, Any]]],
    pooled_ci: tuple[float, float],
) -> list[str]:
    reasons: list[str] = []

    if result.get("stub_only", False):
        reasons.append("stub_only: real LLM backend absent; H_locus invalid")

    plumbing_summary = result.get("plumbing_summary", {})
    total_calls = plumbing_summary.get("total_organ_calls", 0)
    total_failures = plumbing_summary.get("total_plumbing_failures", 0)
    if total_calls > 0 and total_failures / total_calls > 0.25:
        reasons.append("organ-arm plumbing failure rate > 25%")

    total_seeds = len(result.get("results", []))
    placebo_failures = sum(
        1 for r in result.get("results", []) if not r.get("placebo_passes", False)
    )
    if total_seeds > 0 and placebo_failures / total_seeds > 0.10:
        reasons.append("placebo failure rate > 10%")

    if not valid_rows:
        reasons.append("no valid seeds remain after dropping INVALID")

    two_largest = sorted(by_k.keys())[-2:]
    for k in two_largest:
        rows = by_k[k]
        if rows:
            median_loop = _median([r["arm_results"]["governed_loop"]["ap"] for r in rows])
            if median_loop <= 0.0:
                reasons.append(f"governed_loop median AP <= 0 at k={k}")

    if not math.isnan(pooled_ci[0]) and pooled_ci[0] <= 0.0:
        reasons.append("pooled effect CI lower <= 0")

    return reasons


def adjudicate(
    result: dict[str, Any],
    spec: dict[str, Any],
    n_boot: int = 2000,
    alpha: float = 0.05,
) -> dict[str, Any]:
    use_organ_alone_stub = result.get("stub_only", False)
    all_rows = result.get("results", [])
    valid_rows = [r for r in all_rows if _is_valid_seed(r, use_organ_alone_stub)]

    by_k: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in valid_rows:
        by_k[r["k"]].append(r)

    ks = sorted(by_k.keys())
    delta_by_k: dict[int, list[float]] = {}
    median_delta: dict[str, float] = {}
    mean_delta: dict[str, float] = {}
    ci_delta: dict[str, list[float]] = {}

    for k in ks:
        deltas = [_delta_for_row(r, use_organ_alone_stub) for r in by_k[k]]
        delta_by_k[k] = deltas
        median_delta[str(k)] = _median(deltas)
        mean_delta[str(k)] = sum(deltas) / len(deltas) if deltas else float("nan")
        lo, hi = _bootstrap_ci(deltas, n_boot=n_boot, alpha=alpha)
        ci_delta[str(k)] = [lo, hi]

    two_largest = sorted(ks)[-2:]
    pooled_deltas: list[float] = []
    for k in two_largest:
        for r in by_k[k]:
            pooled_deltas.append(_delta_for_row(r, use_organ_alone_stub))
    pooled_ci = _bootstrap_ci(pooled_deltas, n_boot=n_boot, alpha=alpha)

    median_values = [median_delta[str(k)] for k in ks]
    rho, p_value = _spearman_one_sided_p([float(k) for k in ks], median_values)

    trend_threshold = 0.05
    trend_significant = not math.isnan(p_value) and p_value <= trend_threshold

    kill_reasons = _apply_kill_conditions(result, spec, valid_rows, by_k, pooled_ci)

    if not valid_rows or len(valid_rows) < max(1, len(all_rows) // 2):
        verdict = "INSUFFICIENT_DATA"
    elif use_organ_alone_stub:
        verdict = "INVALID"
    elif kill_reasons:
        verdict = "NOT_MET"
    elif not trend_significant:
        verdict = "NOT_MET"
    else:
        verdict = "MET"

    if not trend_significant and verdict not in ("INVALID", "INSUFFICIENT_DATA"):
        kill_reasons.append("Spearman trend test not significant (p > 0.05)")

    return {
        "verdict": verdict,
        "reason": "; ".join(kill_reasons) if kill_reasons else "all gates passed",
        "statistics": {
            "median_delta_ap_by_k": median_delta,
            "mean_delta_ap_by_k": mean_delta,
            "ci_delta_ap_by_k": ci_delta,
            "pooled_two_largest_ci": list(pooled_ci),
            "spearman_rho": rho,
            "spearman_p_one_sided": p_value,
            "valid_seeds": len(valid_rows),
            "total_seeds": len(all_rows),
            "ks": ks,
        },
        "caveats": [
            (
                "stub_only: organ arms invalid for H_locus; diagnostics only"
                if use_organ_alone_stub
                else "real LLM backend requested"
            )
        ],
        "spec_ref": spec.get("prereg_ref"),
        "trend_test": spec.get("trend_test"),
        "effect_floor": spec.get("effect_floor"),
    }


def main() -> int:
    args = _parse_args()
    result = _load_json(args.result)
    spec = _load_json(args.spec)

    verdict = adjudicate(result, spec, n_boot=args.n_bootstrap, alpha=args.alpha)

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(verdict, fh, indent=2, sort_keys=True)

    print(json.dumps(verdict, indent=2, sort_keys=True))
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
