"""CWM-LEARN-5e-2 non-enumerable functional-form calibration guards."""
from __future__ import annotations

import math
import unittest

from experiments import cwm_learn_5e2_forms as gate


class TestCWMLearn5E2Forms(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.small_result = gate.run_form_calibration(seeds=[0], random_draws=2)

    def test_form_specs_are_typed_and_not_pair_products(self) -> None:
        for spec in gate.PROPOSED_FORMS:
            self.assertIn("kind", spec)
            self.assertIn(spec["kind"], gate.FORM_KINDS)
            self.assertNotEqual(spec["kind"], "pair_product")

    def test_expand_forms_adds_finite_feature_columns(self) -> None:
        rows = [[1.0 for _ in range(gate.FORM_PARAMS["n_raw"])]]

        expanded = gate.expand_forms(rows, gate.PROPOSED_FORMS[:3])

        self.assertEqual(len(expanded[0]), gate.FORM_PARAMS["n_raw"] + 3)
        for value in expanded[0][-3:]:
            self.assertTrue(math.isfinite(value))

    def test_calibration_schema_is_bounded_and_has_condition_b_control(self) -> None:
        result = self.small_result

        self.assertEqual(result["gate"], "CWM-LEARN-5e-2")
        self.assertEqual(result["claim_scope"], "non_enumerable_function_forms")
        self.assertEqual(result["evidence_level"], "calibration_pilot_not_freeze")
        self.assertEqual(result["screening_baseline"], "finite_pair_products_only")
        self.assertIn("condA", result)
        self.assertIn("condB", result)
        self.assertIn("freeze_verdict", result["not_authorized"])
        self.assertIn("autonomy_claim", result["not_authorized"])

    def test_per_seed_record_compares_forms_against_pair_screening(self) -> None:
        result = self.small_result
        rec = result["condA"]["per_seed"][0]

        self.assertIn("proposed_forms", rec)
        self.assertIn("pair_screening", rec)
        self.assertIn("random_forms_median", rec)
        self.assertIn("oracle_forms", rec)
        self.assertIn("s_proposed_forms", rec)


if __name__ == "__main__":
    unittest.main()
