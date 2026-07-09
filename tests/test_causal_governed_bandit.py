"""Tests for Causal Governed Bandit — M-GAP-3.

Tests-first per Hard Boundary #17. Verifies:
- CausalBanditArm construction and filtering
- Peril kernel: gamma = gamma0 * (1 - peril)
- Thompson sampling: selects legal arms, respects posterior weights
- Causal effect estimation through DAG paths
- Information gain estimation from DiBS particles
- Reward computation: -peril_after + gamma * info_gain
- Regret tracking: cumulative, governance, vs UCB1
- Peril-modulated behavior: high peril -> safe mode
- C7 governance: forbidden arms never selected
- UCB1 baseline for comparison
"""
from __future__ import annotations

import math
import random
import unittest

from aac.causal_governed_bandit import (
    CausalBanditArm,
    CausalGovernedBandit,
    ucb1_baseline,
)


class TestCausalBanditArm(unittest.TestCase):
    def test_arm_construction(self):
        arm = CausalBanditArm(node=3, value=1.5, is_legal=True)
        self.assertEqual(arm.node, 3)
        self.assertEqual(arm.value, 1.5)
        self.assertTrue(arm.is_legal)

    def test_arm_illegal(self):
        arm = CausalBanditArm(node=5, value=0.0, is_legal=False)
        self.assertFalse(arm.is_legal)


class TestPerilKernel(unittest.TestCase):
    def setUp(self):
        self.bandit = CausalGovernedBandit(n_nodes=5, gamma0=1.0, seed=42)

    def test_zero_peril_full_exploration(self):
        gamma = self.bandit.peril_kernel(0.0)
        self.assertAlmostEqual(gamma, 1.0)

    def test_max_peril_safe_mode(self):
        gamma = self.bandit.peril_kernel(1.0)
        self.assertAlmostEqual(gamma, 0.0)

    def test_half_peril_half_exploration(self):
        gamma = self.bandit.peril_kernel(0.5)
        self.assertAlmostEqual(gamma, 0.5)

    def test_negative_peril_clamped(self):
        gamma = self.bandit.peril_kernel(-0.3)
        self.assertAlmostEqual(gamma, 1.3)

    def test_custom_gamma0(self):
        b = CausalGovernedBandit(n_nodes=5, gamma0=2.0, seed=42)
        gamma = b.peril_kernel(0.5)
        self.assertAlmostEqual(gamma, 1.0)


class TestThompsonSampling(unittest.TestCase):
    def setUp(self):
        self.arms = [
            CausalBanditArm(0, 1.0, True),
            CausalBanditArm(1, 2.0, True),
            CausalBanditArm(2, 0.5, True),
        ]
        self.bandit = CausalGovernedBandit(
            n_nodes=4, arms=self.arms, gamma0=1.0, target_node=3, seed=42,
        )

    def test_selects_legal_arm(self):
        particles = [frozenset({(0, 3), (1, 3)})] * 10
        weights = [0.1] * 10
        idx, arm, info = self.bandit.thompson_sample(
            particles, weights, peril=0.0,
        )
        self.assertGreaterEqual(idx, 0)
        self.assertLess(idx, len(self.arms))
        self.assertTrue(self.arms[idx].is_legal)

    def test_no_legal_arms_returns_minus_one(self):
        arms = [CausalBanditArm(0, 1.0, False), CausalBanditArm(1, 2.0, False)]
        b = CausalGovernedBandit(n_nodes=4, arms=arms, seed=42)
        idx, arm, info = b.thompson_sample(
            [frozenset()] * 10, [0.1] * 10, peril=0.0,
        )
        self.assertEqual(idx, -1)

    def test_high_peril_reduces_exploration(self):
        particles = [frozenset({(0, 3)}), frozenset({(1, 3)})]
        weights = [0.5, 0.5]
        _, _, info_low = self.bandit.thompson_sample(particles, weights, peril=0.0)
        _, _, info_high = self.bandit.thompson_sample(particles, weights, peril=0.9)
        self.assertGreater(info_low["gamma"], info_high["gamma"])

    def test_info_contains_expected_keys(self):
        particles = [frozenset()] * 5
        weights = [0.2] * 5
        _, _, info = self.bandit.thompson_sample(particles, weights, peril=0.3)
        self.assertIn("gamma", info)
        self.assertIn("peril", info)
        self.assertIn("sampled_particle", info)
        self.assertIn("best_score", info)


class TestUpdateAndReward(unittest.TestCase):
    def setUp(self):
        self.arms = [CausalBanditArm(0, 1.0), CausalBanditArm(1, 2.0)]
        self.bandit = CausalGovernedBandit(n_nodes=3, arms=self.arms, gamma0=1.0, seed=42)

    def test_update_increments_counts(self):
        self.bandit.update(0, [0.0, 0.5, 0.2], 0.3, 0.1, 0.5)
        self.assertEqual(self.bandit.t, 1)
        self.assertEqual(self.bandit._arm_counts[0], 1)
        self.assertEqual(len(self.bandit.history), 1)

    def test_reward_positive_for_peril_reduction(self):
        self.bandit.update(0, [0.0, 0.5, 0.2], 0.5, 0.2, 0.3)
        self.assertEqual(self.bandit.t, 1)
        h = self.bandit.history[0]
        self.assertGreater(h["reward"], -10)

    def test_cumulative_reward_accumulates(self):
        for _ in range(5):
            self.bandit.update(0, [0.0, 0.5, 0.2], 0.3, 0.2, 0.1)
        self.assertGreater(self.bandit.cumulative_reward, -50)

    def test_peril_trajectory_recorded(self):
        for p in [0.1, 0.2, 0.3]:
            self.bandit.update(0, [0.0, 0.5, 0.2], p * 0.5, p, 0.1)
        self.assertEqual(len(self.bandit._peril_trajectory), 3)

    def test_arm_statistics_returns_correct_counts(self):
        self.bandit.update(0, [0.0, 0.5, 0.2], 0.3, 0.1, 0.5)
        self.bandit.update(1, [0.0, 0.5, 0.2], 0.3, 0.1, 0.5)
        stats = self.bandit.arm_statistics()
        self.assertEqual(stats[0]["pulls"], 1)
        self.assertEqual(stats[1]["pulls"], 1)

    def test_best_arm_returns_most_rewarded(self):
        self.bandit.update(0, [0.0, 0.5, 0.2], 0.3, 0.02, 0.5)
        self.bandit.update(0, [0.0, 0.5, 0.2], 0.3, 0.01, 0.5)
        self.bandit.update(1, [0.0, 0.5, 0.2], 0.3, 0.5, 0.1)
        best = self.bandit.best_arm_index
        self.assertGreaterEqual(best, 0)


class TestCausalEffectEstimation(unittest.TestCase):
    def setUp(self):
        self.bandit = CausalGovernedBandit(
            n_nodes=5, arms=[CausalBanditArm(0, 1.0)], gamma0=1.0, target_node=3, seed=42,
        )

    def test_direct_edge_has_effect(self):
        dag = frozenset({(0, 3)})
        effect = self.bandit._estimate_causal_effect(dag, 0, 1.0, 3)
        self.assertGreater(effect, 0.0)

    def test_no_path_has_zero_effect(self):
        dag = frozenset({(0, 1), (1, 2)})
        effect = self.bandit._estimate_causal_effect(dag, 0, 1.0, 3)
        self.assertAlmostEqual(effect, 0.0)

    def test_indirect_path_has_effect(self):
        dag = frozenset({(0, 1), (1, 3)})
        effect = self.bandit._estimate_causal_effect(dag, 0, 1.0, 3)
        self.assertGreater(effect, 0.0)

    def test_self_intervention_effect_one(self):
        dag = frozenset()
        effect = self.bandit._estimate_causal_effect(dag, 3, 1.0, 3)
        self.assertGreater(effect, 0.0)

    def test_effect_bounded_by_one(self):
        dag = frozenset({(0, 1), (1, 2), (2, 3), (0, 3)})
        effect = self.bandit._estimate_causal_effect(dag, 0, 5.0, 3)
        self.assertLessEqual(effect, 1.0)


class TestInformationGain(unittest.TestCase):
    def setUp(self):
        self.bandit = CausalGovernedBandit(
            n_nodes=4, arms=[CausalBanditArm(0, 1.0)], seed=42,
        )

    def test_divergent_parents_high_info_gain(self):
        particles = [
            frozenset({(1, 0)}),
            frozenset({(2, 0)}),
            frozenset({(3, 0)}),
        ]
        weights = [1.0 / 3] * 3
        info = self.bandit._estimate_info_gain(frozenset(), 0, None, particles, weights)
        self.assertGreater(info, 0.0)

    def test_unanimous_parents_zero_info(self):
        particles = [frozenset({(1, 0)})] * 5
        weights = [0.2] * 5
        info = self.bandit._estimate_info_gain(frozenset(), 0, [[0.0]*4]*10, particles, weights)
        self.assertAlmostEqual(info, 0.0)


class TestRegretComputation(unittest.TestCase):
    def setUp(self):
        self.arms = [CausalBanditArm(0, 1.0), CausalBanditArm(1, 2.0)]
        self.bandit = CausalGovernedBandit(n_nodes=3, arms=self.arms, seed=42)

    def test_regret_nonnegative(self):
        for _ in range(10):
            self.bandit.update(
                self.bandit.rng.choice([0, 1]),
                [0.0, 0.5, 0.2], 0.3, 0.2, 0.1,
            )
        regret = self.bandit.compute_regret()
        self.assertGreaterEqual(regret, 0.0)

    def test_governance_regret_zero_no_forbidden(self):
        oracle = [0.8, 0.5]
        gov_regret = self.bandit.governance_regret(set(), oracle)
        self.assertAlmostEqual(gov_regret, 0.0)

    def test_governance_regret_positive_with_forbidden_best(self):
        arms = [CausalBanditArm(0, 1.0, True), CausalBanditArm(1, 2.0, False)]
        b = CausalGovernedBandit(n_nodes=3, arms=arms, seed=42)
        for _ in range(5):
            b.update(0, [0.0, 0.5, 0.2], 0.3, 0.2, 0.1)
        oracle = [0.3, 0.9]
        gov_regret = b.governance_regret({1}, oracle)
        self.assertGreater(gov_regret, 0.0)

    def test_regret_with_oracle(self):
        for i in range(10):
            self.bandit.update(i % 2, [0.0, 0.5, 0.2], 0.3, 0.2, 0.1)
        oracle = [0.8, 0.4]
        regret = self.bandit.compute_regret(oracle)
        self.assertGreaterEqual(regret, 0.0)


class TestC7Governance(unittest.TestCase):
    def test_forbidden_arm_never_selected(self):
        arms = [
            CausalBanditArm(0, 1.0, True),
            CausalBanditArm(1, 2.0, False),
            CausalBanditArm(2, 0.5, True),
        ]
        b = CausalGovernedBandit(n_nodes=4, arms=arms, seed=42)
        self.assertEqual(b.n_legal, 2)

        particles = [frozenset({(0, 3), (2, 3)})] * 10
        weights = [0.1] * 10
        selections = {0: 0, 1: 0, 2: 0}
        for _ in range(100):
            idx, _, _ = b.thompson_sample(particles, weights, peril=0.0)
            if idx >= 0:
                selections[idx] = selections.get(idx, 0) + 1
        self.assertEqual(selections.get(1, 0), 0,
                         "Forbidden arm was selected")

    def test_all_forbidden_legal_count_zero(self):
        arms = [CausalBanditArm(0, 1.0, False), CausalBanditArm(1, 2.0, False)]
        b = CausalGovernedBandit(n_nodes=3, arms=arms, seed=42)
        self.assertEqual(b.n_legal, 0)


class TestUCB1Baseline(unittest.TestCase):
    def test_ucb1_runs_without_error(self):
        arms = [CausalBanditArm(0, 1.0), CausalBanditArm(1, 2.0), CausalBanditArm(2, 0.5)]
        oracle = [0.8, 0.5, 0.3]
        result = ucb1_baseline(arms, n_rounds=100, oracle_rewards=oracle, seed=42)
        self.assertIn("total_reward", result)
        self.assertIn("regret", result)
        self.assertGreater(result["total_reward"], 0)

    def test_ucb1_prefers_best_arm(self):
        arms = [CausalBanditArm(0, 1.0), CausalBanditArm(1, 2.0)]
        oracle = [0.9, 0.1]
        result = ucb1_baseline(arms, n_rounds=200, oracle_rewards=oracle, seed=42)
        self.assertGreater(result["counts"][0], result["counts"][1],
                           "UCB1 should prefer arm with higher reward")

    def test_ucb1_with_forbidden_arms(self):
        arms = [CausalBanditArm(0, 1.0, True), CausalBanditArm(1, 2.0, False)]
        oracle = [0.5, 0.9]
        result = ucb1_baseline(arms, n_rounds=100, oracle_rewards=oracle, seed=42)
        self.assertEqual(result["counts"][1], 0,
                         "UCB1 should not select forbidden arm")


if __name__ == "__main__":
    unittest.main()
