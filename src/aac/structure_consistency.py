"""StructureConsistency — the AGDE-1 verifier: hypothesis-space PRUNE operator over do()-regime data
(typed-routing law: interventional information enters as a discrete refutation test, never as pooled
likelihood — the RR-0044 type fix for the 5b failure). Pure stdlib, deterministic (closed-form OLS),
verify-only, fail-closed.

For hypothesis h (a parent map): fit each node's linear mechanism on OBSERVATIONAL data by ridge-OLS
(closed form; ridge 1e-6 disclosed, numerical only). Under do(k=c), h predicts node means by topological
propagation (intervened node clamped; non-descendants keep their observational means via the fitted
intercepts). h SURVIVES a do-regime dataset iff max-node |predicted mean - measured mean| <= tol.
Zero survivors -> EXHAUSTED (fail-closed: the caller must surface UNIDENTIFIED, never coerce a winner).
Tolerance is INJECTED (calibrated pre-freeze on disjoint seeds), never hard-coded."""
from __future__ import annotations


class Exhausted(Exception):
    """All hypotheses refuted — fail-closed; the loop must record UNIDENTIFIED, never pick a winner."""


def _ols(X: list[list[float]], y: list[float], ridge: float = 1e-6) -> list[float]:
    """Closed-form ridge OLS with intercept: returns [b0, w...]. Gaussian elimination, deterministic."""
    Z = [[1.0] + row for row in X]
    d = len(Z[0])
    A = [[sum(Z[r][i] * Z[r][j] for r in range(len(Z))) + (ridge if i == j else 0.0)
          for j in range(d)] for i in range(d)]
    b = [sum(Z[r][i] * y[r] for r in range(len(Z))) for i in range(d)]
    for col in range(d):                          # partial-pivot elimination
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


def fit_mechanisms(n: int, pa: dict[int, frozenset[int]], obs_rows: list[list[float]]) -> dict[int, tuple]:
    """Per-node (intercept, {parent: weight}) fitted on observational data under hypothesis pa."""
    out = {}
    for j in range(n):
        parents = sorted(pa.get(j, ()))
        if not parents:
            m = sum(r[j] for r in obs_rows) / len(obs_rows)
            out[j] = (m, {})
        else:
            w = _ols([[r[p] for p in parents] for r in obs_rows], [r[j] for r in obs_rows])
            out[j] = (w[0], {p: w[i + 1] for i, p in enumerate(parents)})
    return out


def _topo(n: int, pa: dict[int, frozenset[int]]) -> list[int]:
    indeg = {j: len(pa.get(j, ())) for j in range(n)}
    ch: dict[int, list[int]] = {}
    for j, ps in pa.items():
        for p in ps:
            ch.setdefault(p, []).append(j)
    order, stack = [], sorted(j for j in range(n) if indeg[j] == 0)
    while stack:
        u = stack.pop(0)
        order.append(u)
        for v in sorted(ch.get(u, ())):
            indeg[v] -= 1
            if indeg[v] == 0:
                stack.append(v)
    return order


def predict_do_means(n: int, pa: dict[int, frozenset[int]], mech: dict[int, tuple],
                     k: int, c: float) -> list[float]:
    """h's predicted node means under do(k=c): clamp k, propagate fitted linear mechanisms in topo order."""
    mean = [0.0] * n
    for j in _topo(n, pa):
        if j == k:
            mean[j] = c
        else:
            b0, ws = mech[j]
            mean[j] = b0 + sum(w * mean[p] for p, w in ws.items())
    return mean


def prune(n: int, survivors: list[dict[int, frozenset[int]]], mechs: list[dict[int, tuple]],
          k: int, c: float, do_rows: list[list[float]], tol: float
          ) -> tuple[list[int], list[int]]:
    """Returns (surviving indices, killed indices) into the CURRENT survivor list. Fail-closed on zero."""
    measured = [sum(r[j] for r in do_rows) / len(do_rows) for j in range(n)]
    keep, kill = [], []
    for i, (pa, mech) in enumerate(zip(survivors, mechs)):
        pred = predict_do_means(n, pa, mech, k, c)
        (keep if max(abs(pred[j] - measured[j]) for j in range(n)) <= tol else kill).append(i)
    if not keep:
        raise Exhausted(f"all {len(survivors)} hypotheses refuted by do({k}) at tol={tol}")
    return keep, kill
