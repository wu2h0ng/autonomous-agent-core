from __future__ import annotations

import unittest

from aac.viability import ViabilityCore


class TestViabilityCore(unittest.TestCase):
    def test_metabolize_and_death(self) -> None:
        v = ViabilityCore(budget=2.0, metabolic_cost=1.0)
        self.assertTrue(v.alive)
        v.metabolize()
        self.assertTrue(v.alive)
        v.metabolize()
        self.assertFalse(v.alive)  # budget == 0.0, not > death_threshold

    def test_pressure_rises_as_budget_drops(self) -> None:
        v = ViabilityCore(budget=50.0, safe_budget=50.0, death_threshold=0.0)
        self.assertAlmostEqual(v.pressure, 0.0)
        v.budget = 25.0
        self.assertAlmostEqual(v.pressure, 0.5)
        v.budget = 0.0
        self.assertAlmostEqual(v.pressure, 1.0)
        v.budget = 80.0  # above safe -> clamped
        self.assertAlmostEqual(v.pressure, 0.0)

    def test_ingest_caps_at_capacity(self) -> None:
        v = ViabilityCore(budget=95.0, capacity=100.0)
        v.ingest(20.0)
        self.assertEqual(v.budget, 100.0)
        v.ingest(-30.0)
        self.assertEqual(v.budget, 70.0)


if __name__ == "__main__":
    unittest.main()
