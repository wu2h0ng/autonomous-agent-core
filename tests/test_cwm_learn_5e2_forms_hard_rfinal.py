"""R-final gate guards for CWM-LEARN-5e-2 hard forms."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from experiments import cwm_learn_5e2_forms_hard_rfinal as gate


class TestCWMLearn5E2FormsHardRFinal(unittest.TestCase):
    def test_rfinal_seed_band_is_disjoint_from_prior_bands(self) -> None:
        prior = set(gate.CALIBRATION_SEEDS) | set(gate.FRESH_SCORED_SEEDS)

        self.assertFalse(prior & set(gate.RFINAL_SEEDS))
        self.assertGreaterEqual(len(gate.RFINAL_SEEDS), 10)

    def test_prereg_lock_rejects_bad_digest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lock = Path(td) / "bad.lock.json"
            lock.write_text(json.dumps({
                "prereg_id": gate.PREREG_ID,
                "files": {gate.PREREG_FILE: "0" * 64},
            }), encoding="utf-8")

            with self.assertRaises(gate.PreregLockDrift):
                gate.verify_prereg_lock(lock)

    def test_rfinal_schema_is_preregistered_and_bounded(self) -> None:
        result = gate.run_rfinal(seeds=[gate.RFINAL_SEEDS[0]], random_draws=1)

        self.assertEqual(result["gate"], "CWM-LEARN-5e-2")
        self.assertEqual(result["evidence_level"], "r_final_preregistered")
        self.assertTrue(result["prereg_lock_verified"])
        self.assertEqual(result["prereg_id"], gate.PREREG_ID)
        self.assertIn(result["summary"]["verdict"], {"MET", "NULL", "INVALID(CONDITION-B-ANOMALY)"})
        self.assertIn("autonomy_claim", result["not_authorized"])
        self.assertIn("product_claim", result["not_authorized"])
        self.assertIn("C6_C7_change", result["not_authorized"])


if __name__ == "__main__":
    unittest.main()
