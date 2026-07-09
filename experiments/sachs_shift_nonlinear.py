"""sachs_shift_nonlinear — TEST the §28 diagnosis instead of asserting it. §28 found a linear causal
predictor does NOT beat correlation for VALUE prediction under real distribution shift on Sachs, and diagnosed
the cause as MECHANISM MISSPECIFICATION (linear fit on nonlinear biology -> the 'invariant mechanism' is not
invariant across regimes). This swaps in the §27 NONLINEAR mechanism organ (tanh-basis structural equations)
and re-runs the identical protocol:
  TRAIN on observational only: causal_NL: T_hat = OLS(basis(parents_of_T)); correlational: OLS(T on all others)
  TEST on 5 held-out interventional do() regimes (real distribution shift): mean abs error of each predictor.
If the NONLINEAR causal predictor now BEATS correlation (where the linear one lost), mechanism fidelity is
confirmed as the deciding factor -> 强 restored on real biology by a better-specified mechanism. If it STILL
loses, the limit is deeper than misspecification. Also reports the linear baseline (§28) for the 3-way contrast.
VERIFY-DON'T-ASSERT on my own §28 diagnosis. Pure stdlib. NOT a freeze; real-data honest test."""
from __future__ import annotations

import json
import math
import statistics

from experiments.sachs_task import load_int, PROTEINS, INTERVENABLE, GROUND_TRUTH

N = len(PROTEINS)


def _parents():
    pa = {}
    for a, b in GROUND_TRUTH:
        pa.setdefault(PROTEINS.index(b), set()).add(PROTEINS.index(a))
    return {j: sorted(pa.get(j, set())) for j in range(N)}


def _basis(parent_vals):
    feats = list(parent_vals)
    feats += [math.tanh(2.0 * p) for p in parent_vals]
    feats.append(math.tanh(2.0 * sum(parent_vals)))
    return feats


def _ols(X, y, ridge=1e-6):
    if not X or not X[0]:
        return [statistics.mean(y)]
    d = len(X[0]) + 1
    Z = [[1.0] + row for row in X]
    A = [[sum(Z[r][i] * Z[r][j] for r in range(len(Z))) + (ridge if i == j else 0.0)
          for j in range(d)] for i in range(d)]
    b = [sum(Z[r][i] * y[r] for r in range(len(Z))) for i in range(d)]
    for col in range(d):
        piv = max(range(col, d), key=lambda r: abs(A[r][col]))
        A[col], A[piv] = A[piv], A[col]
        b[col], b[piv] = b[piv], b[col]
        p = A[col][col] or 1e-12
        for r in range(col + 1, d):
            f = A[r][col] / p
            for j in range(col, d):
                A[r][j] -= f * A[col][j]
            b[r] -= f * b[col]
    w = [0.0] * d
    for r in range(d - 1, -1, -1):
        w[r] = (b[r] - sum(A[r][j] * w[j] for j in range(r + 1, d))) / (A[r][r] or 1e-12)
    return w


def _pred(w, xs):
    if len(w) == 1:
        return w[0]
    return w[0] + sum(w[i + 1] * xs[i] for i in range(len(xs)))


def main():
    intdata = load_int()
    by_code = {}
    for vals, code in intdata:
        by_code.setdefault(code, []).append(vals)
    obs = by_code.get(0, [])
    cols = list(zip(*obs))
    means = [statistics.mean(c) for c in cols]
    sds = [statistics.pstdev(c) or 1.0 for c in cols]

    def zrow(r):
        return [(r[j] - means[j]) / sds[j] for j in range(N)]
    obsz = [zrow(r) for r in obs]
    pa = _parents()

    lin_w, nl_w, corr_w = {}, {}, {}
    for t in range(N):
        y = [r[t] for r in obsz]
        parents = pa[t]
        lin_w[t] = _ols([[r[p] for p in parents] for r in obsz], y)
        nl_w[t] = _ols([_basis([r[p] for p in parents]) for r in obsz], y) if parents else [statistics.mean(y)]
        others = [j for j in range(N) if j != t]
        corr_w[t] = _ols([[r[j] for j in others] for r in obsz], y)

    lin_all, nl_all, corr_all = [], [], []
    per_regime = {}
    for name, code in INTERVENABLE.items():
        rows = by_code.get(code, [])
        if len(rows) < 20:
            continue
        rowsz = [zrow(r) for r in rows]
        xi = PROTEINS.index(name)
        le, ne, ce = [], [], []
        for t in range(N):
            if t == xi:
                continue
            parents = pa[t]
            others = [j for j in range(N) if j != t]
            for r in rowsz:
                le.append(abs(_pred(lin_w[t], [r[p] for p in parents]) - r[t]))
                ne.append(abs(_pred(nl_w[t], _basis([r[p] for p in parents]) if parents else []) - r[t]))
                ce.append(abs(_pred(corr_w[t], [r[j] for j in others]) - r[t]))
        per_regime[f"do({name})"] = {"linear_causal_mae": round(statistics.mean(le), 3),
                                     "nonlinear_causal_mae": round(statistics.mean(ne), 3),
                                     "correlational_mae": round(statistics.mean(ce), 3)}
        lin_all += le
        nl_all += ne
        corr_all += ce

    lm, nm, cm = statistics.mean(lin_all), statistics.mean(nl_all), statistics.mean(corr_all)
    out = {"gate": "sachs-shift-nonlinear", "domain": "REAL Sachs, held-out do regimes (mechanism-fidelity test)",
           "n_regimes": len(per_regime), "per_regime": per_regime,
           "overall": {"linear_causal_mae": round(lm, 3), "nonlinear_causal_mae": round(nm, 3),
                       "correlational_mae": round(cm, 3)},
           "nonlinear_causal_beats_correlation": nm < cm,
           "nonlinear_beats_linear": nm < lm,
           "nonlinear_advantage_over_correlation": round(cm - nm, 3),
           "regimes_nonlinear_beats_corr": sum(1 for r in per_regime.values()
                                               if r["nonlinear_causal_mae"] < r["correlational_mae"])}
    if nm < cm:
        out["verdict"] = "MECHANISM-FIDELITY-RESTORES-强"
        out["finding"] = ("the §28 diagnosis is CONFIRMED: swapping the linear structural equation for a "
                          "NONLINEAR (tanh-basis) mechanism makes the causal predictor BEAT correlation under "
                          "real distribution shift (nl " + str(round(nm, 3)) + " < corr " + str(round(cm, 3)) +
                          "), where the linear causal lost (" + str(round(lm, 3)) + "). 强-value-prediction-"
                          "under-shift holds on REAL biology WHEN the mechanism is well-specified -> mechanism "
                          "fidelity is the deciding factor, exactly as §28 diagnosed. Honest scope: ground-truth "
                          "parents (not self-discovered); one real dataset.")
    else:
        out["verdict"] = "DEEPER-LIMIT-NOT-JUST-MISSPECIFICATION"
        out["finding"] = ("the §28 diagnosis is NOT sufficient: even a NONLINEAR (tanh-basis) mechanism does not "
                          "beat correlation under real distribution shift (nl " + str(round(nm, 3)) + " vs corr "
                          + str(round(cm, 3)) + "). The limit is deeper than linear-misspecification -- possible "
                          "causes: the tanh basis is still wrong for the true biology, latent confounders, "
                          "measurement, or the correlational model's flexibility. 强-value-prediction-under-shift "
                          "on real biology is NOT restored by this mechanism organ. Honest negative sustained.")
    open("experiments/sachs_shift_nonlinear.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
