"""5e-2 COMPOSITIONAL pilot (calibration): the open-vocabulary knowledge-exclusive region is real iff a
COMPOSED true mechanism (depth-2, e.g. tanh(a*b) gated by threshold(c)) defeats a FINITE base-form menu
(which cannot enumerate the combinatorial composition space) while an oracle composed feature captures it.
If finite-menu best reaches oracle, even compositions are menu-able at toy scale -> region empty (record).
If finite-menu best fails and composed oracle succeeds -> the exclusive region exists -> LLM open-vocab
compositional proposal is the only searcher that can reach it (next: real LLM proposals + safe-eval)."""
from __future__ import annotations

import json
import math
import random
import statistics

from aac.invariant_structure import InvariantStructureFilter

P = {"n_raw": 12, "n_envs": 3, "n": 300, "noise": 0.5, "spur_c": [1.5, -1.2, 0.9], "beta": 1.8}
SEEDS = [700, 701, 702]
CAUSAL = (2, 5, 8)   # three causal features; true form composes all three

# base menu (finite): single-form over PAIRS — the enumerable region
BASE = {
    "product": lambda a, b: a * b,
    "tanh": lambda a, b: math.tanh(2 * a) * b,
    "threshold": lambda a, b: b * (1.0 if a > 0.5 else 0.0),
    "deadzone": lambda a, b: b * (1.0 if abs(a) > 1.0 else -1.0),
    "absdiff": lambda a, b: -abs(a - b),
    "ratio": lambda a, b: a / (1.0 + abs(b)),
}


def true_form(x):
    # DEPTH-2 composition of 3 features: tanh(x2*x5) gated by a threshold on x8 — not any single base pair
    a, b, c = x[CAUSAL[0]], x[CAUSAL[1]], x[CAUSAL[2]]
    return math.tanh(2.0 * a * b) * (1.0 if c > 0.3 else -1.0)


def gen(seed, env_i):
    r = random.Random(f"comp|{seed}|{env_i}")
    rows, ys = [], []
    for _ in range(P["n"]):
        x = [r.gauss(0, 1) for _ in range(P["n_raw"])]
        y = 1 if (P["beta"] * true_form(x) + r.gauss(0, P["noise"])) > 0 else 0
        x[3] += P["spur_c"][env_i] * (2 * y - 1) + r.gauss(0, 0.8)   # env-flipping spurious on slot 3
        rows.append(x); ys.append(y)
    return rows, ys


def verify(envs, te, feat, seed):
    tr = [([r + [feat(r)] for r in X], Y) for X, Y in envs]
    teX = [r + [feat(r)] for r in te[0]]
    m = InvariantStructureFilter(basis="raw").fit(tr, seed=seed)
    return m.score_auc(teX, te[1]) if m.found else 0.5


def best_finite_menu(envs, te, seed):
    """Best single base-form over all feature pairs (the enumerable finite-menu searcher)."""
    n = P["n_raw"]
    best = 0.5
    for fname, f in BASE.items():
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                best = max(best, verify(envs, te, (lambda r, _f=f, _i=i, _j=j: _f(r[_i], r[_j])), seed))
    return best


def main():
    o_scores, m_scores = [], []
    for s in SEEDS:
        envs = [gen(s + i, i) for i in range(P["n_envs"])]
        te = gen(s + 40, 0)
        o_scores.append(verify(envs, te, true_form, s))          # oracle composed feature
        m_scores.append(best_finite_menu(envs, te, s))           # best finite base-form pair
    o, m = statistics.mean(o_scores), statistics.mean(m_scores)
    out = {"true_form": "tanh(2*x2*x5) * threshold(x8>0.3) [depth-2, 3-feature composition]",
           "oracle_composed_auc": round(o, 3), "best_finite_menu_auc": round(m, 3),
           "exclusive_gap": round(o - m, 3),
           "open_vocab_region_exists": bool(o - m >= 0.10 and o >= 0.75)}
    open("experiments/e5_2_compositional_pilot.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
