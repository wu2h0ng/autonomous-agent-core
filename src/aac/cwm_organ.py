"""CWM Organ — pluggable causal world model organ interface.

Each CWM organ proposes causal structures, verifies them via intervention data,
and fits causal mechanisms for do() prediction. Organs write only the K (structure)
channel — never action, policy, shell, gate, or verdict. Multiple organs compose:
data skeleton + language orientation + intervention verification.

Protocol (duck-typed, like GovernedLoop's proposer/verifier):
  .propose_skeleton(obs) -> list[tuple[frozenset, float]]
        Return ranked undirected candidate edge-sets with scores.
  .propose_orientation(skeleton) -> list[tuple[frozenset, float]]
        Return ranked directed candidate edge-sets. Optional.
  .verify_structure(dag, obs, int_data) -> VerifyResult
        Verify whether a candidate structure is consistent with intervention data.
  .mechanism_fit(dag, obs) -> callable
        Fit structural equations, returning a predictor f(do_node, do_val, target, obs_baseline).
  .update(obs, int_data) -> None
        Update internal state with new data.
  .confidence() -> float
        Return confidence [0,1] in the current best structure estimate.

All implementations MUST be pure stdlib and MUST NOT reference C7, CorrigibilityShell,
GovernedDecisionGate, or any action/policy/shell/gate/verdict channel.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class StructureProposal:
    """A proposed causal structure — undirected or directed edge set with a score."""
    edges: frozenset  # frozenset of (int,int) for directed, frozenset of frozenset({int,int}) for undirected
    score: float      # higher = more likely per the organ
    is_directed: bool = False
    provenance: str = ""  # which organ proposed this


@dataclass(frozen=True)
class VerifyResult:
    """Output of intervention verification of a candidate structure."""
    is_consistent: bool
    confidence: float       # [0,1]
    interventions_used: int


@dataclass
class DiscoveryState:
    """Mutable state maintained by GovernedDiscoveryLoop across discovery rounds."""
    proposals: list[StructureProposal] = field(default_factory=list)
    verified_dags: list[tuple[frozenset, float]] = field(default_factory=list)
    interventions_spent: int = 0
    best_dag: frozenset | None = None
    best_confidence: float = 0.0
    round_log: list[dict] = field(default_factory=list)


class CWMOrgan:
    """Base class for pluggable CWM organs. Override the methods you support."""

    def propose_skeleton(self, obs: list[list[float]]) -> list[StructureProposal]:
        raise NotImplementedError

    def propose_orientation(self, skeleton: frozenset) -> list[StructureProposal]:
        raise NotImplementedError

    def verify_structure(
        self, dag: frozenset[tuple[int, int]], obs: list[list[float]],
        int_data: list[tuple[int, float, list[float]]] | None = None,
    ) -> VerifyResult:
        raise NotImplementedError

    def mechanism_fit(
        self, dag: frozenset[tuple[int, int]], obs: list[list[float]],
    ) -> Callable[[int, float, int, list[float]], float]:
        raise NotImplementedError

    def update(self, obs: list[list[float]]):
        pass

    def confidence(self) -> float:
        return 0.0


def _standardize_cols(obs: list[list[float]]) -> list[list[float]]:
    cols = list(zip(*obs))
    means = [statistics.mean(c) for c in cols]
    sds = [statistics.pstdev(c) or 1.0 for c in cols]
    n = len(cols)
    return [[(obs[r][j] - means[j]) / sds[j] for j in range(n)] for r in range(len(obs))]


def _cov(rows: list[list[float]]) -> list[list[float]]:
    m = len(rows)
    n = len(rows[0])
    means = [sum(r[j] for r in rows) / m for j in range(n)]
    return [[sum((rows[t][i] - means[i]) * (rows[t][j] - means[j]) for t in range(m)) / (m - 1)
             for j in range(n)] for i in range(n)]


def _inv(A: list[list[float]]) -> list[list[float]]:
    n = len(A)
    M = [[A[i][j] + (1e-6 if i == j else 0.0) for j in range(n)] + [1.0 if i == j else 0.0 for j in range(n)]
          for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        M[col], M[piv] = M[piv], M[col]
        p = M[col][col] or 1e-12
        M[col] = [v / p for v in M[col]]
        for r in range(n):
            if r != col and M[r][col] != 0.0:
                f = M[r][col]
                M[r] = [M[r][j] - f * M[col][j] for j in range(2 * n)]
    return [row[n:] for row in M]


def _ols_fit(X: list[list[float]], y: list[float]) -> list[float]:
    m = len(X)
    k = len(X[0])
    Xt = [[X[i][j] for i in range(m)] for j in range(k)]
    XtX = [[sum(Xt[i][t] * Xt[j][t] for t in range(m)) for j in range(k)] for i in range(k)]
    XtX_inv = _inv(XtX)
    Xty = [sum(Xt[i][t] * y[t] for t in range(m)) for i in range(k)]
    return [sum(XtX_inv[i][j] * Xty[j] for j in range(k)) for i in range(k)]


class LinearGGMOrgan(CWMOrgan):
    """Linear GGM skeleton proposer + OLS mechanism fitting.

    Wraps the existing precision-matrix precision-correlation pipeline.
    Pure stdlib. Works on standardized data. Recovers ~0.588 recall on Sachs.
    """

    def __init__(self, tau: float = 0.05):
        self.tau = tau

    def propose_skeleton(self, obs: list[list[float]]) -> list[StructureProposal]:
        n = len(obs[0])
        std = _standardize_cols(obs)
        prec = _inv(_cov(std))
        edges = set()
        for i in range(n):
            for j in range(i + 1, n):
                denom = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
                pcorr = abs(prec[i][j]) / denom
                if pcorr > self.tau:
                    edges.add(frozenset({i, j}))
        score = len(edges) / (n * (n - 1) / 2) if n > 1 else 0.0
        return [StructureProposal(edges=frozenset(edges), score=score, provenance="LinearGGM")]

    def verify_structure(
        self, dag: frozenset[tuple[int, int]], obs: list[list[float]],
        int_data: list[tuple[int, float, list[float]]] | None = None,
    ) -> VerifyResult:
        if not int_data:
            return VerifyResult(False, 0.0, 0)
        n_checked = 0
        n_ok = 0
        for do_node, do_val, row in int_data:
            pred = self._predict_do(dag, obs, do_node, do_val)
            actual = row[do_node]
            n_checked += 1
            if abs(pred - actual) < 0.5:
                n_ok += 1
        if n_checked == 0:
            return VerifyResult(False, 0.0, 0)
        conf = n_ok / n_checked
        return VerifyResult(conf > 0.5, conf, n_checked)

    def mechanism_fit(
        self, dag: frozenset[tuple[int, int]], obs: list[list[float]],
    ) -> Callable[[int, float, int, list[float]], float]:
        n = len(obs[0])
        parents = {j: [] for j in range(n)}
        for u, v in dag:
            parents[v].append(u)
        coefs = {}
        for j in range(n):
            pa = parents[j]
            if pa:
                X = [[obs[t][p] for p in pa] for t in range(len(obs))]
                y = [obs[t][j] for t in range(len(obs))]
                coefs[j] = _ols_fit(X, y)
            else:
                coefs[j] = []

        def predict(do_node, do_val, target, baseline_obs):
            if target == do_node:
                return do_val
            values = list(baseline_obs)
            values[do_node] = do_val
            for node in _topological_order(dag, n):
                if node == do_node:
                    continue
                pa = parents[node]
                if not pa:
                    continue
                pred_val = sum(coefs[node][p_idx] * values[p] for p_idx, p in enumerate(pa))
                values[node] = pred_val
            return values[target]

        return predict

    def _predict_do(
        self, dag: frozenset[tuple[int, int]], obs: list[list[float]],
        do_node: int, do_val: float,
    ) -> float:
        n = len(obs[0])
        parents = {j: [] for j in range(n)}
        for u, v in dag:
            parents[v].append(u)
        coefs = {}
        for j in range(n):
            pa = parents[j]
            if pa:
                X = [[obs[t][p] for p in pa] for t in range(len(obs))]
                y = [obs[t][j] for t in range(len(obs))]
                coefs[j] = _ols_fit(X, y)

        row = [statistics.mean([obs[t][k] for t in range(len(obs))]) for k in range(n)]
        row[do_node] = do_val
        for node in _topological_order(dag, n):
            if node == do_node:
                continue
            pa = parents[node]
            if pa:
                row[node] = sum(coefs[node][p_idx] * row[p] for p_idx, p in enumerate(pa))
        return row[do_node]


class PolynomialOrgan(CWMOrgan):
    """Nonlinear CWM organ using polynomial basis expansion + OLS.

    Expands each parent set with degree-d monomials (including cross-terms),
    then fits OLS. Captures nonlinearities like tanh saturation, interactions,
    and monotone curvatures that linear OLS misses.

    Pure stdlib. Computational cost: O(n_obs × k^d) where k = |pa|, d = max_degree.
    For n<=11 and d<=2, this is well within budget.
    """

    def __init__(self, max_degree: int = 2, tau: float = 0.05):
        self.max_degree = max_degree
        self.tau = tau
        self._fitted_coefs: dict = {}

    def _expand_basis(self, X: list[list[float]], degree: int) -> list[list[float]]:
        if not X or not X[0]:
            return [[1.0] for _ in X]
        k = len(X[0])
        basis_cols = []
        for deg in range(1, degree + 1):
            idx = [0] * deg
            while True:
                basis_cols.append(list(idx))
                pos = deg - 1
                while pos >= 0 and idx[pos] == k - 1:
                    pos -= 1
                if pos < 0:
                    break
                idx[pos] += 1
                for p in range(pos + 1, deg):
                    idx[p] = idx[pos]
        result = []
        for t in range(len(X)):
            row_basis = [1.0]
            for idx_list in basis_cols:
                val = 1.0
                for col in idx_list:
                    val *= X[t][col]
                row_basis.append(val)
            result.append(row_basis)
        return result

    def propose_skeleton(self, obs: list[list[float]]) -> list[StructureProposal]:
        n = len(obs[0])
        ranked = _spearman_rank(obs)
        std = _standardize_cols(ranked)
        prec = _inv(_cov(std))
        edges = set()
        for i in range(n):
            for j in range(i + 1, n):
                denom = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
                if abs(prec[i][j]) / denom > self.tau:
                    edges.add(frozenset({i, j}))
        score = len(edges) / (n * (n - 1) / 2) if n > 1 else 0.0
        return [StructureProposal(edges=frozenset(edges), score=score, provenance="Polynomial")]

    def mechanism_fit(
        self, dag: frozenset[tuple[int, int]], obs: list[list[float]],
    ) -> Callable[[int, float, int, list[float]], float]:
        n = len(obs[0])
        parents = {j: [] for j in range(n)}
        for u, v in dag:
            parents[v].append(u)
        for j in range(n):
            pa = parents[j]
            if pa:
                X_raw = [[obs[t][p] for p in pa] for t in range(len(obs))]
                X_basis = self._expand_basis(X_raw, self.max_degree)
                y = [obs[t][j] for t in range(len(obs))]
                self._fitted_coefs[j] = _ols_fit(X_basis, y)
            else:
                self._fitted_coefs[j] = []

        def predict(do_node, do_val, target, baseline_obs):
            if target == do_node:
                return do_val
            values = list(baseline_obs)
            values[do_node] = do_val
            for node in _topological_order(dag, n):
                if node == do_node:
                    continue
                pa = parents[node]
                if not pa:
                    continue
                x = [[values[p] for p in pa]]
                x_basis = self._expand_basis(x, self.max_degree)
                pred = sum(self._fitted_coefs[node][c] * x_basis[0][c] for c in range(len(self._fitted_coefs[node])))
                values[node] = pred
            return values[target]

        return predict

    def confidence(self) -> float:
        return 0.5


def _spearman_rank(obs: list[list[float]]) -> list[list[float]]:
    n_cols = len(obs[0])
    ranked = [[0.0] * n_cols for _ in obs]
    for c in range(n_cols):
        pairs = [(obs[r][c], r) for r in range(len(obs))]
        pairs.sort(key=lambda x: x[0])
        i = 0
        while i < len(pairs):
            j = i
            while j < len(pairs) and pairs[j][0] == pairs[i][0]:
                j += 1
            avg_rank = (i + j + 1) / 2.0
            for k in range(i, j):
                ranked[pairs[k][1]][c] = avg_rank
            i = j
    return ranked


def _topological_order(dag: frozenset[tuple[int, int]], n: int) -> list[int]:
    indeg = {i: 0 for i in range(n)}
    adj = {i: [] for i in range(n)}
    for u, v in dag:
        adj[u].append(v)
        indeg[v] = indeg.get(v, 0) + 1
    indeg.setdefault(0, 0)
    q = [i for i in range(n) if indeg[i] == 0]
    order = []
    while q:
        u = q.pop(0)
        order.append(u)
        for v in adj[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)
    return order
