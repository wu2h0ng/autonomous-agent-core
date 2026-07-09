"""Tests for Temporal Options and Bayesian IRL from Correction."""
from __future__ import annotations

import unittest

from aac.temporal_and_irl import (
    TemporalOption,
    OptionLibrary,
    BayesianIRLFromCorrection,
    extract_action_features,
)


class TestTemporalOption(unittest.TestCase):
    def test_create_from_chain(self):
        opt = TemporalOption.from_chain(
            "test_chain", [(0, 1.0), (1, -0.5)], n_nodes=3, confidence=0.7,
        )
        self.assertEqual(opt.name, "test_chain")
        self.assertEqual(len(opt.interventions), 2)
        self.assertEqual(opt.confidence, 0.7)

    def test_execute_step_returns_correct_value(self):
        opt = TemporalOption.from_chain("t", [(2, 3.0), (0, -1.0)], n_nodes=4)
        step = opt.execute_step(0)
        self.assertEqual(step, (2, 3.0))
        step = opt.execute_step(1)
        self.assertEqual(step, (0, -1.0))
        self.assertIsNone(opt.execute_step(2))

    def test_is_applicable_high_uncertainty(self):
        opt = TemporalOption.from_chain("t", [(0, 1.0)], n_nodes=3)
        self.assertTrue(opt.is_applicable({0: 0.8, 1: 0.1}))

    def test_is_applicable_low_uncertainty(self):
        opt = TemporalOption.from_chain("t", [(0, 1.0)], n_nodes=3)
        self.assertFalse(opt.is_applicable({0: 0.2, 1: 0.1}))

    def test_update_confidence(self):
        opt = TemporalOption.from_chain("t", [(0, 1.0)], n_nodes=3)
        opt.update_confidence(True)
        opt.update_confidence(False)
        self.assertAlmostEqual(opt.confidence, 0.5)


class TestOptionLibrary(unittest.TestCase):
    def test_add_and_retrieve_by_node(self):
        lib = OptionLibrary()
        lib.add(TemporalOption.from_chain("a", [(0, 1.0)], n_nodes=3))
        lib.add(TemporalOption.from_chain("b", [(1, 2.0)], n_nodes=3))
        self.assertEqual(len(lib.for_node(0)), 1)
        self.assertEqual(len(lib.for_node(1)), 1)

    def test_best_for_uncertainty_ranks_by_confidence(self):
        lib = OptionLibrary()
        lib.add(TemporalOption.from_chain("low_c", [(0, 1.0)], n_nodes=3, confidence=0.4))
        lib.add(TemporalOption.from_chain("high_c", [(0, 2.0)], n_nodes=3, confidence=0.9))
        best = lib.best_for_uncertainty({0: 0.8})
        self.assertEqual(best[0].name, "high_c")

    def test_prune_removes_low_confidence(self):
        lib = OptionLibrary()
        lib.add(TemporalOption.from_chain("keep", [(0, 1.0)], n_nodes=3, confidence=0.6))
        lib.add(TemporalOption.from_chain("drop", [(1, 2.0)], n_nodes=3, confidence=0.1))
        lib.prune_low_confidence(0.3)
        self.assertEqual(len(lib), 1)


class TestBayesianIRL(unittest.TestCase):
    def test_empty_corrections_returns_prior(self):
        irl = BayesianIRLFromCorrection(n_features=4)
        w = irl.infer_reward()
        self.assertEqual(w, [0.0, 0.0, 0.0, 0.0])

    def test_denied_reduces_feature_weight(self):
        irl = BayesianIRLFromCorrection(n_features=2)
        irl.observe_correction([1.0, 0.5], denied=True, confidence=1.0)
        w = irl.infer_reward()
        self.assertLess(w[0], 0.0)

    def test_allowed_increases_feature_weight(self):
        irl = BayesianIRLFromCorrection(n_features=2)
        irl.observe_correction([1.0, 0.5], denied=False, confidence=1.0)
        w = irl.infer_reward()
        self.assertGreater(w[0], 0.0)

    def test_causal_correction_is_ignored(self):
        irl = BayesianIRLFromCorrection(n_features=2)
        irl.observe_correction([1.0, 0.5], denied=True, correction_type="causal")
        w = irl.infer_reward()
        self.assertEqual(w, [0.0, 0.0])  # prior unchanged

    def test_safety_correction_is_learned(self):
        irl = BayesianIRLFromCorrection(n_features=2)
        irl.observe_correction([1.0, 0.0], denied=True, correction_type="safety")
        w = irl.infer_reward()
        self.assertLess(w[0], 0.0)

    def test_mixed_types_only_learn_safety_risk(self):
        irl = BayesianIRLFromCorrection(n_features=2)
        irl.observe_correction([1.0, 0.0], denied=True, correction_type="safety")
        irl.observe_correction([0.0, 1.0], denied=True, correction_type="causal")
        irl.observe_correction([0.0, 0.0], denied=False, correction_type="risk")
        w = irl.infer_reward()
        self.assertLess(w[0], 0.0)
        self.assertEqual(w[1], 0.0)  # causal ignored, risk taught nothing new

    def test_predict_acceptance_in_range(self):
        irl = BayesianIRLFromCorrection(n_features=3)
        irl.observe_correction([0.0, 1.0, 0.0], denied=False, confidence=1.0)
        p = irl.predict_acceptance_probability([0.0, 1.0, 0.0])
        self.assertGreater(p, 0.5)

    def test_most_valuable_features(self):
        irl = BayesianIRLFromCorrection(n_features=4)
        irl.observe_correction([0.0, 0.0, 0.0, 1.0], denied=False)
        top = irl.most_valuable_features(1)
        self.assertEqual(top[0][0], 3)


class TestActionFeatures(unittest.TestCase):
    def test_extracts_expected_shape(self):
        feats = extract_action_features(0, 1.0, 1, 10, 0.8, 0.5, 0.3, 0.7)
        self.assertEqual(len(feats), 8)

    def test_risk_tier_inverts(self):
        f_low = extract_action_features(0, 1.0, 1, 10, 0.5, 0.5)
        f_high = extract_action_features(0, 1.0, 5, 10, 0.5, 0.5)
        self.assertGreater(f_low[0], f_high[0])


if __name__ == "__main__":
    unittest.main()
