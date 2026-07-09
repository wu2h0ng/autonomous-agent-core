"""Placebo world generator and §4.4 non-identifiability validation.

A placebo world has the same marginal statistics as the real world but no
stable causal structure. This module constructs such worlds and verifies they
pass the pre-score gate required by PREREG-DRAFT §4.4.

Pure stdlib.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional

try:
    from .structure_scorer import empirical_truth_from_interventions
except ImportError:
    from structure_scorer import empirical_truth_from_interventions


def generate_placebo(
    observational_data: list[list[float]],
    interventions: dict[tuple[int, float], list[list[float]]],
    seed: Optional[int] = None,
) -> tuple[dict[tuple[int, float], list[list[float]]], list[list[float]]]:
    """Generate a placebo intervention set with matching marginals.

    Strategy:
      - Observational data is reused unchanged (same marginals / covariance).
      - For each "intervention" (target, value), the data is a random sample
        from the observational distribution, with NO conditioning on target
        and NO stable downstream effect. The "intervention" label is therefore
        arbitrary: do(X_i = x) is just a random observational draw.

    This destroys causal structure while preserving the observational marginal
    distribution. The loop's causal advantage MUST vanish on this world.
    """
    rng = random.Random(seed)
    if not interventions:
        return {}, observational_data
    n_obs_per_intervention = len(next(iter(interventions.values())))

    placebo: dict[tuple[int, float], list[list[float]]] = {}
    for (target, value) in interventions:
        # Random observational sample — no causal reset, no conditioning.
        sampled = [list(rng.choice(observational_data)) for _ in range(n_obs_per_intervention)]
        placebo[(target, value)] = sampled

    return placebo, observational_data


@dataclass(frozen=True)
class PlaceboValidation:
    """Result of the §4.4 placebo non-identifiability check."""

    passes: bool
    max_ap: float
    covariance_distance: float
    ap_threshold: float
    covariance_threshold: float
    details: dict


def _empirical_truth_permutation_null(
    interventions: dict[tuple[int, float], list[list[float]]],
    observational_data: list[list[float]],
    n_permutations: int = 100,
    alpha: float = 0.05,
) -> frozenset[tuple[int, int]]:
    """Detect edges using a permutation null.

    For each (target, value) and each other node j, compute the standardized
    mean difference between the intervention group and observational data.
    Build a null distribution by randomly sampling rows from observational
    data (same group size) many times. An edge is declared real only if the
    observed statistic exceeds the (1-alpha) quantile of the null.
    """
    import random

    if not observational_data:
        return frozenset()
    rng = random.Random(42)
    n_nodes = len(observational_data[0])
    obs_mean = [sum(row[j] for row in observational_data) / len(observational_data) for j in range(n_nodes)]
    obs_std = []
    for j in range(n_nodes):
        m = obs_mean[j]
        v = sum((row[j] - m) ** 2 for row in observational_data) / len(observational_data)
        obs_std.append(math.sqrt(v) if v > 0 else 1.0)

    empirical: set[tuple[int, int]] = set()
    for (target, value), data in interventions.items():
        if not data:
            continue
        n = len(data)
        for j in range(n_nodes):
            if j == target:
                continue
            interv_vals = [row[j] for row in data]
            interv_mean = sum(interv_vals) / len(interv_vals)
            diff = abs(interv_mean - obs_mean[j])
            denom = obs_std[j]
            observed_stat = diff / denom if denom > 0 else 0.0

            null_stats = []
            for _ in range(n_permutations):
                sample = [rng.choice(observational_data)[j] for _ in range(n)]
                sample_mean = sum(sample) / len(sample)
                null_diff = abs(sample_mean - obs_mean[j])
                null_stats.append(null_diff / denom if denom > 0 else 0.0)
            null_stats.sort()
            threshold = null_stats[int((1.0 - alpha) * len(null_stats))]
            if observed_stat > threshold:
                empirical.add((target, j))
    return frozenset(empirical)


def validate_placebo_nonidentifiability(
    real_observational: list[list[float]],
    placebo_observational: list[list[float]],
    placebo_interventions: dict[tuple[int, float], list[list[float]]],
    ap_threshold: float = 0.55,
    cov_threshold: float = 0.05,
    n_permutations: int = 100,
    alpha: float = 0.05,
) -> PlaceboValidation:
    """Run the §4.4 pre-score gate on the placebo world.

    The placebo must satisfy:
      1. No intervention-based edge detection achieves AP > threshold.
      2. Marginal covariance matrix is close to the real world's covariance.

    Edge detection uses a permutation null so that sampling noise is not
    mistaken for structure.

    Args:
        real_observational: real observational data.
        placebo_observational: placebo observational data (usually identical).
        placebo_interventions: placebo intervention data.
        ap_threshold: maximum allowed AP for any edge in placebo.
        cov_threshold: maximum relative Frobenius distance between covariances.
        n_permutations: number of permutations for the null distribution.
        alpha: significance level for edge detection.

    Returns:
        PlaceboValidation with pass/fail and diagnostics.
    """
    # 1. intervention-based edge detection on placebo
    empirical = _empirical_truth_permutation_null(
        placebo_interventions, placebo_observational, n_permutations, alpha
    )

    # For AP computation we need ranked predictions. Use |correlation| on observational data as ranker.
    n_nodes = len(placebo_observational[0])
    means = [sum(row[j] for row in placebo_observational) / len(placebo_observational) for j in range(n_nodes)]
    stds = []
    for j in range(n_nodes):
        v = sum((row[j] - means[j]) ** 2 for row in placebo_observational) / len(placebo_observational)
        stds.append(math.sqrt(v) if v > 0 else 1.0)

    corr_scores: dict[tuple[int, int], float] = {}
    for i in range(n_nodes):
        for j in range(n_nodes):
            if i == j:
                continue
            num = sum((row[i] - means[i]) * (row[j] - means[j]) for row in placebo_observational)
            denom = stds[i] * stds[j] * len(placebo_observational)
            corr_scores[(i, j)] = abs(num / denom) if denom > 0 else 0.0

    # AP: average precision at retrieved true edges
    all_edges = [(i, j) for i in range(n_nodes) for j in range(n_nodes) if i != j]
    ranked = sorted(all_edges, key=lambda e: corr_scores.get(e, 0.0), reverse=True)
    truth_set = set(empirical)
    tp_cum = 0
    fp_cum = 0
    precisions: list[float] = []
    for e in ranked:
        if e in truth_set:
            tp_cum += 1
            precisions.append(tp_cum / (tp_cum + fp_cum))
        else:
            fp_cum += 1
    max_ap = sum(precisions) / len(truth_set) if truth_set else 0.0

    # 2. covariance matrix comparison
    def _cov(data: list[list[float]]) -> list[list[float]]:
        n = len(data[0])
        means = [sum(row[j] for row in data) / len(data) for j in range(n)]
        c = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                c[i][j] = sum((row[i] - means[i]) * (row[j] - means[j]) for row in data) / len(data)
        return c

    real_cov = _cov(real_observational)
    placebo_cov = _cov(placebo_observational)
    n = n_nodes
    diff_sq = sum(
        (real_cov[i][j] - placebo_cov[i][j]) ** 2
        for i in range(n) for j in range(n)
    )
    real_sq = sum(real_cov[i][j] ** 2 for i in range(n) for j in range(n))
    cov_distance = math.sqrt(diff_sq) / (math.sqrt(real_sq) + 1e-9)

    passes = (max_ap <= ap_threshold) and (cov_distance <= cov_threshold)

    return PlaceboValidation(
        passes=passes,
        max_ap=max_ap,
        covariance_distance=cov_distance,
        ap_threshold=ap_threshold,
        covariance_threshold=cov_threshold,
        details={
            "n_empirical_edges": len(empirical),
            "correlation_scores_sample": sorted(corr_scores.values(), reverse=True)[:5],
        },
    )


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "experiments")
    from scm_generator import generate_scm, SCMConfig

    world = generate_scm(SCMConfig(n_nodes=6, n_obs=500, seed=42))
    placebo_interv, placebo_obs = generate_placebo(
        world.observational, world.interventions, seed=99
    )
    validation = validate_placebo_nonidentifiability(
        world.observational, placebo_obs, placebo_interv
    )
    print(validation)
