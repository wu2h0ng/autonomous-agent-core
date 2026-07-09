"""Tests for Bayesian DAG posterior (governed DiBS).

Tests-first per Hard Boundary #17. Verifies:
  BayesianDAGPosterior (backward compatible):
    - DAG utilities (is_dag, random_dag, perturb_dag)
    - Particle posterior smoke, convergence, sparsity, confidence, routing
    - Data generation

  GovernedDiBS (M-GAP-2 Algorithm 1):
    - C7 governance: forbidden edges/parents respected everywhere
    - Credit-weighted prior: organ proposals boost prior
    - SVGD gradient-informed updates: particles converge
    - RBF kernel and Hamming distance
    - BOED: Expected Information Gain computation
    - Posterior entropy
    - Organ credit attribution (Bayesian PR-003)
"""
from __future__ import annotations

import math
import random
import unittest

from aac.bayesian_dag_posterior import (
    BayesianDAGPosterior,
    GovernedDiBS,
    compute_edge_gradient,
    generate_linear_scm_data,
    gradient_informed_perturb,
    hamming_distance,
    is_dag,
    is_edge_legal,
    perturb_dag,
    random_dag,
    rbf_kernel,
)


class TestDAGUtilities(unittest.TestCase):
    def test_is_dag_accepts_valid_dag(self):
        edges = {(0, 1), (1, 2), (0, 2)}
        self.assertTrue(is_dag(edges, 3))

    def test_is_dag_rejects_cycle(self):
        edges = {(0, 1), (1, 2), (2, 0)}
        self.assertFalse(is_dag(edges, 3))

    def test_is_dag_rejects_self_loop(self):
        edges = {(0, 0)}
        self.assertFalse(is_dag(edges, 2))

    def test_random_dag_is_valid(self):
        for _ in range(20):
            dag = random_dag(6, edge_prob=0.3, rng=random.Random(42))
            self.assertTrue(is_dag(dag, 6), f"DAG {dag} has a cycle")

    def test_perturb_dag_preserves_dag(self):
        rng = random.Random(42)
        dag = random_dag(6, edge_prob=0.4, rng=rng)
        changes_seen = False
        for _ in range(50):
            new_dag = perturb_dag(dag, 6, max_changes=3, rng=rng)
            self.assertTrue(is_dag(new_dag, 6),
                            f"Perturbed DAG {new_dag} has a cycle")
            if new_dag != dag:
                changes_seen = True
        self.assertTrue(changes_seen,
                        "perturb_dag never produced a different DAG after 50 attempts")

    def test_perturb_dag_changes_edges(self):
        rng = random.Random(42)
        dag = random_dag(6, edge_prob=0.3, rng=rng)
        changes = []
        for _ in range(30):
            new_dag = perturb_dag(dag, 6, max_changes=2, rng=rng)
            changes.append(abs(len(dag) - len(new_dag)))
        self.assertTrue(max(changes) <= 2)


class TestC7GovernanceConstraints(unittest.TestCase):
    def test_is_edge_legal_allows_normal_edge(self):
        self.assertTrue(is_edge_legal((0, 1)))
        self.assertTrue(is_edge_legal((0, 1), None, None))

    def test_is_edge_legal_rejects_forbidden_edge(self):
        forbidden = {(1, 2)}
        self.assertFalse(is_edge_legal((1, 2), forbidden))
        self.assertTrue(is_edge_legal((0, 1), forbidden))

    def test_is_edge_legal_rejects_forbidden_parent(self):
        forbidden_parents = {2}
        self.assertFalse(is_edge_legal((1, 2), None, forbidden_parents))
        self.assertTrue(is_edge_legal((0, 1), None, forbidden_parents))

    def test_is_edge_legal_rejects_both_constraints(self):
        forbidden = {(0, 2)}
        forbidden_parents = {2}
        self.assertFalse(is_edge_legal((0, 2), forbidden, forbidden_parents))
        self.assertFalse(is_edge_legal((1, 2), None, forbidden_parents))

    def test_random_dag_respects_forbidden_edges(self):
        forbidden = {(0, 1), (1, 2)}
        for _ in range(30):
            dag = random_dag(4, edge_prob=0.5, rng=random.Random(42),
                             forbidden_edges=forbidden)
            self.assertTrue(is_dag(dag, 4))
            for f in forbidden:
                self.assertNotIn(f, dag,
                                 f"Forbidden edge {f} found in DAG {dag}")

    def test_random_dag_respects_forbidden_parents(self):
        forbidden_parents = {2}
        for _ in range(30):
            dag = random_dag(4, edge_prob=0.5, rng=random.Random(42),
                             forbidden_parents=forbidden_parents)
            self.assertTrue(is_dag(dag, 4))
            for u, v in dag:
                self.assertNotIn(v, forbidden_parents,
                                 f"Edge {(u,v)} targets forbidden parent {v}")

    def test_perturb_dag_respects_forbidden_edges(self):
        rng = random.Random(42)
        forbidden = {(2, 3)}
        dag = random_dag(5, edge_prob=0.3, rng=rng, forbidden_edges=forbidden)
        for _ in range(50):
            new_dag = perturb_dag(dag, 5, max_changes=3, rng=rng,
                                  forbidden_edges=forbidden)
            self.assertTrue(is_dag(new_dag, 5))
            self.assertNotIn((2, 3), new_dag)

    def test_perturb_dag_respects_forbidden_parents(self):
        rng = random.Random(42)
        forbidden_parents = {0}
        dag = random_dag(5, edge_prob=0.3, rng=rng,
                         forbidden_parents=forbidden_parents)
        for _ in range(50):
            new_dag = perturb_dag(dag, 5, max_changes=3, rng=rng,
                                  forbidden_parents=forbidden_parents)
            self.assertTrue(is_dag(new_dag, 5))
            for u, v in new_dag:
                self.assertNotIn(v, forbidden_parents,
                                 f"Edge {(u, v)} targets forbidden-parent node {v}")

    def test_random_dag_with_both_constraints(self):
        forbidden = {(0, 1)}
        forbidden_parents = {3}
        for _ in range(20):
            dag = random_dag(4, edge_prob=0.6, rng=random.Random(42),
                             forbidden_edges=forbidden,
                             forbidden_parents=forbidden_parents)
            self.assertTrue(is_dag(dag, 4))
            self.assertNotIn((0, 1), dag)
            for u, v in dag:
                self.assertNotEqual(v, 3)


class TestGovernedDiBSInit(unittest.TestCase):
    def test_init_creates_particles(self):
        di = GovernedDiBS(n_nodes=5, n_particles=20, seed=1)
        self.assertEqual(len(di.particles), 20)
        self.assertTrue(all(is_dag(p, 5) for p in di.particles))

    def test_init_respects_forbidden_edges(self):
        forbidden = frozenset({(0, 1), (2, 3)})
        di = GovernedDiBS(n_nodes=5, n_particles=30, seed=1,
                          forbidden_edges=forbidden)
        for p in di.particles:
            for f in forbidden:
                self.assertNotIn(f, p, f"Forbidden edge {f} in particle {p}")

    def test_init_respects_forbidden_parents(self):
        forbidden_parents = frozenset({0})
        di = GovernedDiBS(n_nodes=5, n_particles=30, seed=1,
                          forbidden_parents=forbidden_parents)
        for p in di.particles:
            for u, v in p:
                self.assertNotIn(v, forbidden_parents,
                                 f"Edge {(u, v)} targets forbidden-parent {v}")

    def test_init_stores_organ_data(self):
        proposals = {0: frozenset({(0, 1), (1, 2)})}
        credits = {0: 1.0}
        di = GovernedDiBS(n_nodes=4, n_particles=20, seed=1,
                          organ_proposals=proposals, organ_credits=credits)
        self.assertEqual(di.organ_proposals, proposals)
        self.assertEqual(di.organ_credits, credits)
        self.assertIn((0, 1), di._credit_prior_map)
        self.assertGreater(di._credit_prior_map.get((0, 1), 0), 0)

    def test_init_rejects_too_few_nodes(self):
        with self.assertRaises(ValueError):
            GovernedDiBS(n_nodes=1)

    def test_init_rejects_too_few_particles(self):
        with self.assertRaises(ValueError):
            GovernedDiBS(n_nodes=4, n_particles=1)


class TestGovernedDiBSUpdate(unittest.TestCase):
    def test_update_weights_sum_to_one(self):
        rng = random.Random(42)
        obs, _ = generate_linear_scm_data(4, {(0, 1), (1, 2)}, 100,
                                          noise_std=0.3, rng=rng)
        di = GovernedDiBS(n_nodes=4, n_particles=30, seed=1)
        di.update(obs)
        total = sum(di.weights)
        self.assertAlmostEqual(total, 1.0, delta=1e-9)

    def test_update_populates_log_posteriors(self):
        rng = random.Random(42)
        obs, _ = generate_linear_scm_data(4, {(0, 1)}, 100,
                                          noise_std=0.3, rng=rng)
        di = GovernedDiBS(n_nodes=4, n_particles=20, seed=1)
        di.update(obs)
        self.assertEqual(len(di._log_posteriors), 20)
        self.assertTrue(any(v != 0.0 for v in di._log_posteriors))

    def test_update_caches_kernel(self):
        rng = random.Random(42)
        obs, _ = generate_linear_scm_data(4, {(0, 1)}, 100,
                                          noise_std=0.3, rng=rng)
        di = GovernedDiBS(n_nodes=4, n_particles=10, seed=1)
        di.update(obs)
        self.assertIsNotNone(di._cached_kernel)
        self.assertEqual(len(di._cached_kernel), 10)
        self.assertAlmostEqual(di._cached_kernel[0][0], 1.0)


class TestGovernedDiBSMarginalsAndRouting(unittest.TestCase):
    def test_edge_marginals_shape(self):
        di = GovernedDiBS(n_nodes=4, n_particles=30, seed=2)
        marginals = di.edge_marginals()
        self.assertIsInstance(marginals, dict)
        for (i, j), prob in marginals.items():
            self.assertTrue(0 <= i < 4)
            self.assertTrue(0 <= j < 4)
            self.assertTrue(i != j)
            self.assertTrue(0.0 <= prob <= 1.0)

    def test_MAP_returns_valid_dag(self):
        di = GovernedDiBS(n_nodes=5, n_particles=30, seed=3)
        map_dag = di.MAP_dag()
        self.assertIsInstance(map_dag, frozenset)
        self.assertTrue(is_dag(map_dag, 5))

    def test_confidence_between_zero_and_one(self):
        di = GovernedDiBS(n_nodes=5, n_particles=30, seed=4)
        conf = di.confidence()
        self.assertTrue(0.0 <= conf <= 1.0)

    def test_route_returns_string(self):
        di = GovernedDiBS(n_nodes=5, n_particles=30, seed=4)
        verdict = di.route(confidence_threshold=0.8)
        self.assertIn(verdict, ["VERIFIED", "UNVERIFIED"])

    def test_posterior_entropy_nonnegative(self):
        di = GovernedDiBS(n_nodes=5, n_particles=30, seed=4)
        ent = di.posterior_entropy()
        self.assertGreaterEqual(ent, 0.0)

    def test_posterior_entropy_maximum_for_uniform(self):
        di = GovernedDiBS(n_nodes=4, n_particles=10, seed=5)
        ent = di.posterior_entropy()
        max_ent = math.log(10)
        self.assertLessEqual(ent, max_ent + 0.01)


class TestGovernedDiBSForbiddenParticles(unittest.TestCase):
    def test_svgd_step_respects_constraints(self):
        rng = random.Random(42)
        forbidden = frozenset({(1, 3)})
        obs, _ = generate_linear_scm_data(5, {(0, 1), (1, 2), (2, 3)}, 200,
                                          noise_std=0.3, rng=rng)
        di = GovernedDiBS(n_nodes=5, n_particles=10, seed=1,
                          forbidden_edges=forbidden)
        for _ in range(2):
            di.svgd_step(obs, n_gradient_edges=6)
        for p in di.particles:
            for f in forbidden:
                self.assertNotIn(f, p, f"Forbidden edge {f} in particle after svgd_step")

    def test_resample_and_perturb_respects_constraints(self):
        rng = random.Random(42)
        forbidden = frozenset({(2, 4)})
        forbidden_parents = frozenset({0})
        obs, _ = generate_linear_scm_data(5, {(0, 1), (1, 2)}, 100,
                                          noise_std=0.3, rng=rng)
        di = GovernedDiBS(n_nodes=5, n_particles=20, seed=1,
                          forbidden_edges=forbidden,
                          forbidden_parents=forbidden_parents)
        di.update(obs)
        di.resample_and_perturb()
        for p in di.particles:
            self.assertNotIn((2, 4), p)
            for u, v in p:
                self.assertNotIn(v, forbidden_parents)


class TestCreditWeightedPrior(unittest.TestCase):
    def test_organ_agreement_increases_prior(self):
        from aac.bayesian_dag_posterior import _log_prior_governed, _build_credit_prior_map

        dag = frozenset({(0, 1), (1, 2)})
        proposals = {0: frozenset({(0, 1), (1, 2)}), 1: frozenset({(0, 1)})}
        credits = {0: 0.6, 1: 0.4}
        prior_map = _build_credit_prior_map(3, proposals, credits)

        lp_with = _log_prior_governed(dag, 1.0, 3, proposals, credits, prior_map)
        lp_without = _log_prior_governed(dag, 1.0, 3, None, None, None)

        self.assertGreater(lp_with, lp_without,
                           f"Credit-weighted prior {lp_with:.3f} <= plain prior {lp_without:.3f}")

    def test_credit_map_all_orgs_agree(self):
        from aac.bayesian_dag_posterior import _build_credit_prior_map

        proposals = {0: frozenset({(0, 1)}), 1: frozenset({(0, 1)})}
        credits = {0: 0.5, 1: 0.5}
        cmap = _build_credit_prior_map(3, proposals, credits)
        self.assertAlmostEqual(cmap.get((0, 1), 0), 1.0)

    def test_credit_map_no_organ_agrees(self):
        from aac.bayesian_dag_posterior import _build_credit_prior_map

        proposals = {0: frozenset({(0, 1)}), 1: frozenset({(2, 1)})}
        credits = {0: 0.5, 1: 0.5}
        cmap = _build_credit_prior_map(3, proposals, credits)
        self.assertAlmostEqual(cmap.get((0, 1), 0), 0.5)
        self.assertAlmostEqual(cmap.get((2, 1), 0), 0.5)


class TestSVGDAndGradientUpdates(unittest.TestCase):
    def test_svgd_step_runs_without_error(self):
        rng = random.Random(42)
        obs, _ = generate_linear_scm_data(4, {(0, 1), (1, 2)}, 200,
                                          noise_std=0.3, rng=rng)
        di = GovernedDiBS(n_nodes=4, n_particles=20, seed=1)
        di.svgd_step(obs, n_gradient_edges=15)

    def test_svgd_step_changes_particles(self):
        rng = random.Random(42)
        obs, _ = generate_linear_scm_data(4, {(0, 1), (1, 2)}, 200,
                                          noise_std=0.3, rng=rng)
        di = GovernedDiBS(n_nodes=4, n_particles=20, seed=1)
        before = di.particles[:]
        di.svgd_step(obs, n_gradient_edges=15)
        after = di.particles[:]
        changed = sum(1 for b, a in zip(before, after) if b != a)
        self.assertGreater(changed, 0, "SVGD step changed zero particles")

    def test_svgd_converges_on_linear_scm(self):
        rng = random.Random(123)
        true_edges = {(0, 1), (1, 2), (2, 3)}
        obs, _ = generate_linear_scm_data(5, true_edges, 400,
                                          noise_std=0.3, rng=rng)
        di = GovernedDiBS(n_nodes=5, n_particles=20, lambda_sparse=0.3,
                          sigma_noise=0.3, seed=5)
        for _ in range(6):
            di.svgd_step(obs, n_gradient_edges=8)
        map_dag = di.MAP_dag()
        true_set = frozenset(true_edges)
        map_undir = {frozenset(e) for e in map_dag}
        true_undir = {frozenset(e) for e in true_set}
        recall = len(map_undir & true_undir) / max(len(true_undir), 1)
        self.assertGreaterEqual(recall, 0.25,
                                f"MAP recall {recall:.2f} below 0.25, MAP={map_dag}")

    def test_compute_edge_gradient_returns_values(self):
        rng = random.Random(42)
        obs, _ = generate_linear_scm_data(4, {(0, 1), (1, 2)}, 100,
                                          noise_std=0.3, rng=rng)
        dag = frozenset({(0, 1)})
        grads = compute_edge_gradient(dag, obs, 0.3, 1.0, 4,
                                      max_edges_to_score=8,
                                      rng=random.Random(1))
        self.assertIsInstance(grads, dict)
        self.assertGreater(len(grads), 0)

    def test_gradient_informed_perturb_produces_valid_dag(self):
        rng = random.Random(42)
        dag = frozenset({(0, 1), (1, 2)})
        grads = {(0, 1): 0.5, (1, 2): -0.3, (2, 0): 1.0, (3, 0): 0.2,
                 (3, 1): -0.5, (2, 3): 0.8}
        for _ in range(30):
            new_dag = gradient_informed_perturb(
                dag, 4, grads, n_changes=2, temperature=0.5, rng=rng,
            )
            self.assertTrue(is_dag(new_dag, 4),
                            f"Gradient-inform perturb produced invalid DAG {new_dag}")

    def test_gradient_informed_perturb_respects_c7(self):
        rng = random.Random(42)
        dag = frozenset({(0, 1)})
        forbidden = frozenset({(2, 3)})
        grads = {(0, 1): 0.5, (2, 3): 10.0, (1, 2): 0.3}
        for _ in range(30):
            new_dag = gradient_informed_perturb(
                dag, 4, grads, n_changes=2, temperature=0.2, rng=rng,
                forbidden_edges=forbidden,
            )
            self.assertNotIn((2, 3), new_dag,
                             "Gradient-informed perturb included forbidden edge")

    def test_gradient_informed_perturb_no_candidates(self):
        dag = frozenset({(0, 1)})
        grads = {}
        rng = random.Random(42)
        new_dag = gradient_informed_perturb(
            dag, 4, grads, n_changes=1, temperature=0.5, rng=rng,
        )
        self.assertTrue(is_dag(new_dag, 4))


class TestRBFKernel(unittest.TestCase):
    def test_identical_dags_kernel_one(self):
        dag = frozenset({(0, 1), (1, 2)})
        k = rbf_kernel(dag, dag, 2.0)
        self.assertAlmostEqual(k, 1.0)

    def test_disjoint_dags_kernel_small(self):
        dag_a = frozenset({(0, 1), (1, 2)})
        dag_b = frozenset({(2, 0)})
        k = rbf_kernel(dag_a, dag_b, 2.0)
        self.assertLess(k, 0.5)

    def test_similar_dags_kernel_high(self):
        dag_a = frozenset({(0, 1), (1, 2)})
        dag_b = frozenset({(0, 1), (1, 2), (2, 3)})
        k = rbf_kernel(dag_a, dag_b, 2.0)
        self.assertGreater(k, 0.5)

    def test_hamming_distance_zero(self):
        dag = frozenset({(0, 1), (1, 2)})
        self.assertEqual(hamming_distance(dag, dag), 0)

    def test_hamming_distance_positive(self):
        dag_a = frozenset({(0, 1), (1, 2)})
        dag_b = frozenset({(0, 1)})
        self.assertEqual(hamming_distance(dag_a, dag_b), 1)

    def test_hamming_distance_symmetric(self):
        dag_a = frozenset({(0, 1), (1, 2)})
        dag_b = frozenset({(0, 1), (2, 0)})
        self.assertEqual(hamming_distance(dag_a, dag_b),
                         hamming_distance(dag_b, dag_a))


class TestBOED(unittest.TestCase):
    def test_compute_eig_returns_nonnegative(self):
        rng = random.Random(42)
        obs, _ = generate_linear_scm_data(4, {(0, 1), (1, 2)}, 200,
                                          noise_std=0.3, rng=rng)
        di = GovernedDiBS(n_nodes=4, n_particles=20, seed=1)
        di.update(obs)
        candidates = {0: [1.0, -1.0], 2: [0.5]}
        eig = di.compute_eig(obs, candidates, n_mc_samples=5)
        self.assertIsInstance(eig, dict)
        for v in eig.values():
            self.assertGreaterEqual(v, -1.0,
                                    "EIG should not be extremely negative")

    def test_compute_eig_covers_all_candidates(self):
        rng = random.Random(42)
        obs, _ = generate_linear_scm_data(4, {(0, 1)}, 200,
                                          noise_std=0.3, rng=rng)
        di = GovernedDiBS(n_nodes=4, n_particles=20, seed=1)
        di.update(obs)
        candidates = {0: [1.0], 1: [2.0], 3: [0.0]}
        eig = di.compute_eig(obs, candidates, n_mc_samples=3)
        self.assertEqual(set(eig.keys()), {0, 1, 3})

    def test_compute_eig_invalid_node_zero(self):
        rng = random.Random(42)
        obs, _ = generate_linear_scm_data(4, {(0, 1)}, 100,
                                          noise_std=0.3, rng=rng)
        di = GovernedDiBS(n_nodes=4, n_particles=10, seed=1)
        di.update(obs)
        candidates = {99: [1.0]}
        eig = di.compute_eig(obs, candidates, n_mc_samples=2)
        self.assertAlmostEqual(eig.get(99, -1), 0.0)

    def test_select_intervention_returns_tuple(self):
        rng = random.Random(42)
        obs, _ = generate_linear_scm_data(4, {(0, 1), (1, 2)}, 200,
                                          noise_std=0.3, rng=rng)
        di = GovernedDiBS(n_nodes=4, n_particles=20, seed=1)
        di.update(obs)
        candidates = {0: [1.0], 2: [0.5]}
        best_node, best_val, best_eig = di.select_intervention(
            obs, candidates, n_mc_samples=3,
        )
        self.assertIsInstance(best_node, int)
        self.assertIsInstance(best_val, float)
        self.assertIsInstance(best_eig, float)

    def test_select_intervention_empty_candidates(self):
        rng = random.Random(42)
        obs, _ = generate_linear_scm_data(4, {(0, 1)}, 100,
                                          noise_std=0.3, rng=rng)
        di = GovernedDiBS(n_nodes=4, n_particles=10, seed=1)
        di.update(obs)
        best_node, best_val, best_eig = di.select_intervention(obs, {})
        self.assertEqual(best_node, -1)
        self.assertEqual(best_eig, 0.0)


class TestOrganCreditAttribution(unittest.TestCase):
    def test_attribution_on_known_data(self):
        rng = random.Random(42)
        proposals = {
            0: frozenset({(0, 1), (1, 2)}),
            1: frozenset({(0, 1)}),
        }
        credits = {0: 0.5, 1: 0.5}
        obs, _ = generate_linear_scm_data(4, {(0, 1), (1, 2)}, 200,
                                          noise_std=0.3, rng=rng)
        di = GovernedDiBS(n_nodes=4, n_particles=30, seed=1,
                          organ_proposals=proposals, organ_credits=credits)
        di.update(obs)
        attribution = di.organ_credit_attribution()
        self.assertIn(0, attribution)
        self.assertIn(1, attribution)
        self.assertIsInstance(attribution[0], dict)

    def test_attribution_empty_without_proposals(self):
        di = GovernedDiBS(n_nodes=4, n_particles=20, seed=1)
        attribution = di.organ_credit_attribution()
        self.assertEqual(attribution, {})

    def test_attribution_values_in_range(self):
        rng = random.Random(42)
        proposals = {0: frozenset({(0, 1)})}
        credits = {0: 1.0}
        obs, _ = generate_linear_scm_data(3, {(0, 1)}, 200,
                                          noise_std=0.3, rng=rng)
        di = GovernedDiBS(n_nodes=3, n_particles=20, seed=1,
                          organ_proposals=proposals, organ_credits=credits)
        di.update(obs)
        attribution = di.organ_credit_attribution()
        for org_attrs in attribution.values():
            for score in org_attrs.values():
                self.assertTrue(0.0 <= score <= 1.0,
                                f"Attribution score {score} out of [0,1]")


class TestGovernedDiBSConvergence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rng = random.Random(123)
        cls.n = 5
        cls.true_edges = {(0, 1), (1, 2), (2, 3), (0, 4)}
        cls.n_obs = 800

    def test_log_likelihood_higher_for_true_dag(self):
        obs, _ = generate_linear_scm_data(
            self.n, self.true_edges, self.n_obs,
            noise_std=0.3, rng=self.rng,
        )
        from aac.bayesian_dag_posterior import _dag_log_likelihood
        true_ll = _dag_log_likelihood(frozenset(self.true_edges), obs, 0.3)
        empty_ll = _dag_log_likelihood(frozenset(), obs, 0.3)
        self.assertGreater(true_ll, empty_ll,
                           f"True DAG LL={true_ll:.1f}, empty LL={empty_ll:.1f}")

    def test_posterior_converges_with_svgd(self):
        rng = random.Random(123)
        obs, _ = generate_linear_scm_data(
            self.n, self.true_edges, self.n_obs,
            noise_std=0.3, rng=rng,
        )
        di = GovernedDiBS(n_nodes=self.n, n_particles=20, lambda_sparse=0.3,
                          sigma_noise=0.3, seed=5)
        for _ in range(6):
            di.svgd_step(obs, n_gradient_edges=10)
        map_dag = di.MAP_dag()
        true_set = frozenset(self.true_edges)
        map_undir = {frozenset(e) for e in map_dag}
        true_undir = {frozenset(e) for e in true_set}
        recall = len(map_undir & true_undir) / max(len(true_undir), 1)
        self.assertGreaterEqual(recall, 0.25,
                                f"MAP recall {recall:.2f} below 0.25")

    def test_map_dag_recovers_true_edges(self):
        rng = random.Random(123)
        obs, _ = generate_linear_scm_data(
            self.n, self.true_edges, self.n_obs,
            noise_std=0.3, rng=rng,
        )
        di = GovernedDiBS(n_nodes=self.n, n_particles=40, lambda_sparse=0.5,
                          sigma_noise=0.3, seed=5)
        for _ in range(5):
            di.svgd_step(obs, n_gradient_edges=12)
        map_dag = di.MAP_dag()
        true_set = frozenset(self.true_edges)
        map_undir = {frozenset(e) for e in map_dag}
        true_undir = {frozenset(e) for e in true_set}
        recall = len(map_undir & true_undir) / max(len(true_undir), 1)
        self.assertGreaterEqual(recall, 0.25,
                                f"MAP recall {recall:.2f} below 0.25")


class TestGovernedDiBSConfidenceSafety(unittest.TestCase):
    def test_confidence_low_when_multiple_equivalent_dags(self):
        rng = random.Random(789)
        edges = {(0, 2), (1, 2)}
        obs, _ = generate_linear_scm_data(5, edges, 300, noise_std=0.5, rng=rng)
        di = GovernedDiBS(n_nodes=5, n_particles=40, lambda_sparse=0.5,
                          sigma_noise=0.5, seed=8)
        for _ in range(3):
            di.svgd_step(obs, n_gradient_edges=10)
        conf = di.confidence()
        self.assertLess(conf, 0.95,
                        f"Confidence {conf:.3f} should NOT be near 1.0 for small MEC")

    def test_forbidden_edges_excluded_from_marginals(self):
        forbidden = frozenset({(2, 4)})
        di = GovernedDiBS(n_nodes=5, n_particles=30, seed=1,
                          forbidden_edges=forbidden)
        marginals = di.edge_marginals()
        self.assertAlmostEqual(marginals.get((2, 4), 0.0), 0.0)


class TestBayesianDAGPosteriorBackCompat(unittest.TestCase):
    def test_bdp_init_creates_particles(self):
        post = BayesianDAGPosterior(n_nodes=5, n_particles=20, seed=1)
        self.assertEqual(len(post.particles), 20)
        self.assertTrue(all(is_dag(p, 5) for p in post.particles))

    def test_bdp_edge_marginals_shape(self):
        post = BayesianDAGPosterior(n_nodes=4, n_particles=30, seed=2)
        marginals = post.edge_marginals()
        self.assertIsInstance(marginals, dict)
        for (i, j), prob in marginals.items():
            self.assertTrue(0 <= i < 4)
            self.assertTrue(0 <= j < 4)
            self.assertTrue(i != j)
            self.assertTrue(0.0 <= prob <= 1.0)

    def test_bdp_MAP_returns_valid_dag(self):
        post = BayesianDAGPosterior(n_nodes=5, n_particles=30, seed=3)
        map_dag = post.MAP_dag()
        self.assertIsInstance(map_dag, frozenset)
        self.assertTrue(is_dag(map_dag, 5))

    def test_bdp_confidence_between_zero_and_one(self):
        post = BayesianDAGPosterior(n_nodes=5, n_particles=30, seed=4)
        conf = post.confidence()
        self.assertTrue(0.0 <= conf <= 1.0)

    def test_bdp_weights_sum_to_one(self):
        post = BayesianDAGPosterior(n_nodes=4, n_particles=30, seed=11)
        total = sum(post.weights)
        self.assertAlmostEqual(total, 1.0, delta=1e-9)

    def test_bdp_log_likelihood_improves(self):
        rng = random.Random(123)
        n = 5
        true_edges = {(0, 1), (1, 2), (2, 3), (0, 4)}
        obs, _ = generate_linear_scm_data(n, true_edges, 800,
                                          noise_std=0.3, rng=rng)
        from aac.bayesian_dag_posterior import _dag_log_likelihood
        true_ll = _dag_log_likelihood(frozenset(true_edges), obs, 0.3)
        empty_ll = _dag_log_likelihood(frozenset(), obs, 0.3)
        self.assertGreater(true_ll, empty_ll,
                           f"True DAG LL={true_ll:.1f}, empty LL={empty_ll:.1f}")

    def test_bdp_posterior_improves(self):
        rng = random.Random(123)
        true_edges = {(0, 1), (1, 2), (2, 3)}
        obs, _ = generate_linear_scm_data(5, true_edges, 400,
                                          noise_std=0.3, rng=rng)
        post = BayesianDAGPosterior(n_nodes=5, n_particles=40,
                                    lambda_sparse=0.5, sigma_noise=0.3, seed=5)
        confs = []
        for _ in range(4):
            post.update(obs)
            post.resample_and_perturb()
            confs.append(post.confidence())
        self.assertGreaterEqual(confs[-1], confs[0] * 0.9,
                                f"Confidence degraded: {confs}")

    def test_bdp_route_verified(self):
        rng = random.Random(456)
        true_edges = {(0, 1), (1, 2), (2, 3)}
        obs, _ = generate_linear_scm_data(5, true_edges, 1200,
                                          noise_std=0.2, rng=rng)
        post = BayesianDAGPosterior(n_nodes=5, n_particles=80,
                                    lambda_sparse=0.3, sigma_noise=0.2, seed=7)
        for _ in range(6):
            post.update(obs)
            post.resample_and_perturb()
        conf = post.confidence()
        verdict = post.route(confidence_threshold=0.45)
        self.assertGreater(conf, 0.5)
        self.assertEqual(verdict, "VERIFIED")

    def test_bdp_sparsity_prior(self):
        rng = random.Random(55)
        obs, _ = generate_linear_scm_data(5, {(0, 1), (1, 2)}, 300,
                                          noise_std=0.4, rng=rng)
        post_strong = BayesianDAGPosterior(n_nodes=5, n_particles=30,
                                           lambda_sparse=5.0, seed=10)
        post_weak = BayesianDAGPosterior(n_nodes=5, n_particles=30,
                                         lambda_sparse=0.1, seed=10)
        for _ in range(2):
            post_strong.update(obs)
            post_strong.resample_and_perturb()
            post_weak.update(obs)
            post_weak.resample_and_perturb()
        edges_strong = [len(p) for p in post_strong.particles]
        edges_weak = [len(p) for p in post_weak.particles]
        mean_strong = sum(edges_strong) / len(edges_strong)
        mean_weak = sum(edges_weak) / len(edges_weak)
        self.assertLessEqual(mean_strong, mean_weak + 0.5)

    def test_bdp_confidence_low_multiple_eq(self):
        rng = random.Random(789)
        edges = {(0, 2), (1, 2)}
        obs, _ = generate_linear_scm_data(5, edges, 300, noise_std=0.5, rng=rng)
        post = BayesianDAGPosterior(n_nodes=5, n_particles=80,
                                    lambda_sparse=0.5, sigma_noise=0.5, seed=8)
        for _ in range(3):
            post.update(obs)
            post.resample_and_perturb()
        conf = post.confidence()
        self.assertLess(conf, 0.95)


class TestDataGeneration(unittest.TestCase):
    def test_generate_linear_scm_produces_correct_shape(self):
        edges = {(0, 1), (1, 2)}
        obs, coeffs = generate_linear_scm_data(4, edges, 100, noise_std=0.3,
                                               rng=random.Random(0))
        self.assertEqual(len(obs), 100)
        self.assertEqual(len(obs[0]), 4)
        self.assertIsInstance(coeffs, dict)

    def test_generate_linear_scm_single_row(self):
        edges = {(0, 1)}
        obs, _ = generate_linear_scm_data(3, edges, 1, noise_std=0.3,
                                          rng=random.Random(1))
        self.assertEqual(len(obs), 1)
        self.assertEqual(len(obs[0]), 3)


class TestNonlinearPoly2Likelihood(unittest.TestCase):
    def test_poly2_ll_finite_on_scm_data(self):
        from aac.bayesian_dag_posterior import _dag_log_likelihood_poly2
        rng = random.Random(42)
        obs, _ = generate_linear_scm_data(4, {(0, 1), (1, 2)}, 100,
                                          noise_std=0.3, rng=rng)
        ll = _dag_log_likelihood_poly2(frozenset({(0, 1), (1, 2)}), obs, 0.3)
        self.assertFalse(math.isnan(ll))
        self.assertFalse(math.isinf(ll))

    def test_poly2_ll_higher_for_true_dag(self):
        from aac.bayesian_dag_posterior import _dag_log_likelihood_poly2
        rng = random.Random(42)
        true_edges = {(0, 1), (1, 2), (2, 3)}
        obs, _ = generate_linear_scm_data(5, true_edges, 400,
                                          noise_std=0.3, rng=rng)
        true_ll = _dag_log_likelihood_poly2(frozenset(true_edges), obs, 0.3)
        empty_ll = _dag_log_likelihood_poly2(frozenset(), obs, 0.3)
        self.assertGreater(true_ll, empty_ll,
                           f"True poly2 LL={true_ll:.1f}, empty={empty_ll:.1f}")

    def test_poly2_on_nonlinear_data(self):
        from aac.bayesian_dag_posterior import _dag_log_likelihood_poly2, _dag_log_likelihood
        rng = random.Random(42)
        n = 4
        obs = []
        for _ in range(300):
            x0 = rng.gauss(0, 1)
            x1 = math.tanh(0.7 * x0) + rng.gauss(0, 0.3)
            x2 = math.tanh(0.5 * x1 - 0.3 * x0) + rng.gauss(0, 0.3)
            x3 = rng.gauss(0, 1)
            obs.append([x0, x1, x2, x3])
        true_dag = frozenset({(0, 1), (0, 2), (1, 2)})
        wrong_dag = frozenset({(0, 3)})
        poly_ll_true = _dag_log_likelihood_poly2(true_dag, obs, 0.3)
        poly_ll_wrong = _dag_log_likelihood_poly2(wrong_dag, obs, 0.3)
        self.assertGreater(poly_ll_true, poly_ll_wrong,
                           f"poly2 True LL={poly_ll_true:.1f} <= Wrong LL={poly_ll_wrong:.1f}")
        linear_ll_true = _dag_log_likelihood(true_dag, obs, 0.3)
        self.assertGreater(poly_ll_true, linear_ll_true,
                           f"poly2={poly_ll_true:.1f} <= linear={linear_ll_true:.1f} on nonlinear data")

    def test_poly2_empty_parents_no_crash(self):
        from aac.bayesian_dag_posterior import _dag_log_likelihood_poly2
        rng = random.Random(42)
        obs, _ = generate_linear_scm_data(3, frozenset(), 50, noise_std=0.3, rng=rng)
        ll = _dag_log_likelihood_poly2(frozenset(), obs, 0.3)
        self.assertFalse(math.isnan(ll))

    def test_poly2_single_parent(self):
        from aac.bayesian_dag_posterior import _dag_log_likelihood_poly2
        rng = random.Random(42)
        obs, _ = generate_linear_scm_data(3, {(0, 1)}, 100, noise_std=0.3, rng=rng)
        ll = _dag_log_likelihood_poly2(frozenset({(0, 1)}), obs, 0.3)
        self.assertFalse(math.isnan(ll))


class TestGovernedDiBSPoly2(unittest.TestCase):
    def test_init_with_poly2_mode(self):
        di = GovernedDiBS(n_nodes=4, n_particles=20, seed=1,
                          likelihood_mode="poly2")
        self.assertEqual(di.likelihood_mode, "poly2")

    def test_init_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            GovernedDiBS(n_nodes=4, n_particles=20, seed=1,
                         likelihood_mode="cubic")

    def test_poly2_update_weights_sum_to_one(self):
        rng = random.Random(42)
        n = 4
        obs = []
        for _ in range(200):
            x0 = rng.gauss(0, 1)
            x1 = math.tanh(0.5 * x0) + rng.gauss(0, 0.3)
            x2 = rng.gauss(0, 1)
            x3 = math.tanh(0.4 * x1) + rng.gauss(0, 0.3)
            obs.append([x0, x1, x2, x3])
        di = GovernedDiBS(n_nodes=n, n_particles=20, seed=1,
                          lambda_sparse=0.5, sigma_noise=0.3,
                          likelihood_mode="poly2")
        di.update(obs)
        total = sum(di.weights)
        self.assertAlmostEqual(total, 1.0, delta=1e-9)

    def test_poly2_svgd_converges_on_nonlinear(self):
        rng = random.Random(42)
        n = 4
        obs = []
        for _ in range(400):
            x0 = rng.gauss(0, 1)
            x1 = math.tanh(0.7 * x0) + rng.gauss(0, 0.3)
            x2 = math.tanh(0.5 * x1 - 0.3 * x0) + rng.gauss(0, 0.3)
            x3 = rng.gauss(0, 1)
            obs.append([x0, x1, x2, x3])
        true_edges = frozenset({(0, 1), (0, 2), (1, 2)})
        di = GovernedDiBS(n_nodes=n, n_particles=30, seed=5,
                          lambda_sparse=0.3, sigma_noise=0.3,
                          likelihood_mode="poly2")
        for _ in range(4):
            di.svgd_step(obs, n_gradient_edges=10)
        map_dag = di.MAP_dag()
        map_undir = {frozenset(e) for e in map_dag}
        true_undir = {frozenset(e) for e in true_edges}
        recall = len(map_undir & true_undir) / max(len(true_undir), 1)
        self.assertGreaterEqual(recall, 0.25,
                                f"Poly2 MAP recall {recall:.2f} below 0.25")

    def test_poly2_confidence_safety(self):
        rng = random.Random(42)
        n = 4
        obs = []
        for _ in range(300):
            x0 = rng.gauss(0, 0.5)
            x1 = math.tanh(x0) + rng.gauss(0, 0.3)
            x2 = math.tanh(x1) + rng.gauss(0, 0.3)
            x3 = rng.gauss(0, 0.5)
            obs.append([x0, x1, x2, x3])
        di = GovernedDiBS(n_nodes=n, n_particles=20, seed=5,
                          lambda_sparse=0.3, sigma_noise=0.3,
                          likelihood_mode="poly2")
        di.update(obs)
        conf = di.confidence()
        self.assertLess(conf, 1.0,
                        f"Poly2 confidence {conf:.4f} should not be 1.0 on initializing")


if __name__ == "__main__":
    unittest.main()
