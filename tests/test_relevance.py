from __future__ import annotations

import unittest

from aac.relevance import RelevanceField


class TestRelevanceField(unittest.TestCase):
    def test_explore_drive_drops_when_settled_under_pressure(self) -> None:
        f = RelevanceField()
        # Confident model (low uncertainty), low surprise, real budget pressure
        for _ in range(30):
            f.update(surprise=0.02, pressure=0.7, mean_uncertainty=0.05)
        self.assertLess(f.explore_drive, 0.4)

    def test_surprise_spike_swings_field_to_explore(self) -> None:
        f = RelevanceField()
        for _ in range(30):
            f.update(surprise=0.02, pressure=0.7, mean_uncertainty=0.05)
        before = f.explore_drive
        # Regime change: prediction error spikes, uncertainty re-inflates
        for _ in range(5):
            f.update(surprise=3.0, pressure=0.7, mean_uncertainty=0.8)
        after = f.explore_drive
        self.assertGreater(after, before + 0.2)

    def test_output_bounded(self) -> None:
        f = RelevanceField()
        for _ in range(100):
            f.update(surprise=100.0, pressure=1.0, mean_uncertainty=1.0)
        self.assertGreaterEqual(f.explore_drive, 0.0)
        self.assertLessEqual(f.explore_drive, 1.0)


if __name__ == "__main__":
    unittest.main()
