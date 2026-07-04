"""Fresh scored gate guards for CWM-LEARN-5e-2 hard forms."""
from __future__ import annotations

import unittest

from experiments import cwm_learn_5e2_forms_hard_freeze as gate


class TestCWMLearn5E2FormsHardFreeze(unittest.TestCase):
    def test_scoring_seeds_are_disjoint_from_calibration(self) -> None:
        self.assertFalse(set(gate.CALIBRATION_SEEDS) & set(gate.SCORING_SEEDS))
        self.assertGreaterEqual(len(gate.SCORING_SEEDS), 6)

    def test_verdict_logic_has_condition_b_invalidation(self) -> None:
        cond_a = {
            "median_s_proposed_hard_forms": 1.0,
            "median_s_pair_screening": 0.0,
            "median_s_random_hard_forms": 0.0,
            "proposed_gt_pair_screening": "6/6",
            "proposed_gt_random_hard_forms": "6/6",
        }
        cond_b_bad = {"median_s_proposed_hard_forms": 0.5, "median_s_random_hard_forms": 0.0}

        self.assertEqual(gate._decide_verdict(cond_a, cond_b_bad, n=6), "INVALID(CONDITION-B-ANOMALY)")

    def test_fresh_gate_schema_is_bounded_and_not_rfinal(self) -> None:
        result = gate.run_scored_gate(seeds=[40], random_draws=1)

        self.assertEqual(result["gate"], "CWM-LEARN-5e-2")
        self.assertEqual(result["evidence_level"], "fresh_scored_gate_not_r_final")
        self.assertEqual(result["calibration_seed_source"], list(gate.CALIBRATION_SEEDS))
        self.assertIn(result["summary"]["verdict"], {"MET", "NULL", "INVALID(CONDITION-B-ANOMALY)"})
        self.assertIn("r_final", result["not_authorized"])
        self.assertIn("autonomy_claim", result["not_authorized"])


if __name__ == "__main__":
    unittest.main()
