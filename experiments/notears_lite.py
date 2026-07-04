"""NOTEARS-lite — pure-stdlib continuous structure PROPOSER (RR-0045 role reassignment; RR-0044 typed
routing: the continuous W-fit is type-correct as a candidate GENERATOR, type-violating as a structure
DECIDER — both facts measured in the 2026-07-04 spike: thresholded F1 unstable 0.09-0.79 while
recall@2d stable 0.79-0.96). logdet acyclicity (DAGMA-style), plain gradient descent, deterministic."""
from __future__ import annotations


def _inv(M):
    d = len(M)
    A = [row[:] + [1.0 if i == j else 0.0 for j in range(d)] for i, row in enumerate(M)]
    for c in range(d):
        p = max(range(c, d), key=lambda r: abs(A[r][c]))
        A[c], A[p] = A[p], A[c]
        pv = A[c][c] or 1e-12
        A[c] = [v / pv for v in A[c]]
        for r in range(d):
            if r != c and A[r][c]:
                f = A[r][c]
                A[r] = [A[r][k] - f * A[c][k] for k in range(2 * d)]
    return [row[d:] for row in A]


def fit_w(X, iters=150, rounds=2, lam=0.02, s=1.5, lr=0.05):
    """Returns the fitted weighted adjacency W (row=parent, col=child). Deterministic (zero init)."""
    n, d = len(X), len(X[0])
    W = [[0.0] * d for _ in range(d)]
    XtX = [[sum(X[i][a] * X[i][b] for i in range(n)) / n for b in range(d)] for a in range(d)]
    mu = 0.1
    for _ in range(rounds):
        for _ in range(iters):
            M = [[(s if i == j else 0.0) - W[i][j] * W[i][j] for j in range(d)] for i in range(d)]
            Minv = _inv(M)
            for a in range(d):
                for b in range(d):
                    if a == b:
                        continue
                    ls = -XtX[a][b] + sum(XtX[a][k] * W[k][b] for k in range(d))
                    gh = 2.0 * W[a][b] * Minv[b][a]
                    g = ls + mu * gh + lam * (1 if W[a][b] > 0 else (-1 if W[a][b] < 0 else 0))
                    W[a][b] -= lr * g
        mu *= 10
    return W


def top_edges(W, k):
    """Directed candidate edges ranked by |W|, top-k. The PROPOSER output."""
    d = len(W)
    scored = sorted(((abs(W[a][b]), (a, b)) for a in range(d) for b in range(d) if a != b), reverse=True)
    return [e for _, e in scored[:k]]
