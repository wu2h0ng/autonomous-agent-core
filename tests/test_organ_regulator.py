"""Contract tests for C7-on OrganRegulator — credit-driven de-weighting and self-calibration.

Hard Boundary #17: tests must fail if the regulator returns constant credit,
fails to de-weight under-performing organs, or bypasses C7.
"""

from __future__ import annotations

import unittest

from aac.organ_regulator import OrganCredit, OrganRegulator


class OrganRegistration(unittest.TestCase):
    def test_register_new_organ(self):
        reg = OrganRegulator()
        oc = reg.register_organ("organ_a")
        self.assertEqual(oc.organ_id, "organ_a")
        self.assertEqual(oc.credit, 0.5)
        self.assertIn("organ_a", reg.organs)

    def test_register_duplicate_raises(self):
        reg = OrganRegulator()
        reg.register_organ("organ_a")
        with self.assertRaises(ValueError):
            reg.register_organ("organ_a")

    def test_register_with_custom_credit(self):
        reg = OrganRegulator()
        oc = reg.register_organ("organ_b", initial_credit=0.8)
        self.assertEqual(oc.credit, 0.8)

    def test_register_invalid_credit_raises(self):
        reg = OrganRegulator()
        with self.assertRaises(ValueError):
            reg.register_organ("bad", initial_credit=1.5)


class CreditUpdate(unittest.TestCase):
    def test_credit_rises_with_positive_outcomes(self):
        reg = OrganRegulator(credit_lr=0.3)
        reg.register_organ("organ_a")
        for _ in range(20):
            reg.record_outcome("organ_a", advice_applied=True, outcome_positive=True)
        self.assertGreater(reg.organs["organ_a"].credit, 0.7)

    def test_credit_falls_with_negative_outcomes(self):
        reg = OrganRegulator(credit_lr=0.3)
        reg.register_organ("organ_a")
        for _ in range(20):
            reg.record_outcome("organ_a", advice_applied=True, outcome_positive=False)
        self.assertLess(reg.organs["organ_a"].credit, 0.3)

    def test_credit_stays_in_bounds(self):
        reg = OrganRegulator(credit_lr=0.5)
        reg.register_organ("organ_a")
        for _ in range(100):
            reg.record_outcome("organ_a", advice_applied=True, outcome_positive=True)
        self.assertLessEqual(reg.organs["organ_a"].credit, 1.0)
        for _ in range(100):
            reg.record_outcome("organ_a", advice_applied=True, outcome_positive=False)
        self.assertGreaterEqual(reg.organs["organ_a"].credit, 0.0)

    def test_advice_not_applied_no_penalty(self):
        reg = OrganRegulator(credit_lr=0.3)
        reg.register_organ("organ_a")
        reg.record_outcome("organ_a", advice_applied=False, outcome_positive=True)
        self.assertAlmostEqual(reg.organs["organ_a"].credit, 0.5, places=1)


class EffectiveWeight(unittest.TestCase):
    def test_high_credit_organ_passes_uncertainty(self):
        reg = OrganRegulator()
        reg.register_organ("organ_a", initial_credit=0.9)
        weight = reg.effective_weight("organ_a", 0.3)
        self.assertAlmostEqual(weight, 0.27, places=3)

    def test_low_credit_organ_dampens_uncertainty(self):
        reg = OrganRegulator()
        reg.register_organ("organ_b", initial_credit=0.1)
        weight = reg.effective_weight("organ_b", 0.5)
        self.assertAlmostEqual(weight, 0.05, places=3)

    def test_deweighted_organ_near_zero_weight(self):
        reg = OrganRegulator()
        reg.register_organ("organ_c", initial_credit=0.9)
        reg.organs["organ_c"].deweighted = True
        weight = reg.effective_weight("organ_c", 0.5)
        self.assertAlmostEqual(weight, 0.005, places=3)

    def test_unknown_organ_returns_raw_uncertainty(self):
        reg = OrganRegulator()
        self.assertEqual(reg.effective_weight("unknown", 0.4), 0.4)


class DeweightMechanism(unittest.TestCase):
    def test_auto_deweight_below_threshold(self):
        reg = OrganRegulator(credit_lr=0.3, min_credit_threshold=0.2)
        reg.register_organ("organ_a")
        for _ in range(30):
            reg.record_outcome("organ_a", advice_applied=True, outcome_positive=False)
            reg.check_deweight("organ_a")
        oc = reg.organs["organ_a"]
        self.assertTrue(oc.deweighted)
        self.assertNotEqual(oc.deweight_reason, "")

    def test_auto_deweight_stale_organ(self):
        reg = OrganRegulator(staleness_limit=5)
        oc = reg.register_organ("organ_a")
        oc.advice_count = 20
        reg.steps = 100
        reason = reg.check_deweight("organ_a")
        self.assertIsNotNone(reason)
        self.assertTrue(reg.organs["organ_a"].deweighted)

    def test_no_deweight_above_threshold(self):
        reg = OrganRegulator(credit_lr=0.3, min_credit_threshold=0.2)
        reg.register_organ("organ_a", initial_credit=0.9)
        reg.record_outcome("organ_a", advice_applied=True, outcome_positive=True)
        reg.check_deweight("organ_a")
        self.assertFalse(reg.organs["organ_a"].deweighted)

    def test_no_deweight_with_insufficient_history(self):
        reg = OrganRegulator(credit_lr=0.3, min_credit_threshold=0.2)
        reg.register_organ("organ_a", initial_credit=0.1)
        reg.record_outcome("organ_a", advice_applied=True, outcome_positive=False)
        reason = reg.check_deweight("organ_a")
        self.assertIsNone(reason)


class ReweightMechanism(unittest.TestCase):
    def test_auto_reweight_on_recovery(self):
        reg = OrganRegulator(recovery_threshold=0.4)
        oc = reg.register_organ("organ_a", initial_credit=0.1)
        oc.deweighted = True
        oc.advice_count = 15
        oc.credit = 0.5
        result = reg.check_reweight("organ_a")
        self.assertTrue(result)
        self.assertFalse(reg.organs["organ_a"].deweighted)

    def test_no_reweight_below_threshold(self):
        reg = OrganRegulator(recovery_threshold=0.4)
        oc = reg.register_organ("organ_a", initial_credit=0.1)
        oc.deweighted = True
        oc.advice_count = 15
        oc.credit = 0.3
        result = reg.check_reweight("organ_a")
        self.assertFalse(result)

    def test_operator_reweight_unconditionally(self):
        reg = OrganRegulator()
        oc = reg.register_organ("organ_a", initial_credit=0.05)
        oc.deweighted = True
        oc.deweight_reason = "low credit"
        result = reg.reweight_organ("organ_a")
        self.assertTrue(result)
        self.assertFalse(reg.organs["organ_a"].deweighted)
        self.assertEqual(reg.organs["organ_a"].credit, 0.5)


class SelfCalibration(unittest.TestCase):
    def test_self_calibrate_returns_float(self):
        reg = OrganRegulator()
        reg.register_organ("a", initial_credit=0.5)
        scale = reg.self_calibrate()
        self.assertIsInstance(scale, float)
        self.assertGreater(scale, 0.0)

    def test_self_calibrate_with_multiple_organs(self):
        reg = OrganRegulator(credit_lr=0.3, self_calibration_lr=0.1)
        reg.register_organ("a", initial_credit=0.9)
        reg.register_organ("b", initial_credit=0.2)
        for _ in range(25):
            reg.record_outcome("a", advice_applied=True, outcome_positive=True)
            reg.record_outcome("b", advice_applied=True, outcome_positive=False)
        scale = reg.self_calibrate()
        self.assertGreater(scale, 0.0)
        self.assertLess(scale, 3.0)


class StateRoundtrip(unittest.TestCase):
    def test_roundtrip(self):
        reg = OrganRegulator()
        reg.register_organ("a", initial_credit=0.7)
        reg.register_organ("b", initial_credit=0.3)
        reg.record_outcome("a", advice_applied=True, outcome_positive=True)
        reg.record_outcome("b", advice_applied=True, outcome_positive=False)
        reg.steps = 50

        saved = reg.state()
        restored = OrganRegulator()
        restored.restore(saved)
        self.assertEqual(restored.steps, 50)
        self.assertIn("a", restored.organs)
        self.assertAlmostEqual(restored.organs["a"].credit, reg.organs["a"].credit)


class NotAConstant(unittest.TestCase):
    def test_different_organs_different_credits(self):
        reg = OrganRegulator(credit_lr=0.3)
        reg.register_organ("good", initial_credit=0.5)
        reg.register_organ("bad", initial_credit=0.5)
        for _ in range(20):
            reg.record_outcome("good", advice_applied=True, outcome_positive=True)
            reg.record_outcome("bad", advice_applied=True, outcome_positive=False)
        self.assertGreater(
            reg.organs["good"].credit,
            reg.organs["bad"].credit,
        )

    def test_different_organs_different_weights(self):
        reg = OrganRegulator()
        reg.register_organ("good", initial_credit=0.9)
        reg.register_organ("bad", initial_credit=0.2)
        w_good = reg.effective_weight("good", 0.5)
        w_bad = reg.effective_weight("bad", 0.5)
        self.assertGreater(w_good, w_bad)


if __name__ == "__main__":
    unittest.main()
