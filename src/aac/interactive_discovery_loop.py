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
from .regime_shift_env import PiecewiseCausalSimulationEnv


@dataclass
class InteractiveDiscoveryLoop(GovernedDiscoveryLoop):
    """GovernedDiscoveryLoop that queries a live simulation environment.

    Args:
        environment: simulation environment exposing ``observe(n)`` and
            ``intervene(node, value)``.
        All other args are forwarded to GovernedDiscoveryLoop.
    """

    environment: Any | None = None

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


@dataclass
class OnlineInteractiveDiscoveryLoop(InteractiveDiscoveryLoop):
    """Multi-round interactive discovery with a sliding observation window.

    This lets the CWM loop track non-stationary / regime-shift environments:
    each round the loop collects fresh observations, keeps only the most recent
    ``max_window_size`` samples, and re-fits its posterior.  Interventions are
    still routed through the live environment; the loop has no execution
    authority.

    Args:
        max_window_size: if set, the observation window is truncated to this
            many recent samples each round.  ``None`` means cumulative (all
            observations retained).
    """

    max_window_size: int | None = None

    def discover_online(
        self,
        rounds: int = 3,
        n_obs_per_round: int = 60,
        interventions_per_round: int = 8,
    ) -> list[DiscoveryResult]:
        """Run multiple observe-intervene rounds and return per-round results."""
        if self.environment is None:
            raise ValueError("OnlineInteractiveDiscoveryLoop requires an environment")

        results: list[DiscoveryResult] = []
        window: list[list[float]] = []
        saved_budget = self.budget
        for _ in range(rounds):
            new_obs = self.environment.observe(n_obs_per_round)
            window.extend(new_obs)
            if self.max_window_size is not None and len(window) > self.max_window_size:
                window = window[-self.max_window_size:]
            self.budget = interventions_per_round
            result = self.discover(window, int_data=[])
            results.append(result)
        self.budget = saved_budget
        return results


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


def run_regime_shift_benchmark(
    n_nodes: int = 4,
    seed: int = 42,
) -> dict[str, Any]:
    """Compare online adaptive discovery to a static baseline under regime shift.

    Regime 0: chain 0 -> 1 -> 2.
    Regime 1: chain 0 -> 1 -> 3 -> 2 (edge 1->2 replaced by 1->3 and 3->2).
    The shift occurs after 100 samples.  The static baseline only sees regime-0
    data; the online loop uses a sliding window and keeps observing after the
    shift.
    """
    regime0_edges = {(0, 1), (1, 2)}
    regime1_edges = {(0, 1), (1, 3), (3, 2)}

    piecewise_env = PiecewiseCausalSimulationEnv(
        n_nodes=n_nodes,
        regimes=[
            {"edges": regime0_edges, "seed": seed, "noise_std": 0.2},
            {"edges": regime1_edges, "seed": seed + 100, "noise_std": 0.2},
        ],
        changepoints=[100],
        base_seed=seed,
    )

    online_loop = OnlineInteractiveDiscoveryLoop(
        organs=[],
        environment=piecewise_env,
        budget=8,
        confidence_threshold=0.95,
        seed=seed,
        n_particles=40,
        max_window_size=80,
    )
    online_results = online_loop.discover_online(
        rounds=4,
        n_obs_per_round=40,
        interventions_per_round=8,
    )
    final_online = online_results[-1]
    online_shd = piecewise_env.structural_hamming_distance(
        set(final_online.best_dag or []), regime_index=1
    )

    # Static baseline: trained only on regime-0 data, then evaluated on regime-1.
    static_env = CausalSimulationEnv(
        n_nodes=n_nodes,
        edges=regime0_edges,
        seed=seed,
        noise_std=0.2,
    )
    static_loop = InteractiveDiscoveryLoop(
        organs=[],
        environment=static_env,
        budget=24,
        confidence_threshold=0.95,
        seed=seed,
        n_particles=40,
    )
    static_result = static_loop.discover_from_env(n_obs=120)
    static_shd = piecewise_env.structural_hamming_distance(
        set(static_result.best_dag or []), regime_index=1
    )

    return {
        "regime0_truth": sorted(regime0_edges),
        "regime1_truth": sorted(regime1_edges),
        "online": {
            "shd_vs_regime1": online_shd,
            "final_confidence": round(final_online.confidence, 4),
            "interventions_spent_total": sum(r.interventions_spent for r in online_results),
        },
        "static": {
            "shd_vs_regime1": static_shd,
            "final_confidence": round(static_result.confidence, 4),
            "interventions_spent": static_result.interventions_spent,
        },
    }
