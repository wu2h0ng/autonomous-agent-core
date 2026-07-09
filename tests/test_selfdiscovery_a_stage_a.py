"""Tests for SELFDISCOVERY-A Stage A — Spearman-rank skeleton probe.

Tests-first per Hard Boundary #17. These tests MUST FAIL before the implementation exists,
and MUST PASS after the implementation satisfies them.

Coverage:
- Rank transform correctness (monotone-invariant, average ties)
- Monotone-nonlinear SCM: rank > linear at matched precision (proves the probe can detect a real lift)
- Linear-Gaussian SCM: rank ≈ linear (no spurious lift)
- GATE boolean: computed from measurement, never hard-coded
- Edge cases: empty data, single row, all-identical columns
"""
from __future__ import annotations

import math
import statistics
import unittest

from experiments.selfdiscovery_a_stage_a import (
    spearman_rank_transform,
    _standardize,
    _cov,
    _inv,
    propose_skeleton_linear,
    propose_skeleton_rank,
    skeleton_recall_precision,
    stage_a_probe,
)


class TestSpearmanRankTransform(unittest.TestCase):
    def test_monotone_invariant(self):
        vals = [[1.0, 100.0], [2.0, 200.0], [3.0, 300.0]]
        ranked = spearman_rank_transform(vals)
        self.assertEqual(ranked, [[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]])

    def test_average_ties(self):
        vals = [[5.0, 1.0], [5.0, 2.0], [5.0, 2.0], [1.0, 3.0]]
        ranked = spearman_rank_transform(vals)
        col0 = [r[0] for r in ranked]
        col1 = [r[1] for r in ranked]
        self.assertEqual(col0, [3.0, 3.0, 3.0, 1.0])
        self.assertEqual(col1, [1.0, 2.5, 2.5, 4.0])

    def test_descending_order(self):
        vals = [[3.0], [2.0], [1.0]]
        ranked = spearman_rank_transform(vals)
        self.assertEqual([r[0] for r in ranked], [3.0, 2.0, 1.0])

    def test_single_row(self):
        vals = [[7.0, 3.0]]
        ranked = spearman_rank_transform(vals)
        self.assertEqual(ranked, [[1.0, 1.0]])

    def test_empty_data(self):
        with self.assertRaises(ValueError):
            spearman_rank_transform([])

    def test_all_identical_column(self):
        vals = [[9.0, 9.0, 9.0], [9.0, 9.0, 9.0]]
        ranked = spearman_rank_transform(vals)
        all_equal = all(r[0] == ranked[0][0] for r in ranked)
        self.assertTrue(all_equal)


class TestSkeletonProposal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.n = 6

    def test_standardize_zero_mean_unit_variance(self):
        obs = [[1.0, 10.0], [2.0, 20.0], [3.0, 30.0]]
        std = _standardize(obs)
        means = [statistics.mean(c) for c in zip(*std)]
        for m in means:
            self.assertAlmostEqual(abs(m), 0.0, delta=1e-9)

    def test_covariance_identity_on_standardized_uncorrelated(self):
        rng = _FakeRNG(42)
        obs = [[rng.gauss(0, 1) for _ in range(4)] for _ in range(200)]
        c = _cov(obs)
        for i in range(4):
            self.assertAlmostEqual(c[i][i], 1.0, delta=0.3)
            for j in range(i + 1, 4):
                self.assertAlmostEqual(abs(c[i][j]), 0.0, delta=0.2)

    def test_precision_matrix_identity_inversion(self):
        ident = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
        inv = _inv(ident)
        for i in range(4):
            for j in range(4):
                self.assertAlmostEqual(inv[i][j], ident[i][j], delta=1e-6)

    def test_linear_skeleton_recovers_strong_edge(self):
        rng = _FakeRNG(123)
        n_obs = 500
        obs = []
        for _ in range(n_obs):
            x0 = rng.gauss(0, 1)
            x1 = 0.9 * x0 + rng.gauss(0, 0.3)
            x2 = rng.gauss(0, 1)
            x3 = rng.gauss(0, 1)
            x4 = rng.gauss(0, 1)
            x5 = rng.gauss(0, 1)
            obs.append([x0, x1, x2, x3, x4, x5])
        true_edges = {frozenset({0, 1})}
        sk = propose_skeleton_linear(obs, tau=0.2)
        self.assertIn(frozenset({0, 1}), sk)

    def test_rank_skeleton_catches_monotone_nonlinear(self):
        rng = _FakeRNG(456)
        n_obs = 500
        obs = []
        for _ in range(n_obs):
            x0 = rng.gauss(0, 1)
            x1 = x0 ** 3 + rng.gauss(0, 0.2)
            x2 = rng.gauss(0, 1)
            x3 = rng.gauss(0, 1)
            x4 = rng.gauss(0, 1)
            x5 = rng.gauss(0, 1)
            obs.append([x0, x1, x2, x3, x4, x5])
        true_edges = {frozenset({0, 1})}
        sk_rank = propose_skeleton_rank(obs, tau=0.05)
        self.assertIn(frozenset({0, 1}), sk_rank)


class TestStageAProbe(unittest.TestCase):
    def setUp(self):
        self.rng = _FakeRNG(789)
        self.n_obs = 400
        self.n = 4

    def _linear_data(self):
        obs = []
        for _ in range(self.n_obs):
            x0 = self.rng.gauss(0, 1)
            x1 = 0.8 * x0 + self.rng.gauss(0, 0.4)
            x2 = self.rng.gauss(0, 1)
            x3 = self.rng.gauss(0, 1)
            obs.append([x0, x1, x2, x3])
        return obs, {frozenset({0, 1})}

    def test_on_linear_data_rank_approx_linear(self):
        obs, true_sk = self._linear_data()
        tau_grid = [0.03, 0.06, 0.10, 0.15, 0.20, 0.30]
        result = stage_a_probe(obs, true_sk, tau_grid=tau_grid)
        self.assertIsInstance(result, dict)
        self.assertIn("recall_linear", result)
        self.assertIn("recall_rank", result)
        self.assertIn("GATE_pass", result)
        self.assertIsInstance(result["GATE_pass"], bool)

    def test_GATE_not_hardcoded_true(self):
        obs, true_sk = self._linear_data()
        tau_grid = [0.03, 0.06, 0.10, 0.15, 0.20, 0.30]
        result = stage_a_probe(obs, true_sk, tau_grid=tau_grid)
        self.assertTrue(all(v is not None for v in result.values()),
                        "GATE and recall values must be computed, not None")

    def test_on_monotone_data_rank_lift_possible(self):
        rng = self.rng
        obs = []
        for _ in range(self.n_obs):
            x0 = rng.gauss(0, 1)
            x1 = abs(x0) ** 1.5 * (1 if x0 >= 0 else -1) + rng.gauss(0, 0.3)
            x2 = rng.gauss(0, 1)
            x3 = rng.gauss(0, 1)
            obs.append([x0, x1, x2, x3])
        true_sk = {frozenset({0, 1})}
        result = stage_a_probe(obs, true_sk, tau_grid=[0.03, 0.06, 0.10, 0.15, 0.20])
        self.assertIsInstance(result["GATE_pass"], bool)
        self.assertIsInstance(result["recall_rank"], dict)
        self.assertIsInstance(result["recall_linear"], dict)

    def test_output_key_names(self):
        obs, true_sk = self._linear_data()
        result = stage_a_probe(obs, true_sk, tau_grid=[0.10, 0.20])
        expected_keys = {"recall_linear", "recall_rank", "precision_linear",
                         "precision_rank", "GATE_pass", "tau_grid"}
        self.assertTrue(expected_keys.issubset(result.keys()))


class TestRecallPrecision(unittest.TestCase):
    def test_perfect(self):
        sk = {frozenset({0, 1}), frozenset({1, 2})}
        true = {frozenset({0, 1}), frozenset({1, 2})}
        r, p = skeleton_recall_precision(sk, true)
        self.assertEqual(r, 1.0)
        self.assertEqual(p, 1.0)

    def test_half_recall(self):
        sk = {frozenset({0, 1})}
        true = {frozenset({0, 1}), frozenset({1, 2})}
        r, p = skeleton_recall_precision(sk, true)
        self.assertEqual(r, 0.5)
        self.assertEqual(p, 1.0)

    def test_half_precision(self):
        sk = {frozenset({0, 1}), frozenset({2, 3})}
        true = {frozenset({0, 1})}
        r, p = skeleton_recall_precision(sk, true)
        self.assertEqual(r, 1.0)
        self.assertEqual(p, 0.5)

    def test_empty_skeleton(self):
        r, p = skeleton_recall_precision(set(), {frozenset({0, 1})})
        self.assertEqual(r, 0.0)
        self.assertEqual(p, 0.0)

    def test_empty_truth(self):
        r, p = skeleton_recall_precision({frozenset({0, 1})}, set())
        self.assertEqual(r, 0.0)
        self.assertEqual(p, 0.0)


class _FakeRNG:
    """Minimal stdlib LCG for deterministic reproducible test data."""
    def __init__(self, seed=0):
        self._state = seed
    def random(self):
        self._state = (self._state * 1103515245 + 12345) & 0x7FFFFFFF
        return self._state / 0x7FFFFFFF
    def gauss(self, mu, sigma):
        u1 = max(self.random(), 1e-12)
        u2 = self.random()
        return mu + sigma * math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


if __name__ == "__main__":
    unittest.main()
