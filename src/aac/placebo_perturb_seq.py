"""Placebo world generator and §4.4 validation for Perturb-seq real data.

A Perturb-seq placebo destroys the causal link between the KO label and the
observed transcriptome by sampling cells from the observational pool, while
preserving marginal statistics. The validation gate confirms that no passive
skeleton-recovery method can find structure in the placebo.

Pure stdlib. Operates on already-normalized expression vectors.
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


def generate_placebo_perturb_seq(
    observational_data: list[list[float]],
    interventions: dict[tuple[int, str], list[list[float]]],
    seed: Optional[int] = None,
) -> tuple[dict[tuple[int, str], list[list[float]]], list[list[float]]]:
    """Generate a placebo intervention set for Perturb-seq.

    Strategy:
      - Observational data is reused unchanged (same marginals).
      - For each intervention (target, label), the "intervened" cells are a
        random sample from the observational pool with replacement. The KO
        label is therefore arbitrary and carries no causal information.

    This destroys causal structure while preserving the observational marginal
    distribution.
    """
    rng = random.Random(seed)
    if not observational_data:
        return {}, observational_data

    placebo: dict[tuple[int, str], list[list[float]]] = {}
    for key, original in interventions.items():
        n = len(original)
        sampled = [list(rng.choice(observational_data)) for _ in range(n)]
        placebo[key] = sampled

    return placebo, observational_data


@dataclass(frozen=True)
class PlaceboValidation:
    passes: bool
    max_ap: float
    covariance_distance: float
    ap_threshold: float
    covariance_threshold: float
    details: dict


def _covariance_matrix(data: list[list[float]]) -> list[list[float]]:
    n = len(data[0])
    means = [sum(row[j] for row in data) / len(data) for j in range(n)]
    c = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            c[i][j] = sum(
                (row[i] - means[i]) * (row[j] - means[j]) for row in data
            ) / len(data)
    return c


def _correlation_scores(data: list[list[float]]) -> dict[tuple[int, int], float]:
    n = len(data[0])
    means = [sum(row[j] for row in data) / len(data) for j in range(n)]
    stds = []
    for j in range(n):
        v = sum((row[j] - means[j]) ** 2 for row in data) / len(data)
        stds.append(math.sqrt(v) if v > 0 else 1.0)

    scores: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            num = sum((row[i] - means[i]) * (row[j] - means[j]) for row in data)
            denom = stds[i] * stds[j] * len(data)
            scores[(i, j)] = abs(num / denom) if denom > 0 else 0.0
    return scores


def _average_precision(
    ranked_edges: list[tuple[int, int]],
    truth: set[tuple[int, int]],
) -> float:
    tp = 0
    precisions: list[float] = []
    for e in ranked_edges:
        if e in truth:
            tp += 1
            precisions.append(tp / (len(precisions) + 1))
    return sum(precisions) / len(truth) if truth else 0.0


def validate_placebo_nonidentifiability_perturb_seq(
    real_observational: list[list[float]],
    placebo_observational: list[list[float]],
    placebo_interventions: dict[tuple[int, str], list[list[float]]],
    effect_threshold: float = 1.5,
    ap_threshold: float = 0.55,
    cov_threshold: float = 0.05,
    n_permutations: int = 100,
    alpha: float = 0.05,
) -> PlaceboValidation:
    """Run the §4.4 pre-score gate on a Perturb-seq placebo world.

    The placebo must satisfy:
      1. No intervention-based edge detection achieves AP > threshold.
      2. Marginal covariance matrix is close to the real world's covariance.
    """
    empirical = empirical_truth_from_interventions(
        placebo_interventions,
        placebo_observational,
        effect_threshold=effect_threshold,
        use_sem_threshold=True,
    )

    corr_scores = _correlation_scores(placebo_observational)
    all_edges = [(i, j) for i in range(len(placebo_observational[0])) for j in range(len(placebo_observational[0])) if i != j]
    ranked = sorted(all_edges, key=lambda e: corr_scores.get(e, 0.0), reverse=True)
    max_ap = _average_precision(ranked, set(empirical))

    real_cov = _covariance_matrix(real_observational)
    placebo_cov = _covariance_matrix(placebo_observational)
    n = len(real_observational[0])
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
