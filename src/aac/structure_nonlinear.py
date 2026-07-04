"""structure_nonlinear — a PLUGGABLE nonlinear mechanism organ for the governed-discovery loop. RR-0046 §15
localized the domain-specific piece: the loop STRUCTURE is domain-independent, but the linear mechanism-fitter
(structure_consistency.fit_mechanisms / predict_do_means) is misspecified for nonlinear mechanisms. The goal's
architecture is 'organs compose, the loop is invariant' — so crossing to a nonlinear domain must be an ORGAN
SWAP, not a loop rebuild. This module is that swapped organ; the loop code stays byte-identical and simply
calls (fit_fn, predict_fn) here instead of the linear ones.

Fitter: each node regresses on its parents via a basis expansion linear-in-parameters (closed-form OLS,
pure stdlib): features = [p_i] + [tanh(2 p_i)] + [tanh(2 * sum_i p_i)], which represents tanh-saturated
mechanisms of a linear combination well enough to recover structure + interventional effect. Do-mean
prediction propagates parent MEANS through the fitted basis (mean-field; E[f(X)] ~= f(E[X])).

Additive: imports the frozen primitives (_ols, _topo) but modifies nothing. No frozen gate is touched."""
from __future__ import annotations

import math

from aac.structure_consistency import _ols, _topo, Exhausted  # noqa: F401 (Exhausted re-exported for callers)


def _basis(parent_vals: list) -> list:
    """features for a node from its parents' values: linear + per-parent tanh + tanh of the parent sum."""
    feats = list(parent_vals)
    feats += [math.tanh(2.0 * p) for p in parent_vals]
    feats.append(math.tanh(2.0 * sum(parent_vals)))
    return feats


def fit_mechanisms_nl(n: int, pa: dict, obs_rows: list) -> dict:
    """Per-node nonlinear mechanism: root -> (mean, [], 'root'); child -> (basis_weights, parents, 'nl')."""
    out = {}
    m = len(obs_rows)
    for j in range(n):
        parents = sorted(pa.get(j, ()))
        if not parents:
            out[j] = (sum(r[j] for r in obs_rows) / m, [], "root")
        else:
            X = [_basis([r[p] for p in parents]) for r in obs_rows]
            w = _ols(X, [r[j] for r in obs_rows])
            out[j] = (w, parents, "nl")


    return out


def predict_do_means_nl(n: int, pa: dict, mech: dict, k: int, c: float) -> list:
    """Predicted node means under do(k=c): clamp k, propagate parent MEANS through the fitted basis in topo order."""
    mean = [0.0] * n
    for j in _topo(n, pa):
        if j == k:
            mean[j] = c
            continue
        w, parents, typ = mech[j]
        if typ == "root":
            mean[j] = w
        else:
            feats = _basis([mean[p] for p in parents])
            mean[j] = w[0] + sum(w[i + 1] * feats[i] for i in range(len(feats)))
    return mean


def prune_nl(n: int, survivors: list, mechs: list, k: int, c: float, do_rows: list, tol: float) -> tuple:
    """Same fail-closed prune contract as structure_consistency.prune, but using the nonlinear predictor."""
    measured = [sum(r[j] for r in do_rows) / len(do_rows) for j in range(n)]
    keep, kill = [], []
    for i, (pa, mech) in enumerate(zip(survivors, mechs)):
        pred = predict_do_means_nl(n, pa, mech, k, c)
        (keep if max(abs(pred[j] - measured[j]) for j in range(n)) <= tol else kill).append(i)
    if not keep:
        raise Exhausted(f"all {len(survivors)} hypotheses refuted by do({k}) under nonlinear organ")
    return keep, kill
