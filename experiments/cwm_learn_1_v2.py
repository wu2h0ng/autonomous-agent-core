"""CWM-LEARN-1 v2 — leak-closed discrimination test (prereg §7, FROZEN prediction NULL).

Excludes the intervened node's own value from LearnedCWM features; scores every (X,T) pair and
measures DISCRIMINATION AUC (rank true-ancestor pairs above non-ancestor pairs) for both arms.
Run: PYTHONPATH=src python -m experiments.cwm_learn_1_v2
"""
from __future__ import annotations

import json
import os
import statistics

from aac.learned_cwm import LearnedCWM
from experiments.sachs_task import PROTEINS, INTERVENABLE, ancestors, load_int

SEEDS = tuple(range(10))
TRAIN_FRAC = 0.6
DELTA = 0.05


def _by_code():
    by = {}
    for vals, code in load_int():
        by.setdefault(code, []).append([float(v) for v in vals])
    return by


def _stat_effect(do_rows, base_rows, t):
    a = [r[t] for r in do_rows]; b = [r[t] for r in base_rows]
    if len(a) < 2 or len(b) < 2:
        return 0.0
    ma, mb = statistics.mean(a), statistics.mean(b)
    sd = (statistics.pstdev(a) + statistics.pstdev(b)) / 2 or 1e-9
    return abs(ma - mb) / sd


def _disc_auc(scores, is_anc):
    return LearnedCWM._auc(scores, [1 if a else 0 for a in is_anc])


def _binom(k, n):
    from math import comb
    if n == 0:
        return 1.0
    le = sum(comb(n, i) for i in range(k + 1)) / 2 ** n
    ge = sum(comb(n, i) for i in range(k, n + 1)) / 2 ** n
    return min(1.0, 2 * min(le, ge))


def main():
    by = _by_code(); base = by[0]; cwm = LearnedCWM()
    targets = [t for t in PROTEINS if ancestors(t) & set(INTERVENABLE) - {t}]
    pairs = []
    for t in targets:
        ti = PROTEINS.index(t); gt = ancestors(t) & set(INTERVENABLE) - {t}
        for x, code in INTERVENABLE.items():
            if x == t or len(by.get(code, [])) < 10:
                continue
            pairs.append((t, ti, x, PROTEINS.index(x), code, x in gt))

    stat_disc, cwm_disc = [], []
    for seed in SEEDS:
        stat_scores, cwm_scores, anc = [], [], []
        cut_b = int(len(base) * TRAIN_FRAC)
        for t, ti, x, xi, code, is_anc in pairs:
            do = by[code]
            stat_scores.append(_stat_effect(do[:int(len(do) * TRAIN_FRAC)], base[:cut_b], ti))
            cwm_scores.append(cwm.ancestry_auc(do, base, ti, seed, TRAIN_FRAC, exclude=(xi,)))
            anc.append(is_anc)
        stat_disc.append(_disc_auc(stat_scores, anc))
        cwm_disc.append(_disc_auc(cwm_scores, anc))

    ms, mc = statistics.mean(stat_disc), statistics.mean(cwm_disc)
    delta = mc - ms
    n_plus = sum(1 for c, s in zip(cwm_disc, stat_disc) if c > s)
    n_minus = sum(1 for c, s in zip(cwm_disc, stat_disc) if s > c)
    p = _binom(n_plus, n_plus + n_minus)
    verdict = "MET" if (delta >= DELTA and n_plus > n_minus and p < 0.05) else "NULL"

    result = {"prereg": "docs/pre_spec/S1B-CWM-LEARN-1.PREREG-2026-07-03.md (v2 §7)",
              "n_pairs": len(pairs), "seeds": len(SEEDS),
              "stat_discrimination_auc": round(ms, 4), "cwm_discrimination_auc": round(mc, 4),
              "delta": round(delta, 4), "n_plus": n_plus, "n_minus": n_minus,
              "sign_test_p": round(p, 5), "verdict": verdict}
    print(f"CWM-LEARN-1 v2 (leak-closed)  pairs={len(pairs)} seeds={len(SEEDS)}")
    print(f"  STAT discrimination AUC={ms:.3f}  LearnedCWM discrimination AUC={mc:.3f}  delta={delta:+.3f}")
    print(f"  sign-test n+/n-={n_plus}/{n_minus} p={p:.4f}")
    print(f"  VERDICT: {verdict}")
    with open(os.path.join(os.path.dirname(__file__), "cwm_learn_1_v2.result.json"), "w") as f:
        json.dump(result, f, indent=1)


if __name__ == "__main__":
    main()
