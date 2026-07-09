"""Tests for CWM Organ interface and GovernedDiscoveryLoop.

Tests-first per Hard Boundary #17.

Coverage:
- LinearGGMOrgan: skeleton proposal, mechanism fitting, do() prediction
- PolynomialOrgan: basis expansion, nonlinear fitting, skeleton proposal
- GovernedDiscoveryLoop: discovery pipeline, proposal collection, intervention selection
- CWMOrgan protocol: duck typing, structure proposal shape, verify result shape
"""
from __future__ import annotations

import math
import random
import unittest

from aac.cwm_organ import (
    CWMOrgan,
    StructureProposal,
    VerifyResult,
    LinearGGMOrgan,
    PolynomialOrgan,
    _standardize_cols,
    _cov,
    _inv,
    _ols_fit,
    _spearman_rank,
    _topological_order,
)
from aac.governed_discovery_loop import (
    GovernedDiscoveryLoop,
    DiscoveryResult,
)
from aac.bayesian_dag_posterior import generate_linear_scm_data, is_dag


class TestCWMOrganProtocol(unittest.TestCase):
    def test_structure_proposal_fields(self):
        p = StructureProposal(edges=frozenset({(0, 1)}), score=0.8, is_directed=True, provenance="test")
        self.assertEqual(p.provenance, "test")

    def test_verify_result_fields(self):
        v = VerifyResult(True, 0.9, 3)
        self.assertTrue(v.is_consistent)
        self.assertEqual(v.interventions_used, 3)

    def test_base_organ_raises_not_implemented(self):
        organ = CWMOrgan()
        with self.assertRaises(NotImplementedError):
            organ.propose_skeleton([])
        with self.assertRaises(NotImplementedError):
            organ.propose_orientation(frozenset())
        with self.assertRaises(NotImplementedError):
            organ.verify_structure(frozenset(), [])

    def test_base_organ_confidence_zero(self):
        self.assertEqual(CWMOrgan().confidence(), 0.0)


class TestLinearGGMOrgan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rng = random.Random(42)
        cls.true_edges = frozenset({(0, 1), (1, 2), (2, 3)})
        cls.obs, _ = generate_linear_scm_data(5, cls.true_edges, 500, noise_std=0.3, rng=cls.rng)

    def test_propose_skeleton_returns_list(self):
        organ = LinearGGMOrgan(tau=0.05)
        proposals = organ.propose_skeleton(self.obs)
        self.assertIsInstance(proposals, list)
        self.assertGreater(len(proposals), 0)

    def test_skeleton_is_undirected(self):
        organ = LinearGGMOrgan(tau=0.05)
        proposals = organ.propose_skeleton(self.obs)
        for p in proposals:
            self.assertFalse(p.is_directed)

    def test_mechanism_fit_returns_callable(self):
        organ = LinearGGMOrgan()
        dag = frozenset({(0, 1), (1, 2)})
        pred = organ.mechanism_fit(dag, self.obs)
        self.assertTrue(callable(pred))

    def test_do_prediction_returns_do_value_for_target(self):
        organ = LinearGGMOrgan()
        dag = frozenset({(0, 1)})
        pred = organ.mechanism_fit(dag, self.obs)
        baseline = [0.0] * 5
        result = pred(0, 3.0, 0, baseline)
        self.assertEqual(result, 3.0)

    def test_do_prediction_on_child_uses_parent_value(self):
        organ = LinearGGMOrgan()
        dag = frozenset({(0, 1)})
        pred = organ.mechanism_fit(dag, self.obs)
        baseline = [0.0] * 5
        result = pred(0, 3.0, 1, baseline)
        self.assertIsInstance(result, float)


class TestPolynomialOrgan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rng = random.Random(55)
        cls.n = 5

    def test_basis_expansion_shape(self):
        organ = PolynomialOrgan(max_degree=2)
        X = [[0.5, 1.0], [-0.5, 2.0], [0.0, 0.0]]
        basis = organ._expand_basis(X, 2)
        self.assertEqual(len(basis), 3)
        self.assertEqual(basis[0][0], 1.0)
        self.assertGreater(len(basis[0]), 3)

    def test_propose_skeleton(self):
        rng = random.Random(42)
        edges = frozenset({(0, 1), (1, 2)})
        obs, _ = generate_linear_scm_data(self.n, edges, 300, noise_std=0.4, rng=rng)
        organ = PolynomialOrgan(max_degree=2, tau=0.05)
        proposals = organ.propose_skeleton(obs)
        self.assertGreater(len(proposals), 0)
        self.assertEqual(proposals[0].provenance, "Polynomial")

    def test_nonlinear_mechanism_fit_on_sinusoidal(self):
        rng = random.Random(99)
        n_obs = 200
        obs = []
        for _ in range(n_obs):
            x0 = rng.gauss(0, 1)
            x1 = math.sin(x0 * 2.0) + rng.gauss(0, 0.2)
            x2 = rng.gauss(0, 1)
            x3 = rng.gauss(0, 1)
            x4 = rng.gauss(0, 1)
            obs.append([x0, x1, x2, x3, x4])
        organ = PolynomialOrgan(max_degree=2)
        dag = frozenset({(0, 1)})
        pred = organ.mechanism_fit(dag, obs)
        baseline = [0.0] * 5
        result = pred(0, 1.0, 1, baseline)
        self.assertIsInstance(result, float)
        self.assertNotEqual(result, 0.0)


class TestSpearmanRank(unittest.TestCase):
    def test_monotone_invariant(self):
        vals = [[1.0, 10.0], [2.0, 20.0], [3.0, 30.0]]
        ranked = _spearman_rank(vals)
        self.assertEqual(ranked, [[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]])

    def test_ties_averaged(self):
        vals = [[5.0], [5.0], [5.0], [1.0]]
        ranked = _spearman_rank(vals)
        self.assertEqual([r[0] for r in ranked], [3.0, 3.0, 3.0, 1.0])


class TestTopologicalOrder(unittest.TestCase):
    def test_linear_chain(self):
        dag = frozenset({(0, 1), (1, 2), (2, 3)})
        order = _topological_order(dag, 4)
        self.assertEqual(len(order), 4)
        self.assertLess(order.index(0), order.index(1))
        self.assertLess(order.index(1), order.index(2))


class TestGovernedDiscoveryLoop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rng = random.Random(42)
        cls.n = 5
        cls.true_edges = frozenset({(0, 1), (1, 2), (2, 3)})
        cls.obs, _ = generate_linear_scm_data(cls.n, cls.true_edges, 400, noise_std=0.3, rng=cls.rng)

    def test_init_creates_loop(self):
        loop = GovernedDiscoveryLoop(
            organs=[LinearGGMOrgan(tau=0.05)],
            intervenable_nodes={0, 1, 2, 3, 4},
            budget=10,
        )
        self.assertEqual(len(loop.organs), 1)

    def test_discover_returns_result(self):
        loop = GovernedDiscoveryLoop(
            organs=[LinearGGMOrgan(tau=0.05)],
            intervenable_nodes={0, 1, 2, 3, 4},
            budget=3,
            n_particles=30,
            confidence_threshold=0.99,
        )
        result = loop.discover(self.obs)
        self.assertIsInstance(result, DiscoveryResult)
        self.assertIn(result.status, ["VERIFIED", "UNVERIFIED", "BUDGET_EXHAUSTED"])
        self.assertIsInstance(result.organs_used, list)

    def test_discover_respects_budget(self):
        loop = GovernedDiscoveryLoop(
            organs=[LinearGGMOrgan(tau=0.05)],
            intervenable_nodes={0, 1, 2, 3, 4},
            budget=3,
            n_particles=30,
            confidence_threshold=0.99,
        )
        result = loop.discover(self.obs)
        self.assertLessEqual(result.interventions_spent, loop.budget)

    def test_discover_with_polynomial_organ(self):
        loop = GovernedDiscoveryLoop(
            organs=[PolynomialOrgan(max_degree=1, tau=0.05)],
            intervenable_nodes={0, 1, 2, 3, 4},
            budget=3,
            n_particles=30,
            confidence_threshold=0.99,
        )
        result = loop.discover(self.obs)
        self.assertIsInstance(result, DiscoveryResult)

    def test_discover_with_multiple_organs(self):
        loop = GovernedDiscoveryLoop(
            organs=[LinearGGMOrgan(tau=0.05), PolynomialOrgan(max_degree=1, tau=0.05)],
            intervenable_nodes={0, 1, 2, 3, 4},
            budget=3,
            n_particles=30,
            confidence_threshold=0.99,
        )
        result = loop.discover(self.obs)
        self.assertGreaterEqual(len(result.organs_used), 2)

    def test_best_dag_is_valid(self):
        loop = GovernedDiscoveryLoop(
            organs=[LinearGGMOrgan(tau=0.05)],
            intervenable_nodes={0, 1, 2, 3, 4},
            budget=3,
            n_particles=30,
            confidence_threshold=0.99,
        )
        result = loop.discover(self.obs)
        if result.best_dag is not None:
            self.assertTrue(is_dag(result.best_dag, self.n))

    def test_edge_marginals_produced(self):
        loop = GovernedDiscoveryLoop(
            organs=[LinearGGMOrgan(tau=0.05)],
            intervenable_nodes={0, 1, 2, 3, 4},
            budget=3,
            n_particles=30,
            confidence_threshold=0.99,
        )
        result = loop.discover(self.obs)
        self.assertIsNotNone(result.edge_marginals)
        self.assertGreater(len(result.edge_marginals), 0)


class TestEndToEndDiscovery(unittest.TestCase):
    def test_generated_data_self_discovery(self):
        rng = random.Random(123)
        true_edges = frozenset({(0, 1), (1, 2), (0, 3)})
        obs, _ = generate_linear_scm_data(5, true_edges, 200, noise_std=0.3, rng=rng)
        loop = GovernedDiscoveryLoop(
            organs=[LinearGGMOrgan(tau=0.05)],
            intervenable_nodes={0, 1, 2, 3, 4},
            budget=3,
            n_particles=30,
            confidence_threshold=0.5,
            lambda_sparse=0.5,
        )
        result = loop.discover(obs)
        self.assertIsInstance(result.best_dag, frozenset)
        self.assertGreater(result.confidence, 0.0)
        self.assertLessEqual(result.interventions_spent, 3)


if __name__ == "__main__":
    unittest.main()
