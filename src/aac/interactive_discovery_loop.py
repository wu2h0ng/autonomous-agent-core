"""InteractiveDiscoveryLoop — connect GovernedDiscoveryLoop to a live env.

The loop proposes interventions using BOED/EIG, asks the environment for the
resulting sample, and updates the CWM posterior.  It is C7-offline/verify-only:
the environment is read-only for observations/interventions; the loop never
holds execution authority outside the discovery sandbox.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .governed_discovery_loop import DiscoveryResult, GovernedDiscoveryLoop
from .live_intervention_env import CausalSimulationEnv, RandomInterventionEnv


@dataclass
class InteractiveDiscoveryLoop(GovernedDiscoveryLoop):
    """GovernedDiscoveryLoop that queries a live simulation environment.

    Args:
        environment: simulation environment exposing ``observe(n)`` and
            ``intervene(node, value)``.
        All other args are forwarded to GovernedDiscoveryLoop.
    """

    environment: CausalSimulationEnv | None = None

    def discover_from_env(
        self,
        n_obs: int = 100,
    ) -> DiscoveryResult:
        """Run the full loop: observe, propose interventions, update posterior."""
        if self.environment is None:
            raise ValueError("InteractiveDiscoveryLoop requires an environment")
        obs = self.environment.observe(n_obs)
        return self.discover(obs, int_data=[])

    def _execute_intervention(
        self,
        obs: list[list[float]],
        int_data: list,
        do_node: int,
        do_val: float,
    ) -> list[float] | None:
        """Live intervention: ask the environment instead of replaying int_data."""
        if self.environment is None:
            # Fallback to base-class synthetic behavior if no env is set.
            return super()._execute_intervention(obs, int_data, do_node, do_val)
        return self.environment.intervene(do_node, do_val)


def run_live_intervention_benchmark(
    n_nodes: int = 3,
    edges: set[tuple[int, int]] | None = None,
    n_obs: int = 80,
    budget: int = 12,
    seed: int = 42,
) -> dict[str, Any]:
    """Run BOED-driven interactive loop vs random-baseline on a simulation env."""
    edges = edges or {(0, 1), (1, 2)}
    env = CausalSimulationEnv(
        n_nodes=n_nodes,
        edges=edges,
        seed=seed,
        noise_std=0.2,
    )

    boed_loop = InteractiveDiscoveryLoop(
        organs=[],
        environment=env,
        budget=budget,
        confidence_threshold=0.95,
        seed=seed,
        n_particles=40,
    )
    boed_result = boed_loop.discover_from_env(n_obs=n_obs)

    # Random baseline: same env, but override intervention selection by using
    # RandomInterventionEnv which ignores the loop's proposal.
    import random

    random_env = RandomInterventionEnv(env=env, rng=random.Random(seed + 1))
    random_loop = InteractiveDiscoveryLoop(
        organs=[],
        environment=random_env,
        budget=budget,
        confidence_threshold=0.95,
        seed=seed + 1,
        n_particles=40,
    )
    random_result = random_loop.discover_from_env(n_obs=n_obs)

    return {
        "ground_truth": sorted(edges),
        "boed": {
            "status": boed_result.status,
            "shd": env.structural_hamming_distance(set(boed_result.best_dag or [])),
            "confidence": round(boed_result.confidence, 4),
            "interventions_spent": boed_result.interventions_spent,
            "map_dag": sorted(boed_result.best_dag or []),
        },
        "random": {
            "status": random_result.status,
            "shd": random_env.structural_hamming_distance(set(random_result.best_dag or [])),
            "confidence": round(random_result.confidence, 4),
            "interventions_spent": random_result.interventions_spent,
            "map_dag": sorted(random_result.best_dag or []),
        },
    }
