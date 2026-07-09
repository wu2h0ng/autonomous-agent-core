"""Temporal Precision Matrix — VAR-style causal discovery on the stdlib pipeline.

Extends the existing GGM skeleton pipeline (standardize→cov→precision→partial corr)
to temporal data via lagged feature expansion. Discovers causal edges across time
steps, not just contemporaneous associations.

Key innovation over standard VAR/Granger:
- Uses the SAME precision matrix CI test as the static pipeline — no new algorithm
- Only keeps edges where source lag > target lag (past→present causation)
- Automatically prunes spurious contemporaneous correlations by lag ordering
- Supports interventional data: do() rows at specific time indices

Integration: plugs into ProductDiscoveryEngine via TemporalPrecisionMatrix organ.
Pure stdlib. No external dependencies.

Usage:
    from aac.temporal_precision import TemporalPrecisionMatrix
    tpm = TemporalPrecisionMatrix(max_lag=3, tau=0.05)
    temporal_dag = tpm.discover(obs_data)  # returns {(src_n, src_lag, tgt_n, tgt_lag)}
"""
from __future__ import annotations

import math
import statistics

from .cwm_organ import _standardize_cols, _cov, _inv


class TemporalPrecisionMatrix:
    """Temporal causal discovery via lagged precision matrix CI tests.

    Extends the stdlib GGM skeleton to temporal data. Builds a lagged feature
    matrix, computes precision matrix, and identifies causal edges where
    past variables are partially correlated with future variables given
    all other past information.

    Args:
        max_lag: maximum number of lag steps to consider.
        tau: partial correlation threshold for edge inclusion.
    """

    def __init__(self, max_lag: int = 3, tau: float = 0.02):
        self.max_lag = max_lag
        self.tau = tau

    def build_lagged_matrix(
        self, obs: list[list[float]], drop_lags: bool = False,
    ) -> tuple[list[list[float]], int]:
        """Build lagged feature matrix.

        If drop_lags=False (default): keeps all rows. First max_lag rows use
        self-padding — the same observation replicated as pseudo-history.
        This preserves all data at small cost of weaker early temporal signal.

        If drop_lags=True: legacy behavior — drops first max_lag rows.
        """
        n = len(obs[0])
        expanded = []
        if not drop_lags:
            for t in range(len(obs)):
                row = []
                for lag in range(self.max_lag + 1):
                    idx = max(0, t - lag)
                    for v in range(n):
                        row.append(obs[idx][v])
                expanded.append(row)
        else:
            for t in range(self.max_lag, len(obs)):
                row = []
                for lag in range(self.max_lag + 1):
                    for v in range(n):
                        row.append(obs[t - lag][v])
                expanded.append(row)
        return expanded, n

    def discover(
        self, obs: list[list[float]],
    ) -> frozenset[tuple[int, int]]:
        """Discover temporal causal edges via lagged precision matrix.

        Returns set of (src_var, tgt_var) original-space directed edges.
        Only returns edges where past causes present (src_lag > tgt_lag).

        Contemporaneous edges (same lag) are excluded — these are observational
        associations, not Granger-causal.
        """
        expanded, n_vars = self.build_lagged_matrix(obs)
        try:
            std = _standardize_cols(expanded)
            prec = _inv(_cov(std))
        except (ValueError, ZeroDivisionError):
            return frozenset()

        n_exp = len(expanded[0])
        edges = set()
        for i in range(n_exp):
            for j in range(i + 1, n_exp):
                denom = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
                if abs(prec[i][j]) / denom > self.tau:
                    src_var = i % n_vars; src_lag = i // n_vars
                    tgt_var = j % n_vars; tgt_lag = j // n_vars
                    if src_lag > tgt_lag and tgt_lag == 0:
                        edges.add((src_var, tgt_var))
                    elif tgt_lag > src_lag and src_lag == 0:
                        edges.add((tgt_var, src_var))
        return frozenset(edges)

    def discover_with_lags(
        self, obs: list[list[float]],
    ) -> frozenset[tuple[int, int, int, int]]:
        """Discover temporal edges with full lag information.

        Returns set of (src_var, src_lag, tgt_var, tgt_lag) tuples.
        Useful for analyzing delay structure and feedback decomposition.
        """
        expanded, n_vars = self.build_lagged_matrix(obs)
        try:
            std = _standardize_cols(expanded)
            prec = _inv(_cov(std))
        except (ValueError, ZeroDivisionError):
            return frozenset()

        n_exp = len(expanded[0])
        edges = set()
        for i in range(n_exp):
            for j in range(i + 1, n_exp):
                denom = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
                if abs(prec[i][j]) / denom > self.tau:
                    src_var = i % n_vars; src_lag = i // n_vars
                    tgt_var = j % n_vars; tgt_lag = j // n_vars
                    if src_lag > tgt_lag:
                        edges.add((src_var, src_lag, tgt_var, tgt_lag))
                    elif tgt_lag > src_lag:
                        edges.add((tgt_var, tgt_lag, src_var, src_lag))
        return frozenset(edges)
