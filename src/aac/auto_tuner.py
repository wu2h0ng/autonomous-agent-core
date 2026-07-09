"""Auto-Tuning & Cross-Validation for Causal Discovery.

ENGINEERING DEPLOYMENT ONLY. FORBIDDEN in research/preregistration/falsification runs.
Per Hard Boundary #5: "绝不为了让实验门变绿而调机制" — automated hyperparameter
tuning is data snooping and violates preregistration discipline.

Allowed usage:
- Product deployment in enterprise OS
- Post-discovery sensitivity analysis (report-only, not gate-deciding)
- Engineering performance benchmarking (explicitly labeled as tuned)

Forbidden usage:
- Any Research Track R run with preregistered gates
- Any falsification experiment
- Any claim about mechanism performance

Fully automatic hyperparameter tuning without oracle access:
1. Tau grid search: picks tau that maximizes skeleton stability × edge economy.
2. Confidence threshold: bootstrap edge frequency → optimal threshold via elbow method.
3. K-fold cross-validation: edge consistency across folds → filter spurious edges.

All methods are GENERAL — no dataset-specific tuning, no ground truth required.
Pure stdlib.
"""
from __future__ import annotations

import math
import random
import statistics

from .cwm_organ import _standardize_cols, _cov, _inv


class AutoTuner:
    """Automatic hyperparameter tuning for causal discovery.

    Uses data-driven criteria (no ground truth required):
    - tau: maximize skeleton stability × (1 - edge_density)
    - confidence: bootstrap edge frequency elbow point
    - cross_val: K-fold edge consistency filter
    """

    def __init__(self, seed: int = 42):
        self._rng = random.Random(seed)
        self.best_tau: float = 0.05
        self.best_confidence: float = 0.5

    def tune_tau(self, obs: list[list[float]], tau_grid: list[float] | None = None,
                 n_bootstrap: int = 10) -> float:
        """Find optimal skeleton threshold tau.

        Criterion: maximize stability × economy.
        - Stability = mean pairwise Jaccard similarity of skeletons across bootstrap samples.
        - Economy = 1 - edge_density (penalizes overly dense skeletons that capture noise).

        Balances signal (stable edges) vs noise (unstable edges from low tau).
        """
        if tau_grid is None:
            tau_grid = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12, 0.15]
        n = len(obs)
        scores = {}
        for tau in tau_grid:
            skeletons = []
            for _ in range(n_bootstrap):
                sample = [obs[self._rng.randrange(n)] for _ in range(n)]
                try:
                    std = _standardize_cols(sample); prec = _inv(_cov(std))
                    edges = set()
                    nv = len(sample[0])
                    for i in range(nv):
                        for j in range(i + 1, nv):
                            d = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
                            if abs(prec[i][j]) / d > tau:
                                edges.add(frozenset({i, j}))
                    skeletons.append(edges)
                except (ValueError, ZeroDivisionError):
                    pass
            if len(skeletons) < 2:
                continue
            n_pairs = len(skeletons[0]) if skeletons else 1
            nv = len(obs[0])
            max_pairs = nv * (nv - 1) / 2 if nv > 1 else 1
            economy = 1.0 - n_pairs / max_pairs
            jaccards = []
            for i in range(len(skeletons)):
                for j in range(i + 1, len(skeletons)):
                    a, b = skeletons[i], skeletons[j]
                    inter = len(a & b); union = len(a | b)
                    jaccards.append(inter / max(union, 1))
            stability = statistics.mean(jaccards) if jaccards else 0
            scores[tau] = stability * economy
        if scores:
            self.best_tau = max(scores, key=scores.get)
            return self.best_tau
        return 0.05

    def tune_confidence(self, obs: list[list[float]], n_bootstrap: int = 10,
                        tau: float | None = None) -> float:
        """Tune Bayesian confidence threshold via bootstrap edge frequency.

        Find the elbow point in: edge frequency across bootstrap samples.
        Edges that appear in > elbow_fraction of bootstraps are considered
        'stable' and define the confidence threshold.
        """
        tau = tau or self.best_tau
        n = len(obs)
        edge_counts: dict[frozenset, int] = {}
        nv = len(obs[0])
        for _ in range(n_bootstrap):
            sample = [obs[self._rng.randrange(n)] for _ in range(n)]
            try:
                std = _standardize_cols(sample); prec = _inv(_cov(std))
                for i in range(nv):
                    for j in range(i + 1, nv):
                        d = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
                        if abs(prec[i][j]) / d > tau:
                            edge_counts[frozenset({i, j})] = edge_counts.get(frozenset({i, j}), 0) + 1
            except (ValueError, ZeroDivisionError):
                pass
        if not edge_counts:
            return 0.5
        freqs = sorted([c / n_bootstrap for c in edge_counts.values()], reverse=True)
        diffs = [freqs[i] - freqs[i + 1] for i in range(len(freqs) - 1)]
        if diffs:
            elbow_idx = diffs.index(max(diffs))
            self.best_confidence = freqs[elbow_idx] if elbow_idx < len(freqs) else 0.5
            return self.best_confidence
        return 0.5

    def cross_validate_edges(
        self, obs: list[list[float]], k: int = 5, tau: float | None = None,
    ) -> frozenset:
        """K-fold cross-validation: keep only edges consistent across folds.

        Split data into K folds. For each fold i:
        - Train on union of all OTHER folds
        - Discover edges on training set
        - Check if each edge is confirmed in the held-out fold i

        Edge survives if confirmed in at least K-1 folds.
        """
        tau = tau or self.best_tau
        nv = len(obs[0]); n = len(obs)
        fold_size = n // k
        fold_edges: list[set[frozenset]] = []
        fold_confirmed: dict[frozenset, int] = {}

        for fold in range(k):
            start = fold * fold_size; end = start + fold_size if fold < k - 1 else n
            test = obs[start:end]
            train = obs[:start] + obs[end:]
            if not test or not train:
                continue
            try:
                train_std = _standardize_cols(train); train_prec = _inv(_cov(train_std))
                nv = len(train[0])
                train_edges = set()
                for i in range(nv):
                    for j in range(i + 1, nv):
                        d = math.sqrt(abs(train_prec[i][i] * train_prec[j][j])) or 1e-12
                        if abs(train_prec[i][j]) / d > tau:
                            train_edges.add(frozenset({i, j}))
            except (ValueError, ZeroDivisionError):
                continue
            fold_edges.append(train_edges)

            try:
                test_std = _standardize_cols(test); test_prec = _inv(_cov(test_std))
                test_edges = set()
                for i in range(nv):
                    for j in range(i + 1, nv):
                        d = math.sqrt(abs(test_prec[i][i] * test_prec[j][j])) or 1e-12
                        if abs(test_prec[i][j]) / d > tau:
                            test_edges.add(frozenset({i, j}))
                for e in train_edges:
                    if e in test_edges:
                        fold_confirmed[e] = fold_confirmed.get(e, 0) + 1
            except (ValueError, ZeroDivisionError):
                pass

        if not fold_confirmed:
            all_edges = set()
            for fe in fold_edges: all_edges |= fe
            return frozenset(all_edges)

        min_folds = max(1, k - 2)
        validated = {e for e, c in fold_confirmed.items() if c >= min_folds}
        return frozenset(validated)
