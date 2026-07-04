"""CWM-LEARN-5e-2 zero-shot calibration guards."""
from __future__ import annotations

import unittest

import experiments.synthetic_scm_highdim as hd
from experiments import cwm_learn_5e2 as gate


class TestCWMLearn5E2(unittest.TestCase):
    def test_zero_shot_gate_uses_frozen_data_blind_proposals(self) -> None:
        result = gate.run_zero_shot_calibration(seeds=[0], train_sizes=[40], random_draws=2)

        self.assertEqual(result["gate"], "CWM-LEARN-5e-2")
        self.assertEqual(result["proposal_source"], "frozen_data_blind_5e_union")
        self.assertEqual(result["evidence_level"], "calibration_pilot_not_freeze")
        self.assertGreater(result["union_size"], 0)
        self.assertIn("freeze_verdict", result["not_authorized"])
        self.assertIn("autonomy_claim", result["not_authorized"])

    def test_train_size_override_is_restored(self) -> None:
        original = hd.HD_PARAMS["n_train"]

        gate.run_zero_shot_calibration(seeds=[0], train_sizes=[30], random_draws=1)

        self.assertEqual(hd.HD_PARAMS["n_train"], original)

    def test_screening_uses_later_data_not_prompt(self) -> None:
        result = gate.run_zero_shot_calibration(seeds=[0], train_sizes=[40], random_draws=2)
        rec = result["train_sizes"]["40"]["per_seed"][0]

        self.assertEqual(rec["seed"], 0)
        self.assertIn("zeroshot", rec)
        self.assertIn("screening", rec)
        self.assertIn("random_median", rec)
        self.assertIn("oracle", rec)


if __name__ == "__main__":
    unittest.main()
