"""CWM-LEARN-4 contract tests. Lock family-isolation, verify-only consumption, and the confound negative
control machinery — NOT the verdict (author != adjudicator; founder casts). The heavy 10-seed arm comparison
lives in experiments/cwm_learn_4.py; these are fast property/direction checks (some at reduced n)."""
from __future__ import annotations

import unittest

import experiments.synthetic_scm_transfer as scm
from aac.transfer_cwm import mlp_transfer_auc


class FamilyIsolation(unittest.TestCase):
    def test_train_and_novel_families_are_row_disjoint(self):
        for s in (0, 3, 7):
            tr = {tuple(r) for X, _ in scm.train_family(s) for r in X}
            a = {tuple(r) for r in scm.novelA_env(s)[0]}
            b = {tuple(r) for r in scm.novelB_env(s)[0]}
            self.assertEqual(len(tr & a), 0, "train/novelA row collision — families not isolated")
            self.assertEqual(len(tr & b), 0, "train/novelB row collision — families not isolated")
            self.assertEqual(len(a & b), 0, "novelA/novelB row collision")

    def test_novelA_nuisance_is_non_exploitable(self):
        # NOVEL-A slot-2 nuisance must carry ~0 linear class signal (nothing to leak / ride)
        import statistics
        rows, labels = scm.novelA_env(0)
        k = scm.SPURIOUS_IDX
        a = [rows[i][k] for i in range(len(rows)) if labels[i] == 1]
        b = [rows[i][k] for i in range(len(rows)) if labels[i] == 0]
        sd = statistics.pstdev([r[k] for r in rows]) or 1.0
        self.assertLess(abs(statistics.mean(a) - statistics.mean(b)) / sd, 0.15)

    def test_env_frozen_shape(self):
        self.assertEqual(scm.ENV_PARAMS_T["train_couplings"], [2.0, -1.5, 1.0])
        self.assertEqual(scm.ENV_PARAMS_T["n_features"], 5)
        self.assertEqual(scm.CAUSAL_IDX, [0, 1])


class MechanismMachinery(unittest.TestCase):
    def setUp(self):
        self._n = scm.ENV_PARAMS_T["n_samples"]
        scm.ENV_PARAMS_T["n_samples"] = 120   # reduced for test speed

    def tearDown(self):
        scm.ENV_PARAMS_T["n_samples"] = self._n

    def test_transfer_auc_is_offline_scalar(self):
        tr = scm.train_family(0)
        aX, aY = scm.novelA_env(0)
        out = mlp_transfer_auc(tr, aX, aY, lam=1e4, seed=0, epochs=60)
        self.assertIsInstance(out, float)
        self.assertGreaterEqual(out, 0.0)
        self.assertLessEqual(out, 1.0)

    def test_permute_collapses_to_chance(self):
        tr = scm.train_family(0)
        aX, aY = scm.novelA_env(0)
        out = mlp_transfer_auc(tr, aX, aY, lam=1e4, seed=0, epochs=60, permute=True)
        self.assertLess(abs(out - 0.5), 0.15)


if __name__ == "__main__":
    unittest.main()
