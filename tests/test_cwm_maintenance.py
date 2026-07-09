"""Tests for CWM self-maintenance: drift, decay, versioning, incremental update."""
from __future__ import annotations

import math, random, unittest

from aac.cwm_maintenance import CWMMaintenance, ModelSnapshot, EdgeRecord
from aac.bayesian_dag_posterior import generate_linear_scm_data


class TestCWMMaintenance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rng = random.Random(42)
        cls.edges = frozenset({(0, 1), (1, 2), (2, 3), (0, 4)})
        cls.obs, _ = generate_linear_scm_data(5, cls.edges, 400, 0.3, rng=cls.rng)

    def test_initialize_creates_dag_and_versions(self):
        cwm = CWMMaintenance(drift_threshold=10.0)
        cwm.initialize(self.obs)
        self.assertGreater(len(cwm.current_dag), 0)
        self.assertGreater(len(cwm.versions), 0)

    def test_update_no_drift_incremental(self):
        cwm = CWMMaintenance(drift_threshold=10.0)
        cwm.initialize(self.obs)
        info = cwm.update(self.obs[:50])
        self.assertFalse(info["drift_detected"])
        self.assertGreater(cwm.n_obs, len(self.obs))

    def test_update_with_drift_triggers_rediscovery(self):
        cwm = CWMMaintenance(drift_threshold=0.01)
        cwm.initialize(self.obs)
        info = cwm.update(self.obs[:50])
        self.assertTrue(info["drift_detected"])
        self.assertIn("rediscover", info["action"])

    def test_decay_reduces_confidence_over_rounds(self):
        cwm = CWMMaintenance(decay_rate=0.8, decay_rounds=1)
        cwm.initialize(self.obs)
        initial_conf = cwm._edge_confidence_mean()
        for _ in range(3):
            cwm._round += 1
            cwm._decay_edges()
        self.assertLess(cwm._edge_confidence_mean(), initial_conf)

    def test_snapshot_versioning(self):
        cwm = CWMMaintenance(max_versions=5)
        cwm.initialize(self.obs)
        for _ in range(3):
            cwm.update(self.obs[:10])
        self.assertGreater(len(cwm.versions), 1)
        self.assertLessEqual(len(cwm.versions), 5)

    def test_rollback_restores_previous_dag(self):
        cwm = CWMMaintenance()
        cwm.initialize(self.obs)
        v0_dag = cwm.current_dag
        cwm.update(self.obs[:20])
        v1_dag = cwm.current_dag
        snap = cwm.rollback(0)
        self.assertIsNotNone(snap)
        if v0_dag != v1_dag:
            self.assertEqual(cwm.current_dag, v0_dag)

    def test_compare_versions(self):
        cwm = CWMMaintenance()
        cwm.initialize(self.obs)
        cwm.update(self.obs[:20])
        diff = cwm.compare(0, 1)
        self.assertIn("edges_added", diff)
        self.assertIn("edges_removed", diff)

    def test_empty_obs_no_crash(self):
        cwm = CWMMaintenance()
        cwm.initialize(self.obs)
        info = cwm.update([])
        self.assertEqual(info["n_new"], 0)

    def test_edge_record_initialization(self):
        rec = EdgeRecord()
        self.assertEqual(rec.confirmation_count, 0)
        self.assertEqual(rec.current_confidence, 0.5)


class TestDriftDetection(unittest.TestCase):
    def test_same_data_no_drift(self):
        rng = random.Random(99)
        edges = frozenset({(0, 1), (1, 2)})
        obs, _ = generate_linear_scm_data(4, edges, 300, 0.3, rng=rng)
        cwm = CWMMaintenance(drift_threshold=10.0)
        cwm.initialize(obs)
        drift = cwm._check_drift(obs[:10])
        self.assertLess(drift, 1.0)

    def test_noisy_data_high_drift(self):
        rng = random.Random(99)
        edges = frozenset({(0, 1), (1, 2)})
        obs, _ = generate_linear_scm_data(4, edges, 300, 0.3, rng=rng)
        cwm = CWMMaintenance(drift_threshold=0.01)
        cwm.initialize(obs[:100])
        noisy = [[rng.gauss(10, 5) for _ in range(4)] for _ in range(10)]
        drift = cwm._check_drift(noisy)
        self.assertGreater(drift, 1.0)


if __name__ == "__main__":
    unittest.main()
