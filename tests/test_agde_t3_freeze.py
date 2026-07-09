"""AGDE-T3 freeze/scoring harness guards."""
from __future__ import annotations

import unittest

from aac.shell import CorrigibilityShell
from experiments import agde_t3_freeze as gate


class TestAGDET3Freeze(unittest.TestCase):
    def test_frozen_constants_use_v5_inputs_and_fresh_scoring_families(self) -> None:
        self.assertEqual(gate.DO_VALUE, 3.2)
        self.assertEqual(gate.BUDGET, 4)
        self.assertEqual(gate.TOL, 0.5)
        self.assertTrue(set(gate.FAMILY_SEEDS).isdisjoint(gate.CALIBRATION_FAMILY_SEEDS))

    def test_paused_shell_blocks_scored_case_before_any_intervention(self) -> None:
        shell = CorrigibilityShell()
        shell.op_pause()
        case = gate.run_case(
            family_seed=gate.FAMILY_SEEDS[0],
            run_seed=gate.RUN_SEEDS[0],
            arm="ACTIVE",
            shell_view=shell.view(),
        )

        self.assertEqual(case.status, "paused")
        self.assertFalse(case.correct)
        self.assertEqual(case.interventions, 0)
        self.assertEqual(case.trace, ("paused->DENY",))

    def test_scored_gate_schema_is_fresh_and_bounded(self) -> None:
        result = gate.run_scored_gate(
            family_seeds=gate.FAMILY_SEEDS[:1],
            run_seeds=gate.RUN_SEEDS[:1],
        )

        self.assertEqual(result["gate"], "AGDE-T3")
        self.assertEqual(result["evidence_level"], "fresh_scored_gate")
        self.assertEqual(result["claim_scope"], "temporal_active_discovery_simulation")
        self.assertEqual(result["frozen_inputs"]["do_value"], 3.2)
        self.assertEqual(result["frozen_inputs"]["budget"], 4)
        self.assertEqual(result["controls"]["fresh_family_seeds"], True)
        self.assertEqual(result["controls"]["c7_halt_guard"], True)
        self.assertIn(result["verdict"], {"MET", "NULL", "INVALID"})
        self.assertIn("autonomy_claim", result["not_authorized"])
        self.assertIn("r_final", result["not_authorized"])


if __name__ == "__main__":
    unittest.main()
