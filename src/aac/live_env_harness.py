"""Unified live-environment harness for CWM causal discovery.

This module consolidates the four simulation environments built so far
(linear, regime-shift, nonlinear polynomial, latent-confounder) into a single
sweepable benchmark.  Each environment exposes the same surface:

- ``n_nodes``: number of nodes visible to the discovery loop
- ``observe(n_samples)``: batch of observational samples
- ``intervene(node, value)``: one interventional sample
- ``ground_truth_edges``: true directed edges among visible nodes
- ``structural_hamming_distance(predicted)``: SHD against the visible truth

The harness is C7-offline/verify-only: environments return samples, the loop
proposes and updates, and no execution authority leaves the sandbox.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Callable

from .change_point_detector import MeanDriftDetector
from .interactive_discovery_loop import OnlineInteractiveDiscoveryLoop
from .latent_confounder_env import PartiallyObservedSCMEnv
from .live_intervention_env import CausalSimulationEnv
from .nonlinear_intervention_env import PolynomialCausalSimulationEnv
from .regime_shift_env import PiecewiseCausalSimulationEnv


@dataclass
class EnvSpec:
    """Named factory for a live simulation environment family."""

    name: str
    factory: Callable[[int], Any]


def make_linear_env(seed: int) -> CausalSimulationEnv:
    """A simple 4-node linear chain."""
    return CausalSimulationEnv(
        n_nodes=4,
        edges={(0, 1), (1, 2), (2, 3)},
        seed=seed,
        noise_std=0.2,
        coef_range=(0.8, 0.8),
    )


def make_regime_shift_env(seed: int) -> PiecewiseCausalSimulationEnv:
    """A 4-node env where the causal structure changes after 100 samples."""
    return PiecewiseCausalSimulationEnv(
        n_nodes=4,
        regimes=[
            {"edges": {(0, 1), (1, 2)}, "seed": seed, "noise_std": 0.2, "coef_range": (0.8, 0.8)},
            {"edges": {(0, 1), (1, 3), (3, 2)}, "seed": seed + 100, "noise_std": 0.2, "coef_range": (0.8, 0.8)},
        ],
        changepoints=[100],
        base_seed=seed,
    )


def make_nonlinear_env(seed: int) -> PolynomialCausalSimulationEnv:
    """A 3-node quadratic chain."""
    return PolynomialCausalSimulationEnv(
        n_nodes=3,
        edges={(0, 1), (1, 2)},
        seed=seed,
        noise_std=0.1,
        coef_range=(0.8, 0.8),
    )


def make_latent_env(seed: int) -> PartiallyObservedSCMEnv:
    """A 4-node SCM where node 3 is latent and confounds 0 and 1."""
    return PartiallyObservedSCMEnv(
        n_total=4,
        observed_indices=[0, 1, 2],
        edges={(3, 0), (3, 1), (0, 2)},
        seed=seed,
        noise_std=0.2,
        coef_range=(0.8, 0.8),
    )


ENV_SPECS: list[EnvSpec] = [
    EnvSpec("linear", make_linear_env),
    EnvSpec("regime_shift", make_regime_shift_env),
    EnvSpec("nonlinear", make_nonlinear_env),
    EnvSpec("latent", make_latent_env),
]


def _precision_recall_f1(
    predicted: set[tuple[int, int]], truth: set[tuple[int, int]], n_nodes: int
) -> tuple[float, float, float]:
    """Compute precision, recall, F1 for a predicted DAG vs ground truth."""
    tp = len(predicted & truth)
    fp = len(predicted - truth)
    fn = len(truth - predicted)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return round(precision, 4), round(recall, 4), round(f1, 4)


def _mean_and_std(values: list[float]) -> tuple[float, float]:
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / n
    return round(mean, 4), round(math.sqrt(variance), 4)


def run_env_single_seed(
    env_factory: Callable[[int], Any],
    seed: int,
    budget: int = 12,
    rounds: int = 3,
    n_obs_per_round: int = 60,
    interventions_per_round: int = 4,
    n_particles: int = 40,
    likelihood_mode: str = "linear",
    change_point_detector: MeanDriftDetector | None = None,
    min_edge_marginal: float = 0.0,
) -> dict[str, Any]:
    """Run the online discovery loop on one environment instance."""
    env = env_factory(seed)
    loop = OnlineInteractiveDiscoveryLoop(
        organs=[],
        environment=env,
        budget=budget,
        confidence_threshold=0.95,
        seed=seed,
        n_particles=n_particles,
        likelihood_mode=likelihood_mode,
        max_window_size=120,
        change_point_detector=change_point_detector,
        min_edge_marginal=min_edge_marginal,
    )
    results = loop.discover_online(
        rounds=rounds,
        n_obs_per_round=n_obs_per_round,
        interventions_per_round=interventions_per_round,
    )
    final = results[-1]
    predicted = set(final.best_dag or [])
    truth = env.ground_truth_edges
    precision, recall, f1 = _precision_recall_f1(predicted, truth, env.n_nodes)

    false_edges = predicted - truth
    return {
        "seed": seed,
        "status": final.status,
        "shd": env.structural_hamming_distance(predicted),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_edge_count": len(false_edges),
        "confidence": round(final.confidence, 4),
        "interventions_spent": sum(r.interventions_spent for r in results),
        "predicted_dag": sorted(predicted),
        "ground_truth": sorted(truth),
    }


def run_suite(
    seeds: list[int] | None = None,
    budget: int = 12,
    n_particles: int = 40,
) -> dict[str, Any]:
    """Run a multi-seed sweep across all four live-environment families.

    Args:
        seeds: list of RNG seeds to sweep.  Default: 0..9.
        budget: total intervention budget per env instance.
        n_particles: DiBS particle count.

    Returns:
        dict keyed by environment family name, each containing ``per_seed``
        results and ``aggregate`` mean/std metrics.
    """
    seeds = list(range(10)) if seeds is None else list(seeds)
    suite_result: dict[str, Any] = {"seeds": seeds, "families": {}}

    for spec in ENV_SPECS:
        # Nonlinear env uses poly2 likelihood; others use linear.
        likelihood_mode = "poly2" if spec.name == "nonlinear" else "linear"
        per_seed = [
            run_env_single_seed(
                spec.factory,
                seed,
                budget=budget,
                n_particles=n_particles,
                likelihood_mode=likelihood_mode,
            )
            for seed in seeds
        ]
        shds = [r["shd"] for r in per_seed]
        precisions = [r["precision"] for r in per_seed]
        recalls = [r["recall"] for r in per_seed]
        f1s = [r["f1"] for r in per_seed]
        confidences = [r["confidence"] for r in per_seed]
        false_counts = [r["false_edge_count"] for r in per_seed]

        suite_result["families"][spec.name] = {
            "per_seed": per_seed,
            "aggregate": {
                "shd_mean": _mean_and_std(shds)[0],
                "shd_std": _mean_and_std(shds)[1],
                "precision_mean": _mean_and_std(precisions)[0],
                "precision_std": _mean_and_std(precisions)[1],
                "recall_mean": _mean_and_std(recalls)[0],
                "recall_std": _mean_and_std(recalls)[1],
                "f1_mean": _mean_and_std(f1s)[0],
                "f1_std": _mean_and_std(f1s)[1],
                "confidence_mean": _mean_and_std(confidences)[0],
                "confidence_std": _mean_and_std(confidences)[1],
                "false_edge_count_mean": _mean_and_std(false_counts)[0],
                "false_edge_count_std": _mean_and_std(false_counts)[1],
            },
        }

    return suite_result


def run_suite_adaptive(
    seeds: list[int] | None = None,
    budget: int = 12,
    n_particles: int = 40,
    drift_threshold: float = 1.0,
    latent_marginal_threshold: float = 0.35,
) -> dict[str, Any]:
    """Run a multi-seed sweep with adaptive guards enabled.

    - ``regime_shift`` uses a ``MeanDriftDetector`` to reset the posterior on a
      detected shift.
    - ``latent`` removes MAP edges whose marginal is below
      ``latent_marginal_threshold``.
    - ``linear`` and ``nonlinear`` use the same configuration as ``run_suite``.
    """
    detector = MeanDriftDetector(threshold=drift_threshold)
    seeds = list(range(10)) if seeds is None else list(seeds)
    suite_result: dict[str, Any] = {"seeds": seeds, "families": {}}

    for spec in ENV_SPECS:
        likelihood_mode = "poly2" if spec.name == "nonlinear" else "linear"
        cpd = detector if spec.name == "regime_shift" else None
        min_marginal = latent_marginal_threshold if spec.name == "latent" else 0.0
        per_seed = [
            run_env_single_seed(
                spec.factory,
                seed,
                budget=budget,
                n_particles=n_particles,
                likelihood_mode=likelihood_mode,
                change_point_detector=cpd,
                min_edge_marginal=min_marginal,
            )
            for seed in seeds
        ]
        shds = [r["shd"] for r in per_seed]
        precisions = [r["precision"] for r in per_seed]
        recalls = [r["recall"] for r in per_seed]
        f1s = [r["f1"] for r in per_seed]
        confidences = [r["confidence"] for r in per_seed]
        false_counts = [r["false_edge_count"] for r in per_seed]

        suite_result["families"][spec.name] = {
            "per_seed": per_seed,
            "aggregate": {
                "shd_mean": _mean_and_std(shds)[0],
                "shd_std": _mean_and_std(shds)[1],
                "precision_mean": _mean_and_std(precisions)[0],
                "precision_std": _mean_and_std(precisions)[1],
                "recall_mean": _mean_and_std(recalls)[0],
                "recall_std": _mean_and_std(recalls)[1],
                "f1_mean": _mean_and_std(f1s)[0],
                "f1_std": _mean_and_std(f1s)[1],
                "confidence_mean": _mean_and_std(confidences)[0],
                "confidence_std": _mean_and_std(confidences)[1],
                "false_edge_count_mean": _mean_and_std(false_counts)[0],
                "false_edge_count_std": _mean_and_std(false_counts)[1],
            },
        }

    return suite_result
