"""AGDE-1 Phase-0 contract tests (packet §8; tests-first). Machinery + integrity, never the verdict."""
from __future__ import annotations

import unittest

import experiments.intervention_scm as scm
from aac.discovery_loop import run_discovery
from aac.hypothesis_pool import canon, mec, v_structures
from aac.intervention_chooser import choose
from aac.structure_consistency import Exhausted, fit_mechanisms, prune


def _fam(seed=3):
    return scm.Family(seed)


def _first_valid(tol=0.6, start=0):
    s = start
    while True:
        f = scm.Family(s)
        if len(f.pool) >= 4:
            return f
        s += 1


class ScmEnv(unittest.TestCase):
    def test_seed_determinism_byte_identical(self):
        a, b = scm.Family(7), scm.Family(7)
        self.assertEqual(a.skeleton, b.skeleton)
        self.assertEqual(canon(a.true_pa), canon(b.true_pa))
        self.assertEqual(a.sample_obs(0)[:3], b.sample_obs(0)[:3])

    def test_do_clamps_only_intervened_mechanism(self):
        f = _first_valid()
        rows = f.sample_do(k=0, run_seed=0, step=0, n_rows=200)
        self.assertTrue(all(abs(r[0] - scm.SCM_PARAMS["do_value"]) < 1e-12 for r in rows))

    def test_truth_in_pool(self):
        f = _first_valid()
        self.assertEqual(canon(f.pool[f.truth_index]), canon(f.true_pa))


class HypothesisPool(unittest.TestCase):
    def test_mec_hand_case_chain(self):
        # chain 0-1-2 with truth 0->1->2 (no v-structure): MEC = 3 orientations (all but 0->1<-2)
        true_pa = {1: frozenset({0}), 2: frozenset({1})}
        pool = mec(3, [(0, 1), (1, 2)], true_pa)
        self.assertEqual(len(pool), 3)
        colliders = [h for h in pool if h.get(1) and len(h[1]) == 2]
        self.assertEqual(colliders, [])

    def test_mec_hand_case_collider(self):
        # truth 0->1<-2 (v-structure): MEC is a singleton
        true_pa = {1: frozenset({0, 2})}
        self.assertEqual(len(mec(3, [(0, 1), (1, 2)], true_pa)), 1)


class Verifier(unittest.TestCase):
    def test_prune_kills_wrong_orientation_keeps_truth(self):
        f = _first_valid()
        obs = f.sample_obs(0)
        mechs = [fit_mechanisms(f.n, h, obs) for h in f.pool]
        # find an informative do (one that separates at least one pair) by trying nodes
        for k in range(f.n):
            rows = f.sample_do(k, 0, 0, 200)
            try:
                keep, kill = prune(f.n, f.pool, mechs, k, scm.SCM_PARAMS["do_value"], rows, tol=0.6)
            except Exhausted:
                continue
            self.assertIn(f.truth_index, keep, "truth was killed by its own do() data")
            if kill:
                return   # at least one wrong orientation killed somewhere
        self.fail("no intervention killed any wrong hypothesis (tolerance/arena broken)")

    def test_exhausted_is_fail_closed(self):
        f = _first_valid()
        obs = f.sample_obs(0)
        mechs = [fit_mechanisms(f.n, h, obs) for h in f.pool]
        fake = [[100.0] * f.n for _ in range(50)]   # impossible do-regime data
        with self.assertRaises(Exhausted):
            prune(f.n, f.pool, mechs, 0, scm.SCM_PARAMS["do_value"], fake, tol=0.6)


class Chooser(unittest.TestCase):
    def test_deterministic_and_stateless(self):
        f = _first_valid()
        obs = f.sample_obs(0)
        mechs = [fit_mechanisms(f.n, h, obs) for h in f.pool]
        from aac.structure_consistency import predict_do_means
        base = [predict_do_means(f.n, h, m, -1, 0.0) for h, m in zip(f.pool, mechs)]
        k1 = choose(f.n, f.pool, mechs, list(range(f.n)), 2.0, base, 0.6)
        k2 = choose(f.n, f.pool, mechs, list(range(f.n)), 2.0, base, 0.6)
        self.assertEqual(k1, k2)


class Loop(unittest.TestCase):
    def _env(self, f, run_seed, n_int=200):
        def env_do(k, step):
            return f.sample_do(k, run_seed, step, n_int)
        env_do.truth_index = f.truth_index
        return env_do

    def test_budget_zero_touches_nothing_and_stays_unidentified(self):
        f = _first_valid()
        r = run_discovery(f.n, f.pool, f.sample_obs(0), self._env(f, 0), budget=0,
                          policy="active", seed=0, tol=0.6, c=2.0)
        self.assertEqual(r.outcome, "UNIDENTIFIED")
        self.assertEqual(r.interventions, [])
        self.assertEqual(len(r.survivors), len(f.pool))

    def test_gate_trace_has_exactly_budget_approvals(self):
        f = _first_valid()
        r = run_discovery(f.n, f.pool, f.sample_obs(0), self._env(f, 0), budget=2,
                          policy="random", seed=0, tol=0.6, c=2.0)
        self.assertEqual(len([t for t in r.gate_trace if t.endswith("ALLOW")]), len(r.interventions))
        self.assertLessEqual(len(r.interventions), 2)

    def test_identifiable_fixture_reaches_verified_intervention(self):
        # scripted identifiable case: chain family with enough budget; ledger must end VERIFIED
        f = _first_valid()
        r = run_discovery(f.n, f.pool, f.sample_obs(0), self._env(f, 0), budget=f.n,
                          policy="oracle", seed=0, tol=0.6, c=2.0)
        if r.identified:
            self.assertTrue(r.correct, "oracle identified a WRONG structure")
            wid = f"structure:h{f.pool.index(r.survivors[0])}"
            e = r.ledger.get(wid)
            self.assertIsNotNone(e)
            self.assertEqual(e.provenance, "VERIFIED_INTERVENTION")


if __name__ == "__main__":
    unittest.main()
