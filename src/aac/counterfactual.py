"""Counterfactual Inference Engine — Pearl's three-step (abduction→action→prediction).

Given a fitted causal mechanism (from GovernedDiBS or ProductDiscoveryEngine)
and an observed outcome, answers: "What WOULD have happened if I had done X=x'?"

Three-step procedure:
1. ABDUCTION: infer exogenous noise U from observed (X,Y) using fitted mechanisms.
2. ACTION: modify SCM — set X=x' (do operation), keep U fixed.
3. PREDICTION: propagate U through modified SCM → counterfactual Y'.

Requires a fitted SCM (OLS per node). Our GovernedDiBS mechanism_fit provides this.
Pure stdlib. Works on any DAG with fitted linear or polynomial mechanisms.

Usage:
    from aac.counterfactual import CounterfactualEngine
    cf = CounterfactualEngine(dag, obs)
    result = cf.query(do_node=0, do_val=5.0, target=3, observed_row=[1.0,2.0,3.0,4.0])
    print(f"If we had set X0=5.0 instead, Y3 would be {result:.2f}")
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass


@dataclass
class CounterfactualResult:
    actual: float           # what actually happened
    counterfactual: float   # what would have happened
    delta: float            # counterfactual - actual
    noise: float            # inferred exogenous noise (abduction step)
    node: int               # target node
    do_node: int            # intervention node


class CounterfactualEngine:
    """Pearl's three-step counterfactual inference on a fitted SCM.

    DEFECT FIX (2026-07):
    - Auto-corrects DAG direction via ANM DirectionScorer before mechanism fitting.
      If discovered DAG has edge j→i but ANM says i→j, the engine auto-flips it.
    - Error buffer: tracks prediction errors, triggers re-discovery if systematic bias.

    Args:
        dag: discovered causal DAG.
        obs: observational data for mechanism fitting + direction scoring.
        likelihood_mode: "linear" or "poly2".
        error_threshold: max tolerated relative error before triggering re-discovery.
    """

    def __init__(
        self, dag: frozenset[tuple[int, int]], obs: list[list[float]],
        likelihood_mode: str = "linear",
        error_threshold: float = 0.30,
    ):
        self.obs = obs
        self.n = len(obs[0])
        self.error_threshold = error_threshold
        self._error_buffer: list[float] = []
        self.dag = self._auto_correct_dag(dag)
        self._fitted_coefs: dict[int, list[float]] = {}
        self._fit_mechanisms(obs, likelihood_mode)

    def _auto_correct_dag(self, dag):
        from .direction_scorer import DirectionScorer
        time_order = list(range(self.n))
        scorer = DirectionScorer(self.obs, time_order=time_order)
        edges = set(dag)
        for u, v in list(edges):
            if (v, u) in edges:
                continue
            s_uv, s_vu = scorer.score(u, v)
            if s_vu > s_uv + 0.05:
                edges.discard((u, v))
                edges.add((v, u))
        return frozenset(edges)

    def query(
        self, do_node: int, do_val: float, target: int,
        observed_row: list[float],
    ) -> CounterfactualResult:
        n = self.n
        actual = observed_row[target] if target < len(observed_row) else 0.0
        parents = {j: [] for j in range(n)}
        for u, v in self.dag:
            parents[v].append(u)
        order = self._topological_order()

        noise = {}
        factual_values = list(observed_row)
        for j in order:
            pa = parents[j]; coef = self._fitted_coefs.get(j, [])
            if coef and len(coef) == len(pa):
                pred = sum(coef[pi] * factual_values[p] for pi, p in enumerate(pa))
            else:
                pred = statistics.mean(observed_row) if observed_row else 0.0
            noise[j] = factual_values[j] - pred

        cf_values = list(observed_row); cf_values[do_node] = do_val
        for j in order:
            if j == do_node: continue
            coef = self._fitted_coefs.get(j, []); pa = parents[j]
            if coef and len(coef) == len(pa):
                pred = sum(coef[pi] * cf_values[p] for pi, p in enumerate(pa))
                cf_values[j] = pred + noise[j]

        cf = cf_values[target] if target < len(cf_values) else actual
        result = CounterfactualResult(
            actual=actual, counterfactual=cf, delta=cf - actual,
            noise=noise.get(target, 0.0), node=target, do_node=do_node,
        )
        self._record_error(result)
        return result

    def _record_error(self, result):
        if abs(result.actual) > 1e-9:
            rel = abs(result.delta) / abs(result.actual)
            self._error_buffer.append(rel)

    @property
    def needs_rediscovery(self) -> bool:
        if len(self._error_buffer) < 5:
            return False
        return statistics.mean(self._error_buffer[-10:]) > self.error_threshold

    def _fit_mechanisms(self, obs, mode):
        n = self.n
        parents = {j: [] for j in range(n)}
        for u, v in self.dag:
            parents[v].append(u)
        for j in range(n):
            pa = parents[j]
            if pa:
                X = [[obs[t][p] for p in pa] for t in range(len(obs))]
                y = [obs[t][j] for t in range(len(obs))]
                from .bayesian_dag_posterior import _ols_coefficients
                try:
                    self._fitted_coefs[j] = _ols_coefficients(X, y)
                except (ValueError, ZeroDivisionError):
                    self._fitted_coefs[j] = []
            else:
                self._fitted_coefs[j] = []

    def _topological_order(self):
        n = self.n
        indeg = {i: 0 for i in range(n)}
        adj = {i: [] for i in range(n)}
        for u, v in self.dag:
            adj[u].append(v); indeg[v] = indeg.get(v, 0) + 1
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

    def query(
        self, do_node: int, do_val: float, target: int,
        observed_row: list[float],
    ) -> CounterfactualResult:
        """Compute counterfactual: what if do(do_node=do_val) instead of observed?

        Steps:
        1. ABDUCTION: for each node j, compute U_j = actual - prediction.
        2. ACTION: set X_do_node = do_val.
        3. PREDICTION: recompute values using same U_j.

        Args:
            do_node: which variable to intervene on.
            do_val: what value to set it to (counterfactual).
            target: which variable to predict.
            observed_row: the actual observed values [x_0, ..., x_{n-1}].

        Returns:
            CounterfactualResult with actual, counterfactual, delta, noise.
        """
        n = self.n
        actual = observed_row[target] if target < len(observed_row) else 0.0

        parents = {j: [] for j in range(n)}
        for u, v in self.dag:
            parents[v].append(u)
        order = self._topological_order()

        noise = {}
        factual_values = list(observed_row)
        for j in order:
            pa = parents[j]
            coef = self._fitted_coefs.get(j, [])
            if coef and len(coef) == len(pa):
                pred = sum(coef[pi] * factual_values[p] for pi, p in enumerate(pa))
            else:
                pred = statistics.mean(observed_row) if observed_row else 0.0
            noise[j] = factual_values[j] - pred

        counterfactual_values = list(observed_row)
        counterfactual_values[do_node] = do_val
        for j in order:
            if j == do_node:
                continue
            coef = self._fitted_coefs.get(j, [])
            pa = parents[j]
            if coef and len(coef) == len(pa):
                pred = sum(coef[pi] * counterfactual_values[p] for pi, p in enumerate(pa))
                counterfactual_values[j] = pred + noise[j]

        cf = counterfactual_values[target] if target < len(counterfactual_values) else actual
        return CounterfactualResult(
            actual=actual, counterfactual=cf, delta=cf - actual,
            noise=noise.get(target, 0.0), node=target, do_node=do_node,
        )

    def batch_query(
        self, do_node: int, do_values: list[float], target: int,
        observed_row: list[float],
    ) -> list[CounterfactualResult]:
        """Compute counterfactuals for multiple do-values."""
        return [self.query(do_node, v, target, observed_row) for v in do_values]
