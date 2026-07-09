"""Nonlinear live-intervention benchmark.

Run: PYTHONPATH=src python experiments/nonlinear_intervention_binding.py
"""
from __future__ import annotations

import json

from aac.interactive_discovery_loop import OnlineInteractiveDiscoveryLoop
from aac.nonlinear_intervention_env import PolynomialCausalSimulationEnv


def main() -> None:
    edges = {(0, 1), (1, 2)}
    env = PolynomialCausalSimulationEnv(
        n_nodes=3,
        edges=edges,
        seed=42,
        noise_std=0.1,
        coef_range=(0.8, 0.8),
    )

    linear_loop = OnlineInteractiveDiscoveryLoop(
        organs=[],
        environment=env,
        budget=12,
        confidence_threshold=0.95,
        seed=42,
        n_particles=40,
        likelihood_mode="linear",
        max_window_size=80,
    )
    poly_loop = OnlineInteractiveDiscoveryLoop(
        organs=[],
        environment=env,
        budget=12,
        confidence_threshold=0.95,
        seed=42,
        n_particles=40,
        likelihood_mode="poly2",
        max_window_size=80,
    )

    linear_results = linear_loop.discover_online(
        rounds=3, n_obs_per_round=50, interventions_per_round=4
    )
    poly_results = poly_loop.discover_online(
        rounds=3, n_obs_per_round=50, interventions_per_round=4
    )

    result = {
        "ground_truth": sorted(edges),
        "linear": {
            "shd": env.structural_hamming_distance(
                set(linear_results[-1].best_dag or [])
            ),
            "confidence": round(linear_results[-1].confidence, 4),
        },
        "poly2": {
            "shd": env.structural_hamming_distance(
                set(poly_results[-1].best_dag or [])
            ),
            "confidence": round(poly_results[-1].confidence, 4),
        },
    }
    print(json.dumps(result, indent=2))
    with open("experiments/nonlinear_intervention_binding.result.json", "w") as f:
        json.dump(result, f, indent=2)
    print("\nWrote experiments/nonlinear_intervention_binding.result.json")


if __name__ == "__main__":
    main()
