"""STAGE-4 battery — smoke/contract tests (prereg 9a9384b).

The battery is orchestration over already-tested modules; these assert the harness runs,
the frozen verdict mapping is mechanical, the process criteria stay labeled non-capability,
and the Sachs STAT-with-budget arm is computed (not asserted to a value — that is data).
"""
from __future__ import annotations

import unittest

from experiments.stage4_acceptance_battery import a1_a7, sachs_stat_with_budget


class Battery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = a1_a7()

    def test_process_criteria_labeled_non_capability(self):
        self.assertIn("not capability evidence", self.b["A4"]["label"])
        self.assertIn("not capability evidence", self.b["A5"]["label"])

    def test_a3_knockout_diverges(self):
        self.assertEqual(self.b["A3"]["attributor_retry_same"], 0)
        self.assertGreater(self.b["A3"]["knockout_retry_same"], 0)

    def test_a5_zero_high_stakes_auto_act(self):
        self.assertEqual(self.b["A5"]["high_stakes_auto_acts"], 0)

    def test_a1_reports_intervention_cost_honestly(self):
        self.assertIn("argmax_costs_more_interventions", self.b["A1"])
        self.assertIn("note", self.b["A1"])

    def test_a7_autonomy_reading_is_tie(self):
        self.assertIn("TIE", self.b["A7"]["autonomy_reading"])


class SachsArm(unittest.TestCase):
    def test_stat_with_budget_computed(self):
        s = sachs_stat_with_budget()
        for k in ("interv_recall", "corr_recall", "stat_with_budget_recall", "headline_downgraded"):
            self.assertIn(k, s)
        # the honest structural fact: intervention recall strictly exceeds correlation recall
        self.assertGreater(s["interv_recall"], s["corr_recall"])


if __name__ == "__main__":
    unittest.main()
