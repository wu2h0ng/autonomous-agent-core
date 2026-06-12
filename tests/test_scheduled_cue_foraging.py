from __future__ import annotations

import random
import unittest

from aac.viability import ViabilityCore
from envs.scheduled_cue_foraging import (
    ScheduledLethalCueForaging,
    generate_balanced_relevant_sets,
    max_fixed_subset_coverage,
)


class TestBalancedRelevantSchedule(unittest.TestCase):
    def test_no_fixed_subset_covers_too_many_regimes(self) -> None:
        schedule = generate_balanced_relevant_sets(
            K=12,
            k_rel=2,
            m=3,
            n_regimes=20,
            rng=random.Random(7),
            max_cover_fraction=0.25,
        )

        self.assertEqual(len(schedule), 20)
        self.assertLessEqual(max_fixed_subset_coverage(schedule, K=12, m=3), 5)

    def test_rejects_impossible_attention_size(self) -> None:
        with self.assertRaises(ValueError):
            generate_balanced_relevant_sets(
                K=4,
                k_rel=3,
                m=2,
                n_regimes=5,
                rng=random.Random(1),
            )


class TestScheduledLethalCueForaging(unittest.TestCase):
    def test_uses_schedule_on_regime_shift(self) -> None:
        env = ScheduledLethalCueForaging(
            relevant_sets=[(0, 1), (2, 3)],
            K=4,
            k_rel=2,
            m=2,
            n_actions=3,
            regime_period=1,
            rng=random.Random(1),
        )

        self.assertEqual(env.relevant_set, (0, 1))
        env.act(0, [0, 1])
        self.assertEqual(env.relevant_set, (2, 3))

    def test_attention_cost_is_ingested(self) -> None:
        env = ScheduledLethalCueForaging(
            relevant_sets=[(0, 1)],
            K=4,
            k_rel=2,
            m=2,
            rng=random.Random(1),
            attention_cost=0.25,
        )
        viability = ViabilityCore(budget=10.0, metabolic_cost=0.0)
        env.pay_attention(3, viability)

        self.assertAlmostEqual(viability.budget, 9.25)


if __name__ == "__main__":
    unittest.main()
