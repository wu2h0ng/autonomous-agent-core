"""Tests for nonlinear causal simulation environments and live discovery."""
from __future__ import annotations

import unittest

from aac.interactive_discovery_loop import OnlineInteractiveDiscoveryLoop
from aac.nonlinear_intervention_env import PolynomialCausalSimulationEnv


class PolynomialCausalSimulationEnvTest(unittest.TestCase):
    def test_observe_and_intervene_shapes(self) -> None:
        env = PolynomialCausalSimulationEnv(
            n_nodes=3,
            edges={(0, 1), (1, 2)},
            seed=1,
            noise_std=0.1,
        )
        obs = env.observe(30)
        self.assertEqual(len(obs), 30)
        self.assertEqual(len(obs[0]), 3)
        sample = env.intervene(do_node=1, do_value=2.0)
        self.assertEqual(len(sample), 3)
        self.assertAlmostEqual(sample[1], 2.0)

    def test_nonlinear_intervention_effect(self) -> None:
        """Intervening with v on a parent should scale the child like v^2."""
        env = PolynomialCausalSimulationEnv(
            n_nodes=3,
            edges={(0, 1), (1, 2)},
            seed=4,
            noise_std=0.05,
            coef_range=(0.8, 0.8),
        )
        n = 100
        low = [env.intervene(do_node=1, do_value=1.0)[2] for _ in range(n)]
        high = [env.intervene(do_node=1, do_value=2.0)[2] for _ in range(n)]
        ratio = (sum(high) / n) / (sum(low) / n)
        # x2 = 0.8 * x1^2 + noise.  Doubling x1 from 1 to 2 multiplies x2 by ~4.
        self.assertGreater(ratio, 3.0)
        self.assertLess(ratio, 5.0)

    def test_ground_truth_shd(self) -> None:
        env = PolynomialCausalSimulationEnv(
            n_nodes=3,
            edges={(0, 1)},
            seed=3,
        )
        self.assertEqual(env.structural_hamming_distance({(0, 1)}), 0)
        self.assertEqual(env.structural_hamming_distance({(1, 0)}), 2)


class NonlinearLiveDiscoveryTest(unittest.TestCase):
    def test_poly2_beats_linear_on_nonlinear_env(self) -> None:
        """On a quadratic chain, poly2 likelihood should recover more true edges."""
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

        linear_shd = env.structural_hamming_distance(
            set(linear_results[-1].best_dag or [])
        )
        poly_shd = env.structural_hamming_distance(
            set(poly_results[-1].best_dag or [])
        )
        self.assertLessEqual(poly_shd, linear_shd)


if __name__ == "__main__":
    unittest.main()
