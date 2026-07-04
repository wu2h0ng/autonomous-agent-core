"""AGDE-T3 pilot v5 guards.

Pilot v5 is calibration machinery only. These tests pin the causal-minimality
collapse rule and the result schema before this can be used to set freeze bars.
"""
from __future__ import annotations

import unittest

from experiments import agde_t3_pilot5 as pilot5


class TestAGDET3Pilot5(unittest.TestCase):
    def test_minimality_collapse_requires_unique_orientation_and_minimal_lagset(self) -> None:
        orient_a = {1: frozenset({0})}
        orient_b = {0: frozenset({1})}
        pool = [
            (orient_a, frozenset()),
            (orient_a, frozenset({(0, 1)})),
            (orient_a, frozenset({(1, 2)})),
            (orient_b, frozenset()),
        ]

        self.assertEqual(pilot5.collapse_minimal_survivor(pool, [0, 1]), 0)
        self.assertIsNone(pilot5.collapse_minimal_survivor(pool, [1, 2]))
        self.assertIsNone(pilot5.collapse_minimal_survivor(pool, [0, 3]))

    def test_run_pilot_schema_is_calibration_only(self) -> None:
        result = pilot5.run_pilot(
            families=[9000],
            runs=[0],
            c_values=(3.2,),
            budgets=(4,),
        )

        self.assertEqual(result["evidence_level"], "calibration_pilot_not_freeze")
        self.assertEqual(result["claim_scope"], "apparatus_calibration_only")
        self.assertIn("freeze_verdict", result["not_authorized"])
        self.assertIn("autonomy_claim", result["not_authorized"])
        self.assertIn("c3.2_B4", result["configs"])
        self.assertIn("active_id", result["configs"]["c3.2_B4"])


if __name__ == "__main__":
    unittest.main()
