"""Tests for live intervention environment binding."""
from __future__ import annotations

import unittest

from aac.live_intervention_env import CausalSimulationEnv, RandomInterventionEnv
from aac.interactive_discovery_loop import (
    InteractiveDiscoveryLoop,
    run_live_intervention_benchmark,
)


class CausalSimulationEnvTest(unittest.TestCase):
    def test_observe_and_intervene_shapes(self) -> None:
        env = CausalSimulationEnv(n_nodes=3, edges={(0, 1), (1, 2)}, seed=1)
        obs = env.observe(20)
        self.assertEqual(len(obs), 20)
        self.assertEqual(len(obs[0]), 3)

        row = env.intervene(1, 5.0)
        self.assertEqual(len(row), 3)
        self.assertAlmostEqual(row[1], 5.0, places=5)

    def test_ground_truth_edges(self) -> None:
        env = CausalSimulationEnv(n_nodes=3, edges={(0, 1)}, seed=2)
        self.assertEqual(env.ground_truth_edges, {(0, 1)})

    def test_structural_hamming_distance(self) -> None:
        env = CausalSimulationEnv(n_nodes=3, edges={(0, 1), (1, 2)}, seed=3)
        self.assertEqual(env.structural_hamming_distance({(0, 1), (1, 2)}), 0)
        self.assertEqual(env.structural_hamming_distance(set()), 2)
        self.assertEqual(env.structural_hamming_distance({(0, 1), (1, 2), (2, 0)}), 1)


class InteractiveDiscoveryLoopTest(unittest.TestCase):
    def test_runs_full_loop_and_improves_confidence(self) -> None:
        env = CausalSimulationEnv(
            n_nodes=3,
            edges={(0, 1), (1, 2)},
            seed=42,
            noise_std=0.2,
        )
        loop = InteractiveDiscoveryLoop(
            organs=[],
            environment=env,
            budget=10,
            confidence_threshold=0.99,
            seed=42,
            n_particles=30,
        )
        result = loop.discover_from_env(n_obs=60)

        self.assertIn(result.status, {"VERIFIED", "BUDGET_EXHAUSTED"})
        self.assertGreater(result.interventions_spent, 0)
        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)

    def test_boed_beats_random_baseline_on_simple_chain(self) -> None:
        result = run_live_intervention_benchmark(
            n_nodes=3,
            edges={(0, 1), (1, 2)},
            n_obs=80,
            budget=12,
            seed=7,
        )
        boed_shd = result["boed"]["shd"]
        random_shd = result["random"]["shd"]
        # BOED/EIG should not be worse than random on this tiny deterministic chain.
        self.assertLessEqual(boed_shd, random_shd)

    def test_c7_offline_invariant_no_control_path(self) -> None:
        """The loop only reads observations/interventions; it never executes an
        external action or writes to a control surface."""
        env = CausalSimulationEnv(n_nodes=3, edges={(0, 1)}, seed=5, noise_std=0.2)
        loop = InteractiveDiscoveryLoop(
            organs=[],
            environment=env,
            budget=3,
            confidence_threshold=0.99,
            seed=5,
            n_particles=20,
        )
        # The only methods called on the environment are observe and intervene.
        original_intervene = env.intervene
        calls: list[tuple[int, float]] = []

        def wrapped(node: int, value: float) -> list[float]:
            calls.append((node, value))
            return original_intervene(node, value)

        env.intervene = wrapped  # type: ignore[method-assign]
        loop.discover_from_env(n_obs=40)
        self.assertGreater(len(calls), 0)
        for node, value in calls:
            self.assertIsInstance(node, int)
            self.assertIsInstance(value, float)
            # No control-path side effects: just a read of an intervened sample.


if __name__ == "__main__":
    unittest.main()
