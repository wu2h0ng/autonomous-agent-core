from __future__ import annotations

import unittest

from aac.factorized_contextual import (
    FactorizedContextualActionModel,
    candidate_sets_from_attended,
)


class TestFactorizedContextualActionModel(unittest.TestCase):
    def test_equivalent_attention_supersets_share_learning(self) -> None:
        model = FactorizedContextualActionModel(n_actions=3, lr=0.5, margin=0.4)
        cues_a = (1, 0, 1, 0)
        cues_b = (1, 0, 0, 1)
        hypothesis = (0, 1)

        for _ in range(6):
            model.update(cues_a, hypothesis, action=2, reward=2.0)

        self.assertTrue(model.confident(cues_b, hypothesis))
        self.assertEqual(model.best_action(cues_b, hypothesis), 2)

    def test_different_hypothesis_is_independent(self) -> None:
        model = FactorizedContextualActionModel(n_actions=3, lr=0.5, margin=0.4)
        cues = (1, 0, 1, 0)
        for _ in range(6):
            model.update(cues, (0, 1), action=2, reward=2.0)

        self.assertFalse(model.confident(cues, (2, 3)))

    def test_candidate_sets_from_attended(self) -> None:
        self.assertEqual(
            candidate_sets_from_attended([3, 1, 2], k_rel=2),
            [(1, 2), (1, 3), (2, 3)],
        )


if __name__ == "__main__":
    unittest.main()
