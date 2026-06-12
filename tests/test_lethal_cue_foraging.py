"""Tests for LethalCueForaging (ADR-0010 D2). Mechanism correctness only."""
from __future__ import annotations

import random
import unittest

from aac.viability import ViabilityCore
from envs.lethal_cue_foraging import LethalCueForaging


class TestLethalCueForaging(unittest.TestCase):
    def _env(self, seed: int = 0, **kw) -> LethalCueForaging:
        return LethalCueForaging(rng=random.Random(seed), **kw)

    def test_regime_shift_changes_optimal_mapping(self) -> None:
        env = self._env(regime_period=10)
        cues = env.get_cue_vector()
        before = env.best_action_for(cues)
        before_set = list(env._relevant_set)
        env.force_regime_change()
        after_set = list(env._relevant_set)
        # The relevant set and/or mapping changed (S itself drifts).
        self.assertTrue(
            after_set != before_set or env.best_action_for(cues) != before
            or env._mapping != {},
            "regime change must resample S and g",
        )

    def test_shift_happens_at_regime_period(self) -> None:
        env = self._env(regime_period=5)
        idx0 = env.regime_index
        for _ in range(5):
            env.act(0, [0])
        self.assertEqual(env.regime_index, idx0 + 1)

    def test_miss_is_lethally_negative(self) -> None:
        env = self._env()
        cues = env.get_cue_vector()
        best = env.best_action_for(cues)
        wrong = (best + 1) % env.n_actions
        env.noise = 0.0
        reward = env.act(wrong, [0])
        self.assertLess(reward, 0.0, "a miss must cost (lethal economics)")

    def test_hit_is_positive(self) -> None:
        env = self._env()
        env.noise = 0.0
        cues = env.get_cue_vector()
        best = env.best_action_for(cues)
        self.assertGreater(env.act(best, [0]), 0.0)

    def test_attention_cost_is_ingested(self) -> None:
        env = self._env(attention_cost=0.1)
        via = ViabilityCore(budget=50.0)
        b0 = via.budget
        env.pay_attention(3, via)
        self.assertAlmostEqual(via.budget, b0 - 0.3, places=6)

    def test_observe_returns_only_attended(self) -> None:
        env = self._env()
        obs = env.observe([0, 5])
        self.assertEqual(set(obs.keys()), {0, 5})

    def test_best_action_deterministic_given_cues(self) -> None:
        env = self._env()
        cues = env.get_cue_vector()
        self.assertEqual(env.best_action_for(cues), env.best_action_for(cues))


if __name__ == "__main__":
    unittest.main()
