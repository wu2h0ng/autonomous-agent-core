"""Latent-confounder live-intervention benchmark.

Run: PYTHONPATH=src python experiments/latent_confounder_binding.py
"""
from __future__ import annotations

import json

from aac.interactive_discovery_loop import OnlineInteractiveDiscoveryLoop
from aac.latent_confounder_env import PartiallyObservedSCMEnv


def main() -> None:
    # Latent node 3 confounds observed 0 and 1; observed 0 directly causes 2.
    edges = {(3, 0), (3, 1), (0, 2)}
    env = PartiallyObservedSCMEnv(
        n_total=4,
        observed_indices=[0, 1, 2],
        edges=edges,
        seed=42,
        noise_std=0.2,
        coef_range=(0.8, 0.8),
    )

    loop = OnlineInteractiveDiscoveryLoop(
        organs=[],
        environment=env,
        budget=12,
        confidence_threshold=0.95,
        seed=42,
        n_particles=60,
        max_window_size=120,
    )
    results = loop.discover_online(
        rounds=3, n_obs_per_round=60, interventions_per_round=4
    )
    final = results[-1]

    marginals = final.edge_marginals or {}
    false_edges = set(marginals.keys()) - env.ground_truth_observed_edges
    max_false_marginal = max(
        (marginals.get(e, 0.0) for e in false_edges), default=0.0
    )

    result = {
        "observed_truth": sorted(env.ground_truth_observed_edges),
        "final_map_dag": sorted(final.best_dag or []),
        "final_confidence": round(final.confidence, 4),
        "final_shd": env.structural_hamming_distance(set(final.best_dag or [])),
        "max_false_edge_marginal": round(max_false_marginal, 4),
        "interventions_spent_total": sum(r.interventions_spent for r in results),
    }
    print(json.dumps(result, indent=2))
    with open("experiments/latent_confounder_binding.result.json", "w") as f:
        json.dump(result, f, indent=2)
    print("\nWrote experiments/latent_confounder_binding.result.json")


if __name__ == "__main__":
    main()
