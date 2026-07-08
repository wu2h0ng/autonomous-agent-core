"""Unit tests for the multi-seed Sachs CWM benchmark harness.

Tests-first per Hard Boundary #17. These tests verify that:
- The harness loads Sachs data and produces the expected shape.
- The linear SCM oracle simulates interventions correctly.
- A single-seed run produces baseline-vs-causal comparison metrics.
- The multi-seed aggregate result has the expected schema.
"""
from __future__ import annotations

import math
import unittest

from experiments.cwm_sachs_multiseed import (
    GROUND_TRUTH,
    PROTEINS,
    load_sachs_obs,
    make_linear_scm_oracle,
    run_baseline,
    run_cwm_with_interventions,
    run_multiseed_benchmark,
    run_seed,
)


class TestSachsDataLoading(unittest.TestCase):
    def test_load_sachs_obs_shape(self):
        obs = load_sachs_obs()
        self.assertGreater(len(obs), 100)
        self.assertEqual(len(obs[0]), 11)

    def test_ground_truth_matches_proteins(self):
        self.assertEqual(len(PROTEINS), 11)
        for u, v in GROUND_TRUTH:
            self.assertLess(u, len(PROTEINS))
            self.assertLess(v, len(PROTEINS))


class TestLinearScmOracle(unittest.TestCase):
    def test_oracle_respects_do_node(self):
        obs = load_sachs_obs()
        rng = __import__("random").Random(42)
        oracle = make_linear_scm_oracle(obs, GROUND_TRUTH, rng)
        row = oracle(3, 2.0)
        self.assertEqual(len(row), 11)
        self.assertEqual(row[3], 2.0)

    def test_oracle_values_are_finite(self):
        obs = load_sachs_obs()
        rng = __import__("random").Random(7)
        oracle = make_linear_scm_oracle(obs, GROUND_TRUTH, rng)
        row = oracle(0, 1.5)
        for val in row:
            self.assertTrue(math.isfinite(val))


class TestBaselineAndCausal(unittest.TestCase):
    def test_baseline_returns_metric_shape(self):
        obs = load_sachs_obs()
        baseline = run_baseline(obs)
        self.assertIn("f1", baseline)
        self.assertIn("recall", baseline)
        self.assertIn("precision", baseline)
        self.assertIn("n_edges", baseline)
        self.assertTrue(math.isfinite(baseline["f1"]))

    def test_causal_returns_metric_shape(self):
        obs = load_sachs_obs()
        causal = run_cwm_with_interventions(obs, seed=42, budget=2)
        self.assertIn("f1", causal)
        self.assertIn("recall", causal)
        self.assertIn("precision", causal)
        self.assertIn("n_edges", causal)
        self.assertIn("interventions_spent", causal)
        self.assertEqual(causal["interventions_spent"], 2)

    def test_seed_comparison_shape(self):
        obs = load_sachs_obs()
        result = run_seed(obs, seed=100, budget=2)
        self.assertEqual(result["seed"], 100)
        self.assertIn("baseline", result)
        self.assertIn("causal", result)
        self.assertIn("f1_advantage", result)
        self.assertIn("recall_advantage", result)
        self.assertIn("precision_advantage", result)
        self.assertIsInstance(result["f1_advantage"], float)


class TestMultiSeedHarness(unittest.TestCase):
    def test_multiseed_aggregate_schema(self):
        obs = load_sachs_obs()
        result = run_multiseed_benchmark(obs=obs, seeds=[100, 101], budget=2)
        self.assertEqual(len(result["per_seed"]), 2)
        self.assertIn("mean_f1_advantage", result)
        self.assertIn("std_f1_advantage", result)
        self.assertIn("positive_seeds", result)
        self.assertIn("verdict", result)
        self.assertIn(result["verdict"], {"CAUSAL_WINS", "TIE", "BASELINE_WINS"})


if __name__ == "__main__":
    unittest.main()
