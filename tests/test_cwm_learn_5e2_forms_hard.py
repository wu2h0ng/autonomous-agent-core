"""CWM-LEARN-5e-2 hard functional-form arena guards."""
from __future__ import annotations

import unittest

from experiments import cwm_learn_5e2_forms_hard as gate


class TestCWMLearn5E2FormsHard(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.small_result = gate.run_hard_form_calibration(seeds=[0], random_draws=1)

    def test_hard_arena_uses_bandpass_forms_to_break_pair_proxy(self) -> None:
        self.assertIn("bandpass_product", gate.HARD_FORM_KINDS)
        for spec in gate.TRUE_HARD_FORMS:
            self.assertEqual(spec["kind"], "bandpass_product")
            self.assertLess(spec["width"], 1.0)

    def test_bandpass_expansion_is_finite_and_width_bounded(self) -> None:
        rows = [[0.0 for _ in range(gate.HARD_FORM_PARAMS["n_raw"])]]

        expanded = gate.expand_hard_forms(rows, gate.TRUE_HARD_FORMS[:2])

        self.assertEqual(len(expanded[0]), gate.HARD_FORM_PARAMS["n_raw"] + 2)
        self.assertTrue(all(abs(value) < 10.0 for value in expanded[0][-2:]))

    def test_small_calibration_has_no_claim_schema_and_pair_screening_control(self) -> None:
        result = self.small_result

        self.assertEqual(result["gate"], "CWM-LEARN-5e-2")
        self.assertEqual(result["claim_scope"], "hard_non_enumerable_function_forms")
        self.assertEqual(result["evidence_level"], "calibration_pilot_not_freeze")
        self.assertEqual(result["screening_baseline"], "finite_pair_products_only")
        self.assertIn("freeze_verdict", result["not_authorized"])
        self.assertIn("autonomy_claim", result["not_authorized"])

    def test_small_calibration_exposes_pair_proxy_gap(self) -> None:
        rec = self.small_result["condA"]["per_seed"][0]

        self.assertGreater(rec["proposed_hard_forms"], rec["pair_screening"])
        self.assertGreaterEqual(rec["s_proposed_hard_forms"], 0.8)
        self.assertLessEqual(rec["s_pair_screening"], 0.6)
        self.assertTrue(self.small_result["summary"]["pair_proxy_gap_observed"])


if __name__ == "__main__":
    unittest.main()
