from __future__ import annotations

import random
import unittest

from envs.cue_foraging import LatentCueForaging


class TestCueVector(unittest.TestCase):
    """Cue generation basics."""

    def test_cue_vector_length(self) -> None:
        rng = random.Random(42)
        env = LatentCueForaging(K=12, rng=rng)
        cues = env.get_cue_vector()
        self.assertEqual(len(cues), 12)

    def test_cue_values_binary(self) -> None:
        rng = random.Random(42)
        env = LatentCueForaging(K=8, rng=rng)
        for _ in range(20):
            cues = env.get_cue_vector()
            for c in cues:
                self.assertIn(c, (0, 1))

    def test_parameterised_dimensions(self) -> None:
        rng = random.Random(0)
        env = LatentCueForaging(K=6, k_rel=1, m=2, rng=rng)
        self.assertEqual(env.K, 6)
        self.assertEqual(env.k_rel, 1)
        self.assertEqual(env.m, 2)


class TestRegimeDrift(unittest.TestCase):
    """S and g resample on regime change; optimal action can shift."""

    def test_force_regime_change_advances_counter(self) -> None:
        rng = random.Random(7)
        env = LatentCueForaging(K=12, k_rel=2, rng=rng)
        before = env.regime_index
        env.force_regime_change()
        self.assertEqual(env.regime_index, before + 1)

    def test_regime_change_alters_relevant_set(self) -> None:
        """Across many regime changes, the relevant set S is not constant."""
        rng = random.Random(99)
        env = LatentCueForaging(K=12, k_rel=2, rng=rng)
        first_s = frozenset(env._relevant_set)
        sets_seen = {first_s}
        for _ in range(20):
            env.force_regime_change()
            sets_seen.add(frozenset(env._relevant_set))
        self.assertGreater(len(sets_seen), 1, "relevant set never changed")

    def test_regime_change_alters_mapping(self) -> None:
        """Same relevant-cue sub-vector can map to different actions across regimes."""
        rng = random.Random(11)
        env = LatentCueForaging(K=8, k_rel=2, rng=rng, n_actions=4)
        # Build a fixed cue vector
        fixed_cues = tuple([1, 0, 1, 0, 1, 0, 1, 0])
        first_action = env.best_action_for(fixed_cues)
        actions_seen = {first_action}
        for _ in range(20):
            env.force_regime_change()
            actions_seen.add(env.best_action_for(fixed_cues))
        self.assertGreater(len(actions_seen), 1, "mapping never changed")

    def test_auto_regime_change_at_period(self) -> None:
        rng = random.Random(5)
        env = LatentCueForaging(K=8, k_rel=2, regime_period=5, rng=rng)
        before = env.regime_index
        for _ in range(5):
            env.act(action=0, attended_indices=list(range(env.m)))
        self.assertEqual(env.regime_index, before + 1)


class TestAttentionBudget(unittest.TestCase):
    """Agent can only read m cues; attention is costly via viability."""

    def test_attended_subset_size(self) -> None:
        rng = random.Random(42)
        env = LatentCueForaging(K=12, k_rel=2, m=3, rng=rng)
        attended = list(range(3))
        observed = env.observe(attended)
        self.assertEqual(len(observed), 3)

    def test_unattended_cues_not_returned(self) -> None:
        rng = random.Random(42)
        env = LatentCueForaging(K=12, k_rel=2, m=3, rng=rng)
        attended = [0, 5, 11]
        observed = env.observe(attended)
        self.assertEqual(set(observed.keys()), {0, 5, 11})

    def test_attention_cost_via_viability_ingest(self) -> None:
        """Paying attention costs budget (stake-first: cost flows via ingest)."""
        from aac.viability import ViabilityCore

        rng = random.Random(42)
        viability = ViabilityCore(budget=60.0)
        env = LatentCueForaging(K=12, m=3, attention_cost=0.2, rng=rng)
        budget_before = viability.budget
        env.pay_attention(3, viability)
        # 3 cues * 0.2 cost = 0.6 deducted
        self.assertAlmostEqual(viability.budget, budget_before - 0.6)

    def test_attention_cost_fewer_cues(self) -> None:
        from aac.viability import ViabilityCore

        rng = random.Random(0)
        viability = ViabilityCore(budget=60.0)
        env = LatentCueForaging(K=12, m=5, attention_cost=0.3, rng=rng)
        env.pay_attention(2, viability)  # attend 2, not 5
        self.assertAlmostEqual(viability.budget, 60.0 - 0.6)

    def test_cannot_attend_more_than_m(self) -> None:
        from aac.viability import ViabilityCore

        rng = random.Random(0)
        viability = ViabilityCore(budget=60.0)
        env = LatentCueForaging(K=12, m=3, attention_cost=0.2, rng=rng)
        with self.assertRaises(ValueError):
            env.pay_attention(5, viability)  # 5 > m=3

    def test_cannot_exceed_attention_capacity(self) -> None:
        from aac.viability import ViabilityCore

        rng = random.Random(0)
        viability = ViabilityCore(budget=60.0)
        env = LatentCueForaging(K=12, m=3, attention_cost=0.2, rng=rng)
        with self.assertRaises(ValueError):
            env.pay_attention(4, viability)  # 4 > m=3

    def test_can_attend_all_when_m_equals_K(self) -> None:
        from aac.viability import ViabilityCore

        rng = random.Random(1)
        viability = ViabilityCore(budget=60.0)
        env = LatentCueForaging(K=4, m=4, attention_cost=0.2, rng=rng)
        env.pay_attention(4, viability)  # attend all K=4 with m=4
        self.assertAlmostEqual(viability.budget, 60.0 - 0.8)


class TestRewardStructure(unittest.TestCase):
    """Hit vs miss rewards (noise-free path)."""

    def test_hit_reward(self) -> None:
        rng = random.Random(42)
        env = LatentCueForaging(
            K=8, k_rel=2, m=3, rng=rng, noise=0.0, reward_hit=3.0, reward_miss=-0.5
        )
        cues = env.get_cue_vector()
        best = env.best_action_for(cues)
        reward = env.act(action=best, attended_indices=list(range(3)))
        self.assertAlmostEqual(reward, 3.0)

    def test_miss_reward(self) -> None:
        rng = random.Random(42)
        env = LatentCueForaging(
            K=8,
            k_rel=2,
            m=3,
            rng=rng,
            noise=0.0,
            reward_hit=3.0,
            reward_miss=-0.5,
            n_actions=4,
        )
        cues = env.get_cue_vector()
        best = env.best_action_for(cues)
        # pick a non-best action
        wrong = (best + 1) % env.n_actions
        reward = env.act(action=wrong, attended_indices=list(range(3)))
        self.assertAlmostEqual(reward, -0.5)


class TestRegret(unittest.TestCase):
    """last_regret = noise-free optimal minus chosen (matches GridlessSurvival)."""

    def test_regret_zero_on_best(self) -> None:
        rng = random.Random(42)
        env = LatentCueForaging(K=8, k_rel=2, rng=rng, noise=0.5, n_actions=4)
        cues = env.get_cue_vector()
        best = env.best_action_for(cues)
        env.act(action=best, attended_indices=list(range(env.m)))
        self.assertAlmostEqual(env.last_regret, 0.0)

    def test_regret_positive_on_miss(self) -> None:
        rng = random.Random(42)
        env = LatentCueForaging(
            K=8,
            k_rel=2,
            rng=rng,
            noise=0.0,
            reward_hit=3.0,
            reward_miss=-0.5,
            n_actions=4,
        )
        cues = env.get_cue_vector()
        best = env.best_action_for(cues)
        wrong = (best + 1) % env.n_actions
        env.act(action=wrong, attended_indices=list(range(env.m)))
        # regret = hit_reward - miss_reward = 3.0 - (-0.5) = 3.5
        self.assertAlmostEqual(env.last_regret, 3.5)


class TestDeterminism(unittest.TestCase):
    """Same seed -> same sequence."""

    def test_deterministic_with_same_seed(self) -> None:
        results = []
        for _ in range(2):
            rng = random.Random(123)
            env = LatentCueForaging(K=8, k_rel=2, m=3, rng=rng, noise=0.3)
            rewards = []
            for _ in range(10):
                r = env.act(action=0, attended_indices=[0, 1, 2])
                rewards.append(round(r, 6))
            results.append(rewards)
        self.assertEqual(results[0], results[1])


if __name__ == "__main__":
    unittest.main()
