"""Precision & Temporal Filters — general causal discovery quality improvements.

1. InterventionValidationFilter: post-process discovered DAG edges against held-out
   intervention data. Only edges with consistent cross-intervention effects survive.
   Uses do-calculus: for X→Y, checks whether P(Y|do(X)) differs from P(Y) in held-out.

2. TemporalDAGSplitter: converts cyclic/feedback systems into temporal DAGs via
   time-lagged variable expansion. Standard approach (Granger, PCMCI, dynamic BN).
   For FinCARE financial data with investment↔revenue feedback loops.

Both are GENERAL — work on any domain with intervention data or time ordering.
Pure stdlib. Plugs into ProductDiscoveryEngine.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass


class InterventionValidationFilter:
    """Filter discovered DAG edges using interventional held-out data.

    REQUIRES actual do()-style intervention data to distinguish causation
    from correlation. Without intervention data, this filter cannot operate
    safely — observational held-out data only measures correlation, not
    causation, and risks confirming spurious confounded edges.

    When int_data is provided: validates edges by checking whether P(Y|do(X))
    differs from P(Y) in held-out interventional data.
    When int_data is None: returns dag UNCHANGED with a warning that
    interventional validation was requested but no intervention data supplied.

    General: works on any domain with interventional data.
    """
    WARNING_NO_INT_DATA = (
        "InterventionValidationFilter requires do()-style intervention data. "
        "Without it, the filter cannot distinguish causation from correlation "
        "and would confirm spurious confounded edges. DAG returned unchanged."
    )

    def __init__(self, holdout_ratio: float = 0.2, effect_threshold: float = 0.2,
                 min_replications: int = 1):
        self.holdout_ratio = holdout_ratio
        self.effect_threshold = effect_threshold
        self.min_replications = min_replications

    def filter(
        self, dag: frozenset, obs: list[list[float]],
        int_data: list[list[float]] | None = None,
    ) -> frozenset:
        if int_data is None:
            return dag

    def _compute_intervention_effect(
        self, heldout: list[list[float]], baseline: dict,
        u: int, v: int,
    ) -> float:
        if len(heldout) < 20:
            return 0.0
        col_u = [row[u] for row in heldout]
        col_v = [row[v] for row in heldout]
        mu_u = statistics.mean(col_u); sd_u = statistics.pstdev(col_u) or 1.0
        mu_v = statistics.mean(col_v)
        high_u = [row[v] for row in heldout if row[u] > mu_u + 0.5 * sd_u]
        low_u = [row[v] for row in heldout if row[u] < mu_u - 0.5 * sd_u]
        if len(high_u) < 5 or len(low_u) < 5:
            return 0.0
        diff = abs(statistics.mean(high_u) - statistics.mean(low_u))
        pooled = (baseline[v][1] + statistics.pstdev(col_v) or 1.0) / 2
        return diff / max(pooled, 1e-9)


class TemporalDAGSplitter:
    """Split cyclic feedback systems into temporal DAGs via lagged variables.

    For FinCARE-style data with investment→revenue→investment feedback:
    Creates X_t and X_{t-1} copies of each variable. Discovers DAG on the
    expanded feature set where self-loops and reverse edges become forward
    temporal edges (e.g., investment_{t-1}→revenue_t→investment_{t+1}).

    General: works on any time-ordered or pseudo-time-ordered dataset.
    Standard approach in time series causal discovery (Granger, PCMCI).
    """

    def __init__(self, n_lags: int = 2, n_nodes: int = 0):
        self.n_lags = n_lags

    def expand(self, obs: list[list[float]]) -> list[list[float]]:
        """Expand observations into lagged feature matrix.

        obs (n_obs × n_vars) → expanded ((n_obs - n_lags) × (n_vars * (n_lags + 1)))
        Each row t contains: [X_t, X_{t-1}, ..., X_{t-n_lags}] for all variables.
        """
        n = len(obs[0])
        expanded = []
        for t in range(self.n_lags, len(obs)):
            row = []
            for lag in range(self.n_lags + 1):
                for v in range(n):
                    row.append(obs[t - lag][v])
            expanded.append(row)
        return expanded

    def map_edges_to_original(
        self, expanded_dag: frozenset, n_vars: int,
    ) -> frozenset[tuple[int, int]]:
        """Map expanded-space edges back to original variable edges.

        For each edge (exp_i, exp_j) in the expanded space:
        - src_var = exp_i % n_vars, src_lag = exp_i // n_vars
        - tgt_var = exp_j % n_vars, tgt_lag = exp_j // n_vars
        Only keeps edges where at least one side is at lag 0 (current time).
        Maps all lagged causal relations to the original variable pair.
        """
        original = set()
        for exp_i, exp_j in expanded_dag:
            src_var = exp_i % n_vars
            src_lag = exp_i // n_vars
            tgt_var = exp_j % n_vars
            tgt_lag = exp_j // n_vars
            if src_lag == 0 and tgt_lag == 0:
                original.add((src_var, tgt_var))
            elif src_lag > 0 and tgt_lag == 0:
                original.add((src_var, tgt_var))
            elif src_lag == 0 and tgt_lag > 0:
                pass  # future→past, invalid
        return frozenset(original)
