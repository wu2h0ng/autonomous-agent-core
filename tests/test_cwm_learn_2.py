"""CWM-LEARN-2 contract tests (RR-0039 §5). Written before the scored gate is trusted.

Locks the environment-axis mechanism + controls (author != adjudicator; founder casts the verdict):
  - invariant prediction beats the pooled statistical baseline UNDER SHIFT on the held-out env;
  - the invariance filter keeps exactly the causal features (capacity positive control);
  - no-shift parity: the invariant advantage is shift-specific (ties when nothing shifts);
  - causal ablation: the invariant arm's ABSOLUTE test AUC collapses to chance without a real
    invariant mechanism (its prediction is mechanism-driven, not artifact);
  - permuted labels collapse the invariant arm to chance (confound negative control).
"""
from __future__ import annotations

import unittest

import experiments.synthetic_scm as scm
from aac.learned_cwm import LearnedCWM


class EnvironmentAxisMechanism(unittest.TestCase):
    def setUp(self):
        self.c = LearnedCWM()
        self.tr = scm.train_envs(0)
        self.te_rows, self.te_labels = scm.test_env(0)

    def test_invariant_beats_pooled_under_shift(self):
        inv = self.c.invariant_predict_auc(self.tr, self.te_rows, self.te_labels, seed=0, mode="invariant")
        pool = self.c.invariant_predict_auc(self.tr, self.te_rows, self.te_labels, seed=0, mode="pooled")
        self.assertGreater(inv, pool)          # invariance earns OOD transfer the statistical arm lacks
        self.assertGreater(inv, 0.6)           # and it is genuinely predictive, not merely > a broken baseline

    def test_capacity_positive_control_keeps_causal_features(self):
        _, kept = self.c.invariant_predict_auc(self.tr, self.te_rows, self.te_labels, seed=0,
                                               mode="invariant", return_kept=True)
        # the organ CAN identify the invariant mechanism: it keeps exactly the causal features
        self.assertEqual(sorted(kept), sorted(scm.CAUSAL_IDX))

    def test_no_shift_parity_advantage_is_shift_specific(self):
        tr = scm.train_envs(0, no_shift=True)
        rows, labels = scm.test_env(0, no_shift=True)
        inv = self.c.invariant_predict_auc(tr, rows, labels, seed=0, mode="invariant")
        pool = self.c.invariant_predict_auc(tr, rows, labels, seed=0, mode="pooled")
        self.assertLess(abs(inv - pool), 0.03)   # no shift -> no invariant advantage

    def test_causal_ablation_collapses_invariant_prediction(self):
        orig = scm.ENV_PARAMS["causal_coeff"]
        try:
            scm.ENV_PARAMS["causal_coeff"] = 0.0
            tr = scm.train_envs(0)
            rows, labels = scm.test_env(0)
            inv = self.c.invariant_predict_auc(tr, rows, labels, seed=0, mode="invariant")
            self.assertLess(inv, 0.6)   # no invariant mechanism -> invariant arm cannot predict (chance)
        finally:
            scm.ENV_PARAMS["causal_coeff"] = orig

    def test_permuted_labels_collapse_invariant_to_chance(self):
        inv = self.c.invariant_predict_auc(self.tr, self.te_rows, self.te_labels, seed=0,
                                           mode="invariant", permute=True)
        self.assertLess(abs(inv - 0.5), 0.05)   # shuffled labels carry no signal -> chance

    def test_env_params_frozen_shape(self):
        p = scm.ENV_PARAMS
        self.assertEqual((p["n_causal"], p["n_spurious"], p["n_noise"]), (2, 2, 2))
        self.assertEqual(p["train_couplings"], [2.5, 1.5, 2.0, -2.2])   # one sign flip, non-zero pooled mean
        self.assertEqual(p["test_coupling"], -1.65)                     # held-out flipped-sign shift


if __name__ == "__main__":
    unittest.main()
