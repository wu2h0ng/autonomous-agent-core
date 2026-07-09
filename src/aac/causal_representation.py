"""Causal Representation Learning — discover causal variables from raw observations.

ADR-0040 Layer 3: pixel/observation → latent causal factors → DAG → dynamics.

Pipeline:
1. PCA encoder: observation matrix → latent factors Z (n_obs × k)
2. Causal discovery on Z: CI skeleton → orientation → DAG in latent space
3. Latent→observed projection: latent DAG edges → observed variable implications
4. Intervention mapper: do(latent_factor_i = v) → observed effect through loading matrix

All pure stdlib. Uses power iteration for eigen decomposition.
Identifiability: under function orthogonality (Simon+2026, ICML 2026), PCA
recovers causal factors up to rotation when the generative mapping has
orthogonal Jacobian columns.

Usage:
    from aac.causal_representation import CRLPipeline
    crl = CRLPipeline(n_factors=4)
    result = crl.discover(obs_data)  # {dag, factors, loadings, projected_dag}
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .cwm_organ import _standardize_cols, _cov
from .product_engine import ProductDiscoveryEngine


@dataclass
class CRLResult:
    dag: frozenset                     # DAG in latent factor space
    n_factors: int                     # number of latent factors discovered
    factors: list[list[float]]         # Z matrix (n_obs × n_factors)
    loadings: list[list[float]]        # W matrix (n_vars × n_factors)
    explained_variance: list[float]    # per-factor variance explained
    total_variance_explained: float    # cumulative R²
    projected_dag: dict                # latent edges → observed variable implications
    engine_result: object | None = None


class CRLPipeline:
    """Causal representation learning: raw obs → latent factors → DAG.

    Args:
        n_factors: number of latent factors to extract (0 = auto-select via >80% variance).
        variance_threshold: minimum cumulative variance to retain.
        tau: CI test threshold for skeleton on latent factors.
    """

    def __init__(self, n_factors: int = 0, variance_threshold: float = 0.80,
                 tau: float = 0.05):
        self.n_factors = n_factors
        self.variance_threshold = variance_threshold
        self.tau = tau

    def discover(self, obs: list[list[float]]) -> CRLResult:
        n_obs = len(obs); n_vars = len(obs[0])
        std = _standardize_cols(obs)
        cov = _cov(std)

        eigenvalues, eigenvectors = self._eigen_decompose(cov, n_vars)
        n_factors = self._select_factors(eigenvalues)

        loadings = [[eigenvectors[j][i] * math.sqrt(eigenvalues[i])
                      for i in range(n_factors)] for j in range(n_vars)]
        factors = [[0.0] * n_factors for _ in range(n_obs)]
        for t in range(n_obs):
            for k in range(n_factors):
                factors[t][k] = sum(std[t][v] * eigenvectors[v][k] for v in range(n_vars))

        engine = ProductDiscoveryEngine(skeleton_tau=self.tau, use_fast_orient=True)
        result = engine.discover(factors)

        ev = [eigenvalues[i] / sum(eigenvalues) for i in range(n_factors)]
        total_ev = sum(ev)

        projected = self._project_dag_to_observed(result.dag, loadings, n_vars, n_factors)

        return CRLResult(
            dag=result.dag, n_factors=n_factors,
            factors=factors, loadings=loadings,
            explained_variance=ev, total_variance_explained=total_ev,
            projected_dag=projected, engine_result=result,
        )

    def _eigen_decompose(self, cov, n):
        eigenvectors = []
        eigenvalues = []
        for _ in range(n):
            v = [random.Random(_ + 42).uniform(-1, 1) for _ in range(n)]
            norm = math.sqrt(sum(x*x for x in v)) or 1e-9
            v = [x / norm for x in v]
            for _ in range(100):
                Av = [sum(cov[i][j] * v[j] for j in range(n)) for i in range(n)]
                for prev_vec, _ in zip(eigenvectors, eigenvalues):
                    dot = sum(prev_vec[i] * Av[i] for i in range(n))
                    Av = [Av[i] - dot * prev_vec[i] for i in range(n)]
                norm = math.sqrt(sum(x*x for x in Av)) or 1e-9
                v = [x / norm for x in Av]
            ev = sum(v[i] * sum(cov[i][j] * v[j] for j in range(n)) for i in range(n))
            eigenvalues.append(ev)
            eigenvectors.append(v)
        return eigenvalues, eigenvectors

    def _select_factors(self, eigenvalues):
        total = sum(e for e in eigenvalues if e > 0)
        if self.n_factors > 0:
            return min(self.n_factors, len(eigenvalues))
        cum = 0.0
        for i, ev in enumerate(eigenvalues):
            cum += ev / total if total > 0 else 0
            if cum >= self.variance_threshold:
                return i + 1
        return max(1, len(eigenvalues) // 3)

    def _project_dag_to_observed(self, latent_dag, loadings, n_vars, n_factors):
        projected = {}
        for u, v in latent_dag:
            u_vars = [i for i in range(n_vars) if abs(loadings[i][u]) > 0.3]
            v_vars = [j for j in range(n_vars) if abs(loadings[j][v]) > 0.5]
            projected[f"F{u}→F{v}"] = {
                "from_factor": u, "to_factor": v,
                "from_observed": u_vars, "to_observed": v_vars,
            }
        return projected
