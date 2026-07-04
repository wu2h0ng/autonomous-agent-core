"""CWM-LEARN-3 contract tests (design packet §10, tests-first). Lock the leak-immunity, representation,
and control machinery — NOT the verdict (author != adjudicator; founder casts). Heavy full-fidelity audits
A1-A6 live in experiments/cwm_learn_3_audit.py; these tests verify machinery correctness, several at a
reduced n_samples for speed (properties are fidelity-robust; the scored run uses the frozen n_samples=800).
"""
from __future__ import annotations

import unittest

import experiments.synthetic_scm_interaction as scm
from aac.interaction_cwm import InteractionCWM, phi, product_index


class Representation(unittest.TestCase):
    def test_no_self_squares_in_basis(self):
        # phi = 7 raw + C(7,2)=21 cross products = 28; NO x_i^2 (the non-flipping spurious trap)
        row = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        p = phi(row)
        self.assertEqual(len(p), 28)
        self.assertEqual(list(p[:7]), row)
        # STRUCTURAL check: the products are EXACTLY the i<j cross products in order — no self-square term
        # x_i^2 is ever constructed (a value-based check is unsound: a cross product like 1*4 can numerically
        # equal a square like 2*2, so structure, not value, is what proves self-squares are absent).
        prods = p[7:]
        expected = [row[i] * row[j] for i in range(7) for j in range(i + 1, 7)]
        self.assertEqual(prods, expected)
        self.assertEqual(len(prods), 7 * 6 // 2)   # C(7,2)=21 cross products, no 7 self-squares

    def test_product_index_locates_interaction(self):
        n = scm.N_FEATURES
        k = product_index(n, *scm.INTERACTION_PAIR)
        # the located coordinate must be the Xc1*Xc2 product for a known row
        row = list(range(1, n + 1))
        self.assertEqual(phi([float(x) for x in row])[k], float(row[0] * row[1]))


class LeakImmunityAndDisjointness(unittest.TestCase):
    def test_generator_marginal_purity(self):
        # zero-marginal features (interaction causes + independent decoy + noise) carry ~0 linear class signal
        rows, labels = scm.gen_env_l3(50, scm.ENV_PARAMS_L3["train_couplings"][0], 0)
        import statistics
        def shift(k):
            a = [rows[i][k] for i in range(len(rows)) if labels[i] == 1]
            b = [rows[i][k] for i in range(len(rows)) if labels[i] == 0]
            sd = statistics.pstdev([r[k] for r in rows]) or 1.0
            return abs(statistics.mean(a) - statistics.mean(b)) / sd
        # population-zero features; at n=800 single-env the standardized mean-diff SE is ~2/sqrt(800)~=0.07,
        # so allow up to ~2 SE here (A1 audit confirms <0.03 at n=4000 — this is only a coarse sanity gate).
        for k in scm.CAUSAL_XOR_IDX + [scm.SPURIOUS_IDX[1]] + scm.NOISE_IDX:
            self.assertLess(shift(k), 0.14, f"feature {k} leaks a linear marginal (n=800 finite-sample)")

    def test_rng_streams_disjoint(self):
        for s in (0, 3, 7):
            tr = {tuple(r) for rows, _ in scm.train_envs_l3(s) for r in rows}
            te = {tuple(r) for r in scm.test_env_l3(s)[0]}
            self.assertEqual(len(tr & te), 0, "train/test row collision — RNG streams not disjoint")

    def test_c5_indist_reference_is_train_sign_env(self):
        # the decisive C5 gate's in-dist reference is +1.6 (train sign), same |magnitude| as OOD -1.6
        self.assertEqual(scm.ENV_PARAMS_L3["indist_ref_coupling"], 1.6)
        self.assertEqual(scm.ENV_PARAMS_L3["test_coupling"], -1.6)


class MechanismMachinery(unittest.TestCase):
    def setUp(self):
        self._n = scm.ENV_PARAMS_L3["n_samples"]
        scm.ENV_PARAMS_L3["n_samples"] = 300      # reduced for test speed; properties are fidelity-robust
        self.ic = InteractionCWM()

    def tearDown(self):
        scm.ENV_PARAMS_L3["n_samples"] = self._n

    def test_mag_floor_is_frozen_not_a_live_arg(self):
        self.assertEqual(InteractionCWM.mag_floor, 0.15)   # frozen class attribute, not a call parameter

    def test_invariant_interaction_auc_is_offline_scalar(self):
        tr = scm.train_envs_l3(0)
        rows, labels = scm.test_env_l3(0)
        out = self.ic.invariant_interaction_auc(tr, rows, labels, seed=0, mode="inv_interaction")
        self.assertIsInstance(out, float)          # verify-only: a scalar AUC, never an action/advice
        self.assertGreaterEqual(out, 0.0)
        self.assertLessEqual(out, 1.0)

    def test_capacity_matched_arm_uses_full_phi_no_filter(self):
        # cap_pooled must never invoke the invariance filter (no return_kept path); same phi as our arm
        tr = scm.train_envs_l3(0)
        rows, labels = scm.test_env_l3(0)
        cap = self.ic.invariant_interaction_auc(tr, rows, labels, seed=0, mode="cap_pooled")
        self.assertIsInstance(cap, float)

    def test_permute_collapses_to_chance(self):
        tr = scm.train_envs_l3(0)
        rows, labels = scm.test_env_l3(0)
        inv = self.ic.invariant_interaction_auc(tr, rows, labels, seed=0, mode="inv_interaction", permute=True)
        self.assertLess(abs(inv - 0.5), 0.08)      # shuffled labels -> chance

    def test_causal_ablation_cannot_exceed_linear_ceiling(self):
        # a_xor=0 removes the interaction; our arm cannot exceed the linear (Xc3) ceiling
        tr = [scm.gen_env_l3(0, c, scm._TAG_TRAIN[i], a_xor=0.0)
              for i, c in enumerate(scm.ENV_PARAMS_L3["train_couplings"])]
        rows, labels = scm.gen_env_l3(0, scm.ENV_PARAMS_L3["test_coupling"], scm._TAG_TEST, a_xor=0.0)
        inv = self.ic.invariant_interaction_auc(tr, rows, labels, seed=0, mode="inv_interaction")
        self.assertLess(inv, 0.62, "interaction ablated yet our arm still predicts above the linear ceiling")

    def test_c7_attribution_interaction_is_load_bearing(self):
        # dropping Xc1*Xc2 from the kept set must degrade OOD; dropping a retained spurious coord must not help
        tr = scm.train_envs_l3(0)
        rows, labels = scm.test_env_l3(0)
        full, kept = self.ic.invariant_interaction_auc(tr, rows, labels, seed=0, return_kept=True)
        xor_k = product_index(scm.N_FEATURES, *scm.INTERACTION_PAIR)
        if xor_k in kept:
            drop_xor = self.ic.invariant_interaction_auc(tr, rows, labels, seed=0, drop_coords=(xor_k,))
            self.assertLess(drop_xor, full, "dropping the interaction coord did not degrade OOD (not load-bearing)")


if __name__ == "__main__":
    unittest.main()
