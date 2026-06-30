"""Tests for the Sachs real causal task (experiments/sachs_task.py).

Robust assertions (not threshold-brittle): the reverse-causation confound is caught, interventional
recall beats correlation, and the governed loop acts on a true cause not the decoy. On REAL data.
"""

from __future__ import annotations

import unittest

from experiments.sachs_task import (
    load_obs, load_int, discover, run_loop_for, ancestors, correlation,
    PROTEINS, INTERVENABLE, GROUND_TRUTH,
)


class SachsRealTask(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.obs = load_obs()
        cls.intd = load_int()

    def test_data_loaded(self):
        self.assertEqual(len(self.obs[0]), 11)
        self.assertGreater(len(self.obs), 800)      # observational rows (~853)
        self.assertGreater(len(self.intd), 5000)    # interventional rows

    def test_akt_is_reverse_causation_confound_for_erk(self):
        # Erk -> Akt in GT, so Akt correlates strongly with Erk but is NOT its cause; do(Akt) must reject
        t, a = PROTEINS.index("Erk"), PROTEINS.index("Akt")
        self.assertGreater(abs(correlation(self.obs, t, a)), 0.8)   # strong correlation
        d = discover("Erk", self.obs, self.intd)
        self.assertNotIn("Akt", d["interv"])        # intervention correctly rejects the confound
        self.assertNotIn("Akt", ancestors("Erk"))   # ground truth agrees Akt is not an ancestor

    def test_intervention_recall_beats_correlation(self):
        targets = [t for t in PROTEINS if (ancestors(t) & set(INTERVENABLE)) - {t}]
        cR = iR = 0.0
        for t in targets:
            d = discover(t, self.obs, self.intd)
            cR += d["corr_pr"][1]; iR += d["interv_pr"][1]
        n = len(targets)
        self.assertGreater(iR / n, cR / n)          # interventional recall > correlation recall

    def test_governed_loop_acts_on_true_cause_not_decoy(self):
        # the loop, driven by the CONFOUNDED correlation proposer (ranks Akt first), acts on a GT cause
        r = run_loop_for("Erk", self.obs, self.intd)
        self.assertEqual(r["status"], "acted")
        self.assertIn(r["applied"], ancestors("Erk"))   # a true causal ancestor
        self.assertNotEqual(r["applied"], "Akt")        # NOT the reverse-causation decoy

    def test_ground_truth_consistency(self):
        self.assertEqual(len(GROUND_TRUTH), 17)
        self.assertIn("Mek", ancestors("Erk"))
        self.assertIn("PKC", ancestors("Erk"))


if __name__ == "__main__":
    unittest.main()
