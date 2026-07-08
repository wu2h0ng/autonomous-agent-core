"""Tests for non-stationary / regime-shift causal simulation environments."""
from __future__ import annotations

import math
import unittest

from aac.regime_shift_env import PiecewiseCausalSimulationEnv


class PiecewiseCausalSimulationEnvTest(unittest.TestCase):
    def test_single_regime_equivalent_to_stationary(self) -> None:
        edges = {(0, 1), (1, 2)}
        env = PiecewiseCausalSimulationEnv(
            n_nodes=3,
            regimes=[{"edges": edges, "seed": 1}],
            changepoints=[],
            base_seed=1,
        )
        samples = env.observe(50)
        self.assertEqual(len(samples), 50)
        self.assertEqual(len(samples[0]), 3)
        self.assertEqual(env.ground_truth_edges, edges)

    def test_regime_switch_changes_distribution(self) -> None:
        """Observations after a changepoint should follow a different SCM."""
        # Fix coefficient magnitude so the test is deterministic up to random
        # sign: adding edge 1->2 must increase the variance of x2.
        env = PiecewiseCausalSimulationEnv(
            n_nodes=3,
            regimes=[
                {"edges": {(0, 1)}, "seed": 1, "noise_std": 0.1, "coef_range": (0.8, 0.8)},
                {"edges": {(0, 1), (1, 2)}, "seed": 2, "noise_std": 0.1, "coef_range": (0.8, 0.8)},
            ],
            changepoints=[100],
            base_seed=1,
        )
        pre = env.observe(100)
        post = env.observe(100)

        # In regime 0, node 2 is pure noise; in regime 1 it carries signal from
        # node 1, so its variance must be materially larger.
        def variance(values):
            n = len(values)
            mean = sum(values) / n
            return sum((x - mean) ** 2 for x in values) / n

        pre_var = variance([r[2] for r in pre])
        post_var = variance([r[2] for r in post])
        self.assertGreater(post_var, pre_var + 0.005)

    def test_intervene_uses_current_regime(self) -> None:
        env = PiecewiseCausalSimulationEnv(
            n_nodes=3,
            regimes=[
                {"edges": {(0, 1)}, "seed": 1, "noise_std": 0.0},
                {"edges": {(0, 1), (1, 2)}, "seed": 2, "noise_std": 0.0},
            ],
            changepoints=[10],
            base_seed=1,
        )
        env.observe(10)
        # In regime 1, do(x1=5) should drive x2 via edge 1->2.
        sample = env.intervene(do_node=1, do_value=5.0)
        self.assertAlmostEqual(sample[1], 5.0)
        # With unit-ish coefficient and zero noise, x2 should be non-zero.
        self.assertGreater(abs(sample[2]), 0.1)

    def test_structural_hamming_distance_per_regime(self) -> None:
        env = PiecewiseCausalSimulationEnv(
            n_nodes=3,
            regimes=[
                {"edges": {(0, 1)}, "seed": 1},
                {"edges": {(0, 1), (1, 2)}, "seed": 2},
            ],
            changepoints=[10],
            base_seed=1,
        )
        self.assertEqual(
            env.structural_hamming_distance({(0, 1)}, regime_index=0),
            0,
        )
        self.assertEqual(
            env.structural_hamming_distance({(0, 1), (1, 2)}, regime_index=1),
            0,
        )
        self.assertEqual(
            env.structural_hamming_distance({(0, 1)}, regime_index=1),
            1,
        )

    def test_changepoint_validation(self) -> None:
        with self.assertRaises(ValueError):
            PiecewiseCausalSimulationEnv(
                n_nodes=2,
                regimes=[{"edges": {(0, 1)}}],
                changepoints=[10],  # one too many
            )


if __name__ == "__main__":
    unittest.main()
