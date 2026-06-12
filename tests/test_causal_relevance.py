from __future__ import annotations

import random
import unittest

from aac.causal_relevance import CausalRelevanceField


class TestCausalRelevanceField(unittest.TestCase):
    def test_entropy_drops_for_predictive_candidate(self) -> None:
        field = CausalRelevanceField(K=5, k_rel=2, m=3, confidence_threshold=0.2)
        before = field.entropy()
        attended = [0, 1, 2]
        predictions = {
            (0, 1): 2.0,
            (0, 2): -1.0,
            (1, 2): -1.0,
        }
        for _ in range(20):
            field.update(
                cues=(1, 0, 1, 0, 1),
                attended=attended,
                action=1,
                reward=2.0,
                prediction_before=predictions,
            )

        self.assertLess(field.entropy(), before)
        self.assertEqual(field.best_hypothesis(), (0, 1))

    def test_surprise_softens_posterior(self) -> None:
        field = CausalRelevanceField(K=5, k_rel=2, m=3, confidence_threshold=0.2)
        attended = [0, 1, 2]
        predictions = {(0, 1): 2.0, (0, 2): -1.0, (1, 2): -1.0}
        for _ in range(20):
            field.update((1, 0, 1, 0, 1), attended, 1, 2.0, predictions)
        focused_entropy = field.entropy()

        field.on_surprise(3.0)

        self.assertGreater(field.entropy(), focused_entropy)

    def test_pressure_only_changes_attention_budget_not_confidence(self) -> None:
        field = CausalRelevanceField(K=6, k_rel=2, m=4)
        confidence = field.confidence()
        low_pressure = field.select_attention(pressure=0.0, rng=random.Random(1))
        high_pressure = field.select_attention(pressure=0.9, rng=random.Random(1))

        self.assertEqual(field.confidence(), confidence)
        self.assertEqual(len(low_pressure), 4)
        self.assertEqual(len(high_pressure), 2)

    def test_ablation_keeps_uniform_posterior(self) -> None:
        field = CausalRelevanceField(K=5, k_rel=2, m=3, ablate_posterior=True)
        before = field.entropy()
        field.update(
            cues=(1, 0, 1, 0, 1),
            attended=[0, 1, 2],
            action=1,
            reward=2.0,
            prediction_before={(0, 1): 2.0, (0, 2): -1.0, (1, 2): -1.0},
        )
        self.assertAlmostEqual(field.entropy(), before)


if __name__ == "__main__":
    unittest.main()
