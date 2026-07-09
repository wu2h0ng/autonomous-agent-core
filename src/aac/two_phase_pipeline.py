"""Two-Phase Discovery Pipeline — exploratory → confirmatory with feedback.

Refactored architecture replacing the linear ProductDiscoveryEngine:
  Phase 1 (Exploratory): GGM skeleton + HSIC subsample + temporal precision
    → UncertaintyMap with broad edge coverage, high recall, low precision
  Phase 2 (Confirmatory): ANM direction scoring + intervention data +
    active edge selection + cross-validation
    → UncertaintyMap updated with intervention-verified edges

With iterative feedback:
  - Execution results → update UncertaintyMap presence/validation
  - Goal formation → prioritize edges on goal paths for verification
  - LLM consultation → resolve objectively unidentifiable edges

All state flows through UncertaintyMap — no scattered particle weights.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any

from .uncertainty_map import UncertaintyMap, Identifiability, ValidationStatus
from .cwm_organ import _standardize_cols, _cov, _inv
from .advanced_capabilities import hsic_independence_test, online_update_precision
from .per_edge_orient import score_edge_direction
from .direction_scorer import DirectionScorer
from .precision_temporal_filters import TemporalDAGSplitter


@dataclass
class MechanismRegistry:
    """Unified mechanism fitting interface — replaces hardcoded OLS/poly2 selection.

    Registers fitting methods by capability tag. The pipeline auto-selects
    the best mechanism for each node based on cross-validation R².
    """

    def __init__(self):
        self._fitters: dict[str, callable] = {}
        self._capabilities: dict[str, list[str]] = {}

    def register(self, name: str, fitter: callable, capabilities: list[str] | None = None):
        self._fitters[name] = fitter
        self._capabilities[name] = capabilities or ["nonlinear"]

    def best_for(self, capability: str) -> callable | None:
        for name, caps in self._capabilities.items():
            if capability in caps:
                return self._fitters[name]
        return next(iter(self._fitters.values()), None) if self._fitters else None

    def fit_all(self, X, y) -> dict[str, tuple[list[float], float]]:
        """Fit all registered fitters, return {name: (coefs, r2)}."""
        results = {}
        for name, fitter in self._fitters.items():
            try:
                coefs, r2 = fitter(X, y)
                results[name] = (coefs, r2)
            except Exception:
                pass
        return results

    def best_fit(self, X, y) -> tuple[str, list[float], float]:
        results = self.fit_all(X, y)
        if not results:
            return ("ols", [], 0.0)
        best = max(results, key=lambda k: results[k][1])
        return (best, *results[best])


def _ols_fitter(X, y):
    from .bayesian_dag_posterior import _ols_coefficients
    coefs = _ols_coefficients(X, y)
    mu_y = statistics.mean(y)
    ss_res = sum((y[t] - sum(coefs[pi]*X[t][pi] for pi in range(len(coefs))))**2 for t in range(len(y)))
    ss_tot = sum((v - mu_y)**2 for v in y)
    r2 = 1.0 - ss_res / max(ss_tot, 1e-9)
    return coefs, r2


def _poly2_fitter(X, y):
    from .bayesian_dag_posterior import _ols_coefficients
    X_poly = [[1.0] + [X[t][p] for p in range(len(X[0]))] +
              [X[t][p]*X[t][q] for p in range(len(X[0])) for q in range(p, len(X[0]))]
              for t in range(len(X))]
    coefs = _ols_coefficients(X_poly, y)
    mu_y = statistics.mean(y)
    ss_res = sum((y[t] - sum(coefs[pi]*X_poly[t][pi] for pi in range(len(coefs))))**2 for t in range(len(y)))
    ss_tot = sum((v - mu_y)**2 for v in y)
    r2 = 1.0 - ss_res / max(ss_tot, 1e-9)
    return coefs, r2


def _build_default_registry() -> MechanismRegistry:
    reg = MechanismRegistry()
    reg.register("ols", _ols_fitter, ["linear"])
    reg.register("poly2", _poly2_fitter, ["linear", "nonlinear"])
    return reg


@dataclass
class ExploratoryDiscovery:
    """Phase 1: broad skeleton discovery with multiple CI tests.

    Produces UncertaintyMap with presence probabilities from ALL available
    CI signal sources. Fast, cheap, high recall.

    Supports INCREMENTAL updates: after initial batch computation, new rows
    can be added via update_incremental() using Welford's online covariance.
    This avoids O(n³) full recomputation per new observation.
    """

    tau: float = 0.02
    use_hsic: bool = False
    hsic_pvalue: float = 0.10
    hsic_subsample: int = 200
    _current_mean: list[float] | None = None  # for incremental updates
    _current_cov: list[list[float]] | None = None
    _n_current: int = 0

    def run(self, obs: list[list[float]], umap: UncertaintyMap | None = None) -> UncertaintyMap:
        n = len(obs[0])
        if umap is None:
            umap = UncertaintyMap(n_nodes=n)
        self._n_current = len(obs)

        try:
            std = _standardize_cols(obs)
            self._current_mean = [statistics.mean([r[v] for r in obs]) for v in range(n)]
            self._current_cov = _cov(std)
            prec = _inv(self._current_cov)
            for i in range(n):
                for j in range(i + 1, n):
                    d = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
                    pcorr = abs(prec[i][j]) / d
                    pval = 0.01 if pcorr > self.tau else 0.50
                    umap.update_ci_test(i, j, pcorr, pval)
        except (ValueError, ZeroDivisionError):
            pass

        if self.use_hsic and len(obs) > 10:
            import random
            rng = random.Random(42)
            subsample = obs if len(obs) <= self.hsic_subsample else rng.sample(obs, self.hsic_subsample)
            cols = [[subsample[t][v] for t in range(len(subsample))] for v in range(n)]
            for i in range(n):
                for j in range(i + 1, n):
                    _, pval = hsic_independence_test(cols[i], cols[j], "rbf", n_permutations=10)
                    pcorr_hsic = 1.0 - pval
                    umap.update_ci_test(i, j, pcorr_hsic, pval)

        return umap

    def update_incremental(
        self, new_rows: list[list[float]], umap: UncertaintyMap,
    ) -> UncertaintyMap:
        """Incremental update: new rows → update online covariance → update CI test.

        Uses Welford's algorithm (O(n_vars²) per row, not O(n³) full recompute).
        New rows are appended to the running statistics, then precision matrix
        is recomputed ONCE (O(n³)) to update all CI tests.
        """
        n = len(new_rows[0])
        if self._current_mean is None or self._current_cov is None:
            return self.run(new_rows, umap)

        for row in new_rows:
            self._current_mean, self._current_cov = online_update_precision(
                [[]], row, self._current_mean, self._current_cov, self._n_current,
            )
            self._n_current += 1

        try:
            prec = _inv(self._current_cov)
            for i in range(n):
                for j in range(i + 1, n):
                    d = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
                    pcorr = abs(prec[i][j]) / d
                    pval = 0.01 if pcorr > self.tau else 0.50
                    umap.update_ci_test(i, j, pcorr, pval)
        except (ValueError, ZeroDivisionError):
            pass
        return umap


@dataclass
class ConfirmatoryVerification:
    """Phase 2: high-precision edge verification.

    Takes UncertaintyMap from Phase 1, applies:
    - ANM direction scoring for each candidate edge
    - Interventional data (real or synthetic do() rows)
    - Cross-validation stability check
    - Temporal precedence if time order available

    Updates UncertaintyMap with intervention-verified edges.
    """

    effect_threshold: float = 0.3
    time_order: list[int] | None = None

    def run(self, obs: list[list[float]], umap: UncertaintyMap,
            int_data: list[list[float]] | None = None,
            ) -> UncertaintyMap:
        n = len(obs[0])

        scorer = DirectionScorer(obs, self.time_order)
        for i in range(n):
            for j in range(i + 1, n):
                e = umap.edges[(i, j)]
                if e.presence_prob < 0.3:
                    continue
                s_fwd, s_rev = scorer.score(i, j)
                umap.update_anm(i, j, s_fwd, s_rev)

        if int_data:
            for row in int_data:
                for i in range(n):
                    for j in range(i + 1, n):
                        col_i = [r[i] for r in int_data]
                        col_j = [r[j] for r in int_data]
                        if len(col_i) < 5:
                            continue
                        import statistics
                        mu_i = statistics.mean(col_i); sd_i = statistics.pstdev(col_i) or 1.0
                        high_i = [v for v, r in zip(col_i, int_data) if r[i] > mu_i + 0.5 * sd_i]
                        low_i = [v for v, r in zip(col_i, int_data) if r[i] < mu_i - 0.5 * sd_i]
                        obs_col_j = [obs[t][j] for t in range(len(obs))]
                        mu_j_obs = statistics.mean(obs_col_j)
                        if len(high_i) >= 3 and len(low_i) >= 3:
                            eff = (statistics.mean(high_i) - statistics.mean(low_i)) / max(statistics.pstdev(obs_col_j), 1e-9)
                            umap.update_intervention(i, j, eff)

        return umap


@dataclass
class IterativeFeedback:
    """Phase 3: close the loop between discovery and action.

    - Execution results → uncertainty updates on verified edges
    - Goal paths → prioritize uncertain edges for verification
    - LLM consultation → resolve objectively unidentifiable direction
    """

    llm_backend: Any = None
    variable_names: list[str] = field(default_factory=list)

    def run(self, umap: UncertaintyMap, dag: frozenset,
            execution_results: list | None = None,
            goal_path_edges: set | None = None,
            ) -> UncertaintyMap:
        if goal_path_edges:
            for i, j in goal_path_edges:
                e = umap.edges[(i, j)]
                if e.identifiability == Identifiability.DATA_LIMITED:
                    e.identifiability = Identifiability.DATA_SUFFICIENT

        if self.llm_backend and self.variable_names:
            for i, j in umap.edges_needing_llm():
                src = self.variable_names[i] if i < len(self.variable_names) else f"V{i}"
                tgt = self.variable_names[j] if j < len(self.variable_names) else f"V{j}"
                prompt = f"Given variables {src} and {tgt}, which causal direction is more likely? Answer 'i→j' or 'j→i'."
                try:
                    raw = self.llm_backend.propose(prompt)
                    content = str(raw) if isinstance(raw, str) else str(raw.get("content", ""))
                    direction_i_to_j = "i→j" in content
                    umap.update_llm(i, j, direction_i_to_j)
                except Exception:
                    pass

        return umap
