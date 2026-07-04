"""structure_banded — REJECTED CALIBRATION, preserved as an honest negative (like the v0 RelevanceField
baseline). Attempted uncertainty-aware PRUNE band for the big-n false-rejection. It propagates each node's
INDIVIDUAL-OBSERVATION residual variance, which is the wrong quantity: the prune compares two MEANS, so the
band must carry the PREDICTION-MEAN uncertainty (leverage-aware resid_var * x0'(X'X)^-1 x0), not the
per-observation noise. As written the 3-sigma band is ~2.57 (vs the ~0.9 the tol-sweep wanted) -> it keeps
every hypothesis alive and identifies NOTHING (id 0.0, truth_alive 1.0; see bign_banded_fix.result.json).
Root finding (bign_dip_diagnosis + bign_banded_fix): the dip is a genuine SIGNAL-TO-NOISE limit — under
do(k=c=2.0) the truth's do-prediction misses by ~1.0 from CLAMP-AMPLIFIED finite-sample coefficient error
(high leverage at 2 sigma), rivalling the inter-hypothesis discrimination signal. The robust fix is to shrink
coefficient error (more n_obs: id 0.667->0.875 at fixed tol as n_obs 300->2400; or a smaller clamp), NOT a
wider band. A leverage-aware prediction-mean band could help at the margin but is bounded by intrinsic SNR.
Kept in-tree so the rejected approach is not silently re-attempted. DO NOT wire into e2e_agent.

'The band carries the uncertainty.' A hypothesis is refuted by a do-regime dataset only if its prediction
misses the measurement by more than the propagated uncertainty of that prediction. Two additive sources:
  - prediction variance: each node's OLS residual variance, propagated through the topo order under do()
    (intervened node clamped -> zero variance; child var = resid_var + sum_parents w^2 * parent_var);
  - measurement standard error: sd(do_rows[:,j]) / sqrt(n_do) of the measured mean.
band_j = Z * sqrt(pred_var_j + measured_se_j^2), Z = 3.0 (pre-committed 3-sigma; a structural constant, not
an arena-tuned knob). Fail-closed identical to `prune`: zero survivors -> Exhausted.

This module is ADDITIVE — it imports the frozen primitives from structure_consistency and does NOT modify
them, so every frozen e2e gate that calls the original `prune` is byte-for-byte unaffected."""
from __future__ import annotations

import math

from aac.structure_consistency import _ols, _topo, predict_do_means, Exhausted

Z_SIGMA = 3.0   # pre-committed 3-sigma band multiplier (structural, not arena-tuned)


def fit_residual_stds(n: int, pa: dict, obs_rows: list) -> dict:
    """Per-node residual std of the SAME ridge-OLS fit `fit_mechanisms` uses (root node -> marginal std)."""
    out = {}
    m = len(obs_rows)
    for j in range(n):
        parents = sorted(pa.get(j, ()))
        if not parents:
            mean = sum(r[j] for r in obs_rows) / m
            var = sum((r[j] - mean) ** 2 for r in obs_rows) / max(1, m - 1)
            out[j] = math.sqrt(var)
        else:
            w = _ols([[r[p] for p in parents] for r in obs_rows], [r[j] for r in obs_rows])
            resid = [r[j] - (w[0] + sum(w[i + 1] * r[p] for i, p in enumerate(parents))) for r in obs_rows]
            dof = max(1, m - len(parents) - 1)
            out[j] = math.sqrt(sum(e * e for e in resid) / dof)
    return out


def predict_do_var(n: int, pa: dict, mech: dict, resid_stds: dict, k: int) -> list:
    """Propagated prediction variance per node under do(k): clamp k (var 0), accumulate mechanism noise."""
    var = [0.0] * n
    for j in _topo(n, pa):
        if j == k:
            var[j] = 0.0
        else:
            _b0, ws = mech[j]
            var[j] = resid_stds.get(j, 0.0) ** 2 + sum((w * w) * var[p] for p, w in ws.items())
    return var


def prune_banded(n: int, survivors: list, mechs: list, resid_stds_list: list,
                 k: int, c: float, do_rows: list, z: float = Z_SIGMA, base_tol: float = 0.0
                 ) -> tuple:
    """Uncertainty-aware prune. Survive iff every node's |pred-measured| <= base_tol + z*sqrt(predvar+se^2).
    base_tol defaults to 0.0 (pure uncertainty band); expose it only as a model-misspecification floor."""
    m = len(do_rows)
    measured = [sum(r[j] for r in do_rows) / m for j in range(n)]
    meas_var = [(sum((r[j] - measured[j]) ** 2 for r in do_rows) / max(1, m - 1)) / m for j in range(n)]
    keep, kill = [], []
    for i, (pa, mech, rstd) in enumerate(zip(survivors, mechs, resid_stds_list)):
        pred = predict_do_means(n, pa, mech, k, c)
        pvar = predict_do_var(n, pa, mech, rstd, k)
        ok = all(abs(pred[j] - measured[j]) <= base_tol + z * math.sqrt(pvar[j] + meas_var[j])
                 for j in range(n))
        (keep if ok else kill).append(i)
    if not keep:
        raise Exhausted(f"all {len(survivors)} hypotheses refuted by do({k}) under uncertainty band")
    return keep, kill
