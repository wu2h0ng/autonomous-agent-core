from __future__ import annotations

import unittest

from aac.world_model import ActionOutcomeModel


class TestActionOutcomeModel(unittest.TestCase):
    def test_estimate_converges_toward_reward(self) -> None:
        m = ActionOutcomeModel(n_actions=3, lr=0.3)
        for _ in range(50):
            m.update(0, 5.0)
        self.assertAlmostEqual(m.mu[0], 5.0, places=1)
        self.assertEqual(m.best_action(), 0)

    def test_surprise_spikes_on_regime_change(self) -> None:
        m = ActionOutcomeModel(n_actions=2, lr=0.3)
        for _ in range(40):
            m.update(0, 1.0)
        settled = m.update(0, 1.0)
        spike = m.update(0, 9.0)  # the world changed under this action
        self.assertGreater(spike, settled)
        self.assertGreater(m.uncertainty[0], 0.0)

    def test_unvisited_actions_keep_high_uncertainty(self) -> None:
        m = ActionOutcomeModel(n_actions=3)
        for _ in range(20):
            m.update(0, 2.0)
        self.assertLess(m.uncertainty[0], m.uncertainty[1])


if __name__ == "__main__":
    unittest.main()
