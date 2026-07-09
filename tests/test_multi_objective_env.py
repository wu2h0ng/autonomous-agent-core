"""Contract tests for MultiObjectiveEnv (G11 strategy-regime environment)."""

from __future__ import annotations

import random
import unittest

from envs.multi_objective import MultiObjectiveEnv


class EnvConstruction(unittest.TestCase):
    def test_creates_correct_dimensions(self):
        env = MultiObjectiveEnv(n_actions=8, n_metrics=3, n_regimes=4, rng=random.Random(42))
        self.assertEqual(env.n_actions, 8)
        self.assertEqual(env.n_metrics, 3)
        self.assertEqual(env.n_regimes, 4)

    def test_raises_on_invalid(self):
        with self.assertRaises(ValueError):
            MultiObjectiveEnv(n_actions=0, n_metrics=3, n_regimes=4)
        with self.assertRaises(ValueError):
            MultiObjectiveEnv(n_actions=8, n_metrics=1, n_regimes=4)

    def test_regime_library_fixed(self):
        env = MultiObjectiveEnv(n_actions=6, n_metrics=3, n_regimes=3, rng=random.Random(99))
        self.assertEqual(len(env._library), 3)
        self.assertEqual(len(env._library[0].true_weights), 3)
        self.assertEqual(len(env._library[0].action_rewards), 6)


class RewardsAndWeights(unittest.TestCase):
    def test_scalar_reward_is_dot_product(self):
        env = MultiObjectiveEnv(n_actions=4, n_metrics=3, n_regimes=2,
                                noise=0.0, rng=random.Random(1))
        weights = [0.5, 0.3, 0.2]
        reg = env._library[0]
        action_rewards = reg.action_rewards[0]
        expected = sum(w * action_rewards[k] for k, w in enumerate(weights))
        env.noise = 0.0
        reward = env.act(0, weights)
        self.assertAlmostEqual(reward, expected, places=4)

    def test_different_weights_different_rewards(self):
        env = MultiObjectiveEnv(n_actions=4, n_metrics=3, n_regimes=2,
                                noise=0.0, rng=random.Random(2))
        w1 = [1.0, 0.0, 0.0]
        w2 = [0.0, 1.0, 0.0]
        r1 = env.act(0, w1)
        r2 = env.act(0, w2)
        self.assertNotAlmostEqual(r1, r2, places=4)

    def test_weights_normalize_to_simplex(self):
        env = MultiObjectiveEnv(n_actions=4, n_metrics=3, n_regimes=2, rng=random.Random(3))
        for reg in env._library:
            total = sum(reg.true_weights)
            self.assertAlmostEqual(total, 1.0, places=6)


class RegimeShifts(unittest.TestCase):
    def test_shifts_at_period(self):
        env = MultiObjectiveEnv(n_actions=4, n_metrics=3, n_regimes=3,
                                period=20, rng=random.Random(4))
        initial = env._current
        for _ in range(19):
            self.assertFalse(env.just_shifted)
            env.act(0, [1/3, 1/3, 1/3])
        env.act(0, [1/3, 1/3, 1/3])
        self.assertTrue(env.just_shifted)
        self.assertNotEqual(env._current, initial)

    def test_shifts_to_different_regime(self):
        env = MultiObjectiveEnv(n_actions=4, n_metrics=3, n_regimes=3,
                                period=10, rng=random.Random(5))
        for _ in range(10):
            env.act(0, [1/3, 1/3, 1/3])
        self.assertNotEqual(env._current, 0)

    def test_regime_index_increments(self):
        env = MultiObjectiveEnv(n_actions=4, n_metrics=3, n_regimes=3,
                                period=10, rng=random.Random(6))
        self.assertEqual(env.regime_index, 0)
        for _ in range(10):
            env.act(0, [1/3, 1/3, 1/3])
        self.assertEqual(env.regime_index, 1)


class BestAction(unittest.TestCase):
    def test_oracle_best_action_uses_true_weights(self):
        env = MultiObjectiveEnv(n_actions=4, n_metrics=3, n_regimes=2,
                                rng=random.Random(7))
        best = env.best_action_oracle
        true_w = env.true_weights
        reg = env._library[env._current]
        for a in range(env.n_actions):
            oracle_val = sum(true_w[k] * reg.action_rewards[best][k] for k in range(env.n_metrics))
            other_val = sum(true_w[k] * reg.action_rewards[a][k] for k in range(env.n_metrics))
            self.assertGreaterEqual(oracle_val, other_val)


class History(unittest.TestCase):
    def test_records_history(self):
        env = MultiObjectiveEnv(n_actions=4, n_metrics=3, n_regimes=2, rng=random.Random(8))
        for i in range(5):
            env.act(i % 4, [1/3, 1/3, 1/3])
        hist = env.recent_history()
        self.assertEqual(len(hist), 5)
        self.assertEqual(hist[0]["action"], 0)
        self.assertEqual(hist[4]["action"], 0)

    def test_history_capped(self):
        env = MultiObjectiveEnv(n_actions=4, n_metrics=3, n_regimes=2, rng=random.Random(9))
        for i in range(100):
            env.act(i % 4, [1/3, 1/3, 1/3])
        hist = env.recent_history()
        self.assertLessEqual(len(hist), 40)


class NotAConstant(unittest.TestCase):
    def test_different_actions_different_regret(self):
        env = MultiObjectiveEnv(n_actions=8, n_metrics=3, n_regimes=4, rng=random.Random(10))
        w = [1/3, 1/3, 1/3]
        env.act(0, w)
        r1 = env.last_regret
        env.act(7, w)
        r2 = env.last_regret
        self.assertNotAlmostEqual(r1, r2)


if __name__ == "__main__":
    unittest.main()
