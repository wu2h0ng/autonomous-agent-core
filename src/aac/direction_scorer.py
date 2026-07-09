"""Direction Enhancement — three non-interventional sources for DAG orientation.

In addition to interventional data (do()-based), three independent signals:
1. ANM (Additive Noise Model): causal direction has independent residuals.
   fit X=f(Y)+ε_X, Y=g(X)+ε_Y → direction with lower |corr(ε, input)| is causal.
2. Temporal precedence: if time order is known, X before Y → X→Y only.
3. Mechanism simplicity: better R² in one direction suggests simpler mechanism.

All three combined into a DirectionScorer that returns calibrated per-edge scores.
Pure stdlib. No interventional data required.

Reference: Hoyer+2009 (ANM), Shimizu+2006 (LiNGAM non-Gaussian), Peters+2017 (Elements).
"""
from __future__ import annotations

import math
import statistics

from .cwm_organ import _standardize_cols
from .bayesian_dag_posterior import _ols_coefficients


class DirectionScorer:
    """Score both directions of an undirected edge using three signals."""

    def __init__(self, obs: list[list[float]], time_order: list[int] | None = None):
        self.obs = obs
        self.time_order = time_order
        self.n = len(obs[0])

    def score(self, i: int, j: int) -> tuple[float, float]:
        """Return (score_i→j, score_j→i). Higher = more likely causal direction."""
        anm_i, anm_j = self._anm_score(i, j)
        temp_i, temp_j = self._temporal_score(i, j)
        simp_i, simp_j = self._simplicity_score(i, j)
        si = anm_i + temp_i + simp_i
        sj = anm_j + temp_j + simp_j
        return (round(si, 3), round(sj, 3))

    def _anm_score(self, i: int, j: int) -> tuple[float, float]:
        """ANM: direction with independent residuals scores higher."""
        try:
            X_i = [self.obs[t][i] for t in range(len(self.obs))]
            X_j = [self.obs[t][j] for t in range(len(self.obs))]
            X_j_poly = [[x, x*x] for x in X_j]
            X_i_poly = [[x, x*x] for x in X_i]
            beta_i = _ols_coefficients(X_j_poly, X_i)
            beta_j = _ols_coefficients(X_i_poly, X_j)
            res_i = [X_i[t] - sum(beta_i[k]*X_j_poly[t][k] for k in range(len(beta_i))) for t in range(len(X_i))]
            res_j = [X_j[t] - sum(beta_j[k]*X_i_poly[t][k] for k in range(len(beta_j))) for t in range(len(X_j))]
            corr_i = abs(self._correlation(res_i, X_j)) if len(res_i)>1 and statistics.pstdev(res_i)>0 else 1.0
            corr_j = abs(self._correlation(res_j, X_i)) if len(res_j)>1 and statistics.pstdev(res_j)>0 else 1.0
            return (1.0 - min(corr_i, 0.99), 1.0 - min(corr_j, 0.99))
        except (ValueError, ZeroDivisionError):
            return (0.0, 0.0)

    def _temporal_score(self, i: int, j: int) -> tuple[float, float]:
        """Temporal: 0.5 bonus if i precedes j in time, 0 if reversed."""
        if self.time_order is None:
            return (0.0, 0.0)
        try:
            ti = self.time_order.index(i) if i in self.time_order else -1
            tj = self.time_order.index(j) if j in self.time_order else -1
            if ti >= 0 and tj >= 0:
                return (0.5 if ti < tj else 0.0, 0.5 if tj < ti else 0.0)
        except ValueError:
            pass
        return (0.0, 0.0)

    def _simplicity_score(self, i: int, j: int) -> tuple[float, float]:
        """Mechanism simplicity: direction with better R² scores higher."""
        try:
            X_i = [self.obs[t][i] for t in range(len(self.obs))]
            X_j = [self.obs[t][j] for t in range(len(self.obs))]
            r2_i = self._r2(X_j, X_i); r2_j = self._r2(X_i, X_j)
            return (min(r2_i, 0.99), min(r2_j, 0.99))
        except (ValueError, ZeroDivisionError):
            return (0.0, 0.0)

    def _r2(self, X, Y):
        mu_y = statistics.mean(Y)
        X_poly = [[x, x*x] for x in X]
        beta = _ols_coefficients(X_poly, Y)
        ss_res = sum((Y[t] - sum(beta[k]*X_poly[t][k] for k in range(len(beta))))**2 for t in range(len(Y)))
        ss_tot = sum((y - mu_y)**2 for y in Y)
        return 1.0 - ss_res / max(ss_tot, 1e-9)

    def _correlation(self, a, b):
        mu_a = statistics.mean(a); mu_b = statistics.mean(b)
        cov = sum((a[t]-mu_a)*(b[t]-mu_b) for t in range(len(a))) / max(len(a)-1, 1)
        sd_a = statistics.pstdev(a) or 1e-9; sd_b = statistics.pstdev(b) or 1e-9
        return cov / (sd_a * sd_b)
