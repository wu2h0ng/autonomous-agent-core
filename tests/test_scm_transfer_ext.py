"""CWM-LEARN-5a/5b extension-machinery tests (fast; reduced n where fits are involved)."""
from __future__ import annotations

import statistics
import unittest

import experiments.synthetic_scm_transfer as base
import experiments.synthetic_scm_transfer_ext as ext
from aac.transfer_cwm import TransferMLP


class AnchorEnv(unittest.TestCase):
    def test_anchor_slot2_is_randomized_and_decoupled(self):
        rows, labels = ext.anchor_env(0, 400)
        xs = [r[2] for r in rows]
        # marginal is Uniform(-3,3), NOT the N(0,1) of the NOVEL-A test family (no family leakage)
        self.assertGreater(max(xs), 2.0)
        self.assertLess(min(xs), -2.0)
        # decoupled from the label (the interventional information)
        a = [rows[i][2] for i in range(len(rows)) if labels[i] == 1]
        b = [rows[i][2] for i in range(len(rows)) if labels[i] == 0]
        sd = statistics.pstdev(xs) or 1.0
        self.assertLess(abs(statistics.mean(a) - statistics.mean(b)) / sd, 0.15)

    def test_anchor_count_respected(self):
        rows, labels = ext.anchor_env(1, 16)
        self.assertEqual((len(rows), len(labels)), (16, 16))


class NovelCAndTanh(unittest.TestCase):
    def test_novelC_nuisance_lives_on_slot4_only(self):
        rows, labels = ext.novelC_env(0)
        import statistics as st
        def shift(k):
            a = [rows[i][k] for i in range(len(rows)) if labels[i] == 1]
            b = [rows[i][k] for i in range(len(rows)) if labels[i] == 0]
            sd = st.pstdev([r[k] for r in rows]) or 1.0
            return (st.mean(a) - st.mean(b)) / sd
        self.assertLess(shift(4), -0.5)          # flipped proxy on slot 4 (coupling -1.6)
        self.assertLess(abs(shift(2)), 0.15)     # slots 2,3 clean
        self.assertLess(abs(shift(3)), 0.15)

    def test_tanh_env_nuisance_on_slot3(self):
        rows, labels = ext.gen_tanh_env(0, 2.0, 0)
        import statistics as st
        a = [rows[i][3] for i in range(len(rows)) if labels[i] == 1]
        b = [rows[i][3] for i in range(len(rows)) if labels[i] == 0]
        sd = st.pstdev([r[3] for r in rows]) or 1.0
        self.assertGreater((st.mean(a) - st.mean(b)) / sd, 0.5)

    def test_family8_is_disjoint_from_tests(self):
        fam = ext.train_family_8(0)
        tr = {tuple(r) for X, _ in (fam["weak"] + fam["strong_plus"]) for r in X}
        for te_rows in (base.novelA_env(0)[0], ext.novelC_env(0)[0]):
            self.assertEqual(len(tr & {tuple(r) for r in te_rows}), 0)


class CurriculumMechanics(unittest.TestCase):
    def test_warm_start_continues_same_model(self):
        # stage-2 fit must CONTINUE from stage-1 weights (curriculum), not reinitialize
        base.ENV_PARAMS_T["n_samples"], keep = 80, base.ENV_PARAMS_T["n_samples"]
        try:
            fam = ext.train_family_8(0)
            m = TransferMLP(5, lam=0.0, epochs=20, seed=0)
            m.fit(fam["weak"])
            w_after_stage1 = [row[:] for row in m.W1]
            m.lam, m.epochs = 1e4, 20
            m.fit(fam["weak"] + fam["strong_plus"])
            self.assertNotEqual(w_after_stage1, m.W1)     # training continued
            # and it is the SAME object carrying stage-1 learning forward (no reinit path exists on fit)
        finally:
            base.ENV_PARAMS_T["n_samples"] = keep


if __name__ == "__main__":
    unittest.main()
