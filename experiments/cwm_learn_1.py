"""CWM-LEARN-1 — learned CWM vs same-budget statistical baseline on real Sachs (S1b).

Prereg (FROZEN): docs/pre_spec/S1B-CWM-LEARN-1.PREREG-2026-07-03.md (f6ab589).
Run: PYTHONPATH=src python -m experiments.cwm_learn_1
"""
from __future__ import annotations

import json
import math
import os
import statistics

from aac.learned_cwm import LearnedCWM
from experiments.sachs_task import PROTEINS, INTERVENABLE, ancestors, load_int

TAU_STAT = 0.3      # frozen
TAU_CWM = 0.60      # frozen (held-out AUC)
DELTA = 0.05        # frozen
SEEDS = tuple(range(10))
TRAIN_FRAC = 0.6


def _int_rows():
    """Group Sachs interventional rows by the perturbed node code; code 0 = observational base."""
    by_code: dict[int, list[list[float]]] = {}
    for vals, code in load_int():
        by_code.setdefault(code, []).append([float(v) for v in vals])
    return by_code


def _stat_effect(do_rows, base_rows, t: int) -> float:
    a = [r[t] for r in do_rows]
    b = [r[t] for r in base_rows]
    if len(a) < 2 or len(b) < 2:
        return 0.0
    ma, mb = statistics.mean(a), statistics.mean(b)
    sd = (statistics.pstdev(a) + statistics.pstdev(b)) / 2 or 1e-9
    return abs(ma - mb) / sd


def _binom_two_sided(k: int, n: int) -> float:
    if n == 0:
        return 1.0
    from math import comb
    le = sum(comb(n, i) for i in range(0, k + 1)) / 2 ** n
    ge = sum(comb(n, i) for i in range(k, n + 1)) / 2 ** n
    return min(1.0, 2 * min(le, ge))


def main():
    by_code = _int_rows()
    base = by_code.get(0, [])
    cwm = LearnedCWM()
    targets = [t for t in PROTEINS if ancestors(t) & set(INTERVENABLE) - {t}]

    stat_recalls, cwm_recalls, neg_aucs = [], [], []
    per_seed_stat, per_seed_cwm = [], []
    for seed in SEEDS:
        s_tp = s_fn = c_tp = c_fn = 0
        for t in targets:
            ti = PROTEINS.index(t)
            gt = ancestors(t) & set(INTERVENABLE) - {t}
            for x, code in INTERVENABLE.items():
                if x == t:
                    continue
                do_rows = by_code.get(code, [])
                if len(do_rows) < 10 or len(base) < 10:
                    continue
                is_anc = x in gt
                # STAT baseline (marginal effect size on the same train portion budget)
                cut = int(len(do_rows) * TRAIN_FRAC)
                stat_eff = _stat_effect(do_rows[:cut], base[:int(len(base) * TRAIN_FRAC)], ti)
                stat_pred = stat_eff >= TAU_STAT
                # LearnedCWM (multivariate held-out AUC)
                auc = cwm.ancestry_auc(do_rows, base, ti, seed, TRAIN_FRAC)
                cwm_pred = auc >= TAU_CWM
                if is_anc:
                    s_tp += stat_pred; s_fn += (not stat_pred)
                    c_tp += cwm_pred; c_fn += (not cwm_pred)
                # confound negative control (permuted labels) on ancestor cases only (seed 0)
                if seed == 0 and is_anc:
                    neg_aucs.append(cwm.ancestry_auc(do_rows, base, ti, seed, TRAIN_FRAC, permute=True))
        s_rec = s_tp / (s_tp + s_fn) if (s_tp + s_fn) else 0.0
        c_rec = c_tp / (c_tp + c_fn) if (c_tp + c_fn) else 0.0
        per_seed_stat.append(s_rec); per_seed_cwm.append(c_rec)
        stat_recalls.append(s_rec); cwm_recalls.append(c_rec)

    mean_stat = statistics.mean(stat_recalls)
    mean_cwm = statistics.mean(cwm_recalls)
    delta = mean_cwm - mean_stat
    n_plus = sum(1 for c, s in zip(per_seed_cwm, per_seed_stat) if c > s)
    n_minus = sum(1 for c, s in zip(per_seed_cwm, per_seed_stat) if s > c)
    p = _binom_two_sided(n_plus, n_plus + n_minus)
    neg_mean = statistics.mean(neg_aucs) if neg_aucs else 0.5
    neg_collapses = abs(neg_mean - 0.5) < 0.1   # permuted labels -> chance

    if not neg_collapses:
        verdict = "INVALID"
    elif delta >= DELTA and n_plus > n_minus and p < 0.05:
        verdict = "MET"
    else:
        verdict = "NULL"

    result = {
        "prereg": "docs/pre_spec/S1B-CWM-LEARN-1.PREREG-2026-07-03.md",
        "seeds": len(SEEDS), "targets": targets,
        "stat_recall_mean": round(mean_stat, 4), "cwm_recall_mean": round(mean_cwm, 4),
        "delta": round(delta, 4), "n_plus": n_plus, "n_minus": n_minus,
        "sign_test_p": round(p, 5),
        "neg_control_auc_mean": round(neg_mean, 4), "neg_control_collapses_to_chance": neg_collapses,
        "verdict": verdict,
    }
    print(f"CWM-LEARN-1  seeds={len(SEEDS)} targets={len(targets)}")
    print(f"  STAT recall={mean_stat:.3f}  LearnedCWM recall={mean_cwm:.3f}  delta={delta:+.3f}")
    print(f"  sign-test n+/n-={n_plus}/{n_minus} p={p:.4f}")
    print(f"  neg-control AUC={neg_mean:.3f} (collapses={neg_collapses})")
    print(f"  VERDICT: {verdict}")
    out = os.path.join(os.path.dirname(__file__), "cwm_learn_1.result.json")
    with open(out, "w") as f:
        json.dump(result, f, indent=1)
    print(f"  result: {out}")


if __name__ == "__main__":
    main()
