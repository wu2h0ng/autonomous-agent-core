"""Tests for StalenessEnv non-stationary-hazard environment (T-P4.2)."""
from __future__ import annotations

import random
import unittest

from envs.staleness import StalenessEnv


class TestStalenessEnv(unittest.TestCase):
    def test_deterministic_under_seed(self) -> None:
        a = StalenessEnv(rng=random.Random(0))
        b = StalenessEnv(rng=random.Random(0))
        ra = [a.act(i % a.n_actions) for i in range(200)]
        rb = [b.act(i % b.n_actions) for i in range(200)]
        self.assertEqual(ra, rb)

    def test_non_stationary_hazard_fast_then_slow(self) -> None:
        """FAST epoch must shift more often than the following SLOW epoch."""
        env = StalenessEnv(rng=random.Random(1), period_fast=20, period_slow=120, epoch_len=240)
        fast_shifts = slow_shifts = 0
        for _ in range(240):  # epoch 0 = FAST
            env.act(0)
            fast_shifts += env.just_shifted
        for _ in range(240):  # epoch 1 = SLOW
            env.act(0)
            slow_shifts += env.just_shifted
        self.assertGreater(fast_shifts, slow_shifts)
        self.assertGreaterEqual(fast_shifts, 240 // 20 - 1)

    def test_shift_changes_regime_index_and_best_action_can_move(self) -> None:
        env = StalenessEnv(rng=random.Random(3), period_fast=10, period_slow=10, epoch_len=10_000)
        idx0 = env.regime_index
        moved = False
        prev_best = env.best_action
        for _ in range(50):
            env.act(0)
            if env.just_shifted and env.best_action != prev_best:
                moved = True
            prev_best = env.best_action
        self.assertGreater(env.regime_index, idx0)
        self.assertTrue(moved, "regime shifts should sometimes move the best action")

    def test_last_regret_is_gap_to_best(self) -> None:
        env = StalenessEnv(n_actions=4, rng=random.Random(5))
        env.act(env.best_action)
        self.assertAlmostEqual(env.last_regret, 0.0)

    def test_expected_random_regret_is_max_minus_mean(self) -> None:
        env = StalenessEnv(n_actions=4, rng=random.Random(6))
        env.act(0)
        regime = env._regime
        self.assertAlmostEqual(
            env.expected_random_regret, max(regime) - sum(regime) / len(regime)
        )

    def test_validation(self) -> None:
        for bad in (
            dict(n_actions=0),
            dict(period_fast=0),
            dict(period_slow=-1),
            dict(epoch_len=0),
        ):
            with self.assertRaises(ValueError):
                StalenessEnv(rng=random.Random(0), **bad)


if __name__ == "__main__":
    unittest.main()
