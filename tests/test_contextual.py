"""Tests for ContextualActionModel (ADR-0010 D1).

The organ that converts attended cues into actions. These verify the
*mechanism is correct* — distinct from whether claim 2 clears G1' (it did
not; that is a research result, not a code defect).
"""
from __future__ import annotations

import unittest

from aac.contextual import ContextualActionModel


class TestContextualLearning(unittest.TestCase):
    def test_learns_best_action_for_a_stable_key(self) -> None:
        cm = ContextualActionModel(n_actions=4)
        ctx = {0: 1, 3: 0}
        for _ in range(20):
            cm.update(ctx, 2, 2.0)  # action 2 always good here
            cm.update(ctx, 0, -1.5)
        self.assertEqual(cm.best_action(ctx), 2)
        self.assertTrue(cm.confident(ctx))

    def test_distinct_keys_are_independent(self) -> None:
        cm = ContextualActionModel(n_actions=4)
        a = {0: 1, 3: 0}
        b = {0: 0, 3: 1}
        for _ in range(20):
            cm.update(a, 1, 2.0)
            cm.update(b, 3, 2.0)
        self.assertEqual(cm.best_action(a), 1)
        self.assertEqual(cm.best_action(b), 3)

    def test_unseen_key_is_not_confident(self) -> None:
        cm = ContextualActionModel(n_actions=4)
        self.assertFalse(cm.confident({9: 1}))

    def test_reframing_switches_best_action_after_reward_flip(self) -> None:
        cm = ContextualActionModel(n_actions=4)
        ctx = {1: 1, 5: 0}
        for _ in range(20):
            cm.update(ctx, 0, 2.0)
        self.assertEqual(cm.best_action(ctx), 0)
        self.assertTrue(cm.confident(ctx))
        # Regime flips: action 0 now punished, action 1 now rewarded.
        for _ in range(20):
            cm.update(ctx, 0, -1.5)
            cm.update(ctx, 1, 2.0)
        self.assertEqual(cm.best_action(ctx), 1, "EMA must re-frame to the new winner")
        self.assertTrue(cm.confident(ctx))

    def test_confidence_requires_positive_clear_leader(self) -> None:
        cm = ContextualActionModel(n_actions=4)
        ctx = {2: 1}
        # All actions punished: no positive leader -> not confident (explore).
        for _ in range(20):
            for a in range(4):
                cm.update(ctx, a, -1.5)
        self.assertFalse(cm.confident(ctx))


if __name__ == "__main__":
    unittest.main()
