"""InvariantStructureFilter component tests (production form of CWM-LEARN-2/3).

Engineering Reality Gates coverage: real entry point (fit->InvariantModel->predict/score), typed failure
paths (<2 envs, fail-closed predict on not-found), test validity (a constant-return or selection-bypassing
implementation fails the structure-recovery and refusal tests), verify-only (inputs never mutated)."""
from __future__ import annotations

import copy
import random
import unittest

import experiments.synthetic_scm as scm_l2
import experiments.synthetic_scm_transfer as scm
from aac.invariant_structure import InvariantStructureFilter, NoInvariantStructure, SchemaMismatch


def _train_envs(seed=0):
    return scm.train_family(seed)


class RealBehaviour(unittest.TestCase):
    def test_recovers_named_interaction_and_transfers(self):
        # LEARN-3/4 validated capability: on the transfer SCM the kept structure must include the true
        # interaction x0*x1, exclude every spurious-slot coordinate, and transfer to the isolated family.
        m = InvariantStructureFilter(basis="cross2").fit(_train_envs(0), seed=0)
        self.assertTrue(m.found)
        self.assertIn("x0*x1", m.kept_names)
        self.assertFalse(any("x2" in n for n in m.kept_names),
                         f"spurious slot survived selection: {m.kept_names}")
        aX, aY = scm.novelA_env(0)
        self.assertGreater(m.score_auc(aX, aY), 0.80)   # cross-family transfer (supplied basis, LEARN-4 ref 0.89)

    def test_raw_basis_recovers_learn2_causal_set(self):
        # NON-VACUOUS raw-mode test (review D2 fix): on the LEARN-2 SCM, raw selection must FIRE — keep
        # exactly the causal features [x0,x1], drop the flipping spurious (x2/x3 slots) — and transfer to
        # the shifted test env. kept=[x0,x1] is a 2-coordinate model, so this also regression-guards the
        # predict-side standardization path that single-coordinate AUC cannot see (review blind spot).
        envs = scm_l2.train_envs(0)
        m = InvariantStructureFilter(basis="raw").fit(envs, seed=0)
        self.assertTrue(m.found, "raw selection failed to fire on the SCM where LEARN-2's mechanism fires")
        self.assertIn("x0", m.kept_names)
        self.assertIn("x1", m.kept_names)
        for spur in ("x2", "x3"):
            self.assertNotIn(spur, m.kept_names, f"flipping spurious {spur} survived raw selection")
        rows, labels = scm_l2.test_env(0)
        self.assertGreater(m.score_auc(rows, labels), 0.85)   # LEARN-2 gated reference: 0.896


class FailurePaths(unittest.TestCase):
    def test_single_env_rejected(self):
        with self.assertRaises(ValueError):
            InvariantStructureFilter().fit(_train_envs(0)[:1], seed=0)

    def test_schema_drift_fails_closed(self):
        # review D1 fix: a width-drifted row must raise a TYPED error, never return well-formed garbage
        # (a 6-wide row against a 5-wide cross2 fit silently relocates every product coordinate)
        m = InvariantStructureFilter(basis="cross2").fit(_train_envs(0), seed=0)
        good = _train_envs(0)[0][0][0]
        with self.assertRaises(SchemaMismatch):
            m.predict_proba(good + [0.0])          # wider
        with self.assertRaises(SchemaMismatch):
            m.predict_proba(good[:-1])             # narrower
        aX, aY = scm.novelA_env(0)
        with self.assertRaises(SchemaMismatch):
            m.score_auc([r + [0.0] for r in aX], aY)

    def test_ragged_training_rows_rejected(self):
        envs = _train_envs(0)
        X, Y = envs[0]
        bad = ([list(r) for r in X[:-1]] + [list(X[-1]) + [0.0]], Y)   # one row wider
        with self.assertRaises(ValueError):
            InvariantStructureFilter().fit([bad, envs[1]], seed=0)

    def test_unknown_basis_rejected(self):
        with self.assertRaises(ValueError):
            InvariantStructureFilter(basis="learned")   # discovery is out of validated scope by design

    def test_not_found_model_refuses_to_predict(self):
        # permuted labels -> no invariant structure -> the model must FAIL CLOSED, not return a constant
        envs = []
        for i, (X, Y) in enumerate(_train_envs(0)):
            Yp = list(Y)
            random.Random(i).shuffle(Yp)
            envs.append((X, Yp))
        m = InvariantStructureFilter().fit(envs, seed=0)
        self.assertFalse(m.found)
        with self.assertRaises(NoInvariantStructure):
            m.predict_proba(_train_envs(0)[0][0][0])
        with self.assertRaises(NoInvariantStructure):
            m.score_auc(*scm.novelA_env(0))


class VerifyOnly(unittest.TestCase):
    def test_inputs_never_mutated(self):
        envs = _train_envs(0)
        snapshot = copy.deepcopy(envs)
        InvariantStructureFilter().fit(envs, seed=0)
        self.assertEqual(envs, snapshot, "fit() mutated caller data — violates verify-only consumption")


if __name__ == "__main__":
    unittest.main()
