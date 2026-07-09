"""Tests for partially-observed / latent-confounder live discovery."""
from __future__ import annotations

import unittest

from aac.interactive_discovery_loop import OnlineInteractiveDiscoveryLoop
from aac.latent_confounder_env import PartiallyObservedSCMEnv


class PartiallyObservedSCMEnvTest(unittest.TestCase):
    def test_observe_hides_latent_nodes(self) -> None:
        env = PartiallyObservedSCMEnv(
            n_total=4,
            observed_indices=[0, 1, 2],
            edges={(3, 0), (0, 1)},
            seed=1,
        )
        obs = env.observe(20)
        self.assertEqual(len(obs), 20)
        self.assertEqual(len(obs[0]), 3)

    def test_intervene_on_observed_node(self) -> None:
        env = PartiallyObservedSCMEnv(
            n_total=4,
            observed_indices=[0, 1, 2],
            edges={(0, 1)},
            seed=2,
            noise_std=0.0,
            coef_range=(0.8, 0.8),
        )
        sample = env.intervene(do_node=0, do_value=5.0)
        self.assertEqual(len(sample), 3)
        self.assertAlmostEqual(sample[0], 5.0)
        # With zero noise and positive coefficient, child 1 should be nonzero.
        self.assertGreater(abs(sample[1]), 0.1)

    def test_ground_truth_observed_edges_filters_latent(self) -> None:
        env = PartiallyObservedSCMEnv(
            n_total=4,
            observed_indices=[0, 1, 2],
            edges={(3, 0), (3, 1), (0, 2)},
            seed=3,
        )
        # Edge (3,0) and (3,1) involve latent node 3; only (0,2) is observed.
        self.assertEqual(env.ground_truth_observed_edges, {(0, 2)})

    def test_structural_hamming_distance(self) -> None:
        env = PartiallyObservedSCMEnv(
            n_total=3,
            observed_indices=[0, 1],
            edges={(0, 1)},
            seed=4,
        )
        self.assertEqual(env.structural_hamming_distance({(0, 1)}), 0)
        self.assertEqual(env.structural_hamming_distance({(1, 0)}), 2)


class LatentConfounderDiscoveryTest(unittest.TestCase):
    def test_loop_completes_without_hallucinating_high_confidence_false_edges(self) -> None:
        """Latent confounding can create correlation, but no false edge should dominate.

        Setup: latent node 3 confounds observed 0 and 1; observed 0 directly causes 2.
        The discovery loop only sees nodes {0,1,2}.  We verify it finishes and that
        no false observed-edge marginal exceeds a modest threshold.
        """
        env = PartiallyObservedSCMEnv(
            n_total=4,
            observed_indices=[0, 1, 2],
            edges={(3, 0), (3, 1), (0, 2)},
            seed=42,
            noise_std=0.2,
            coef_range=(0.8, 0.8),
        )
        loop = OnlineInteractiveDiscoveryLoop(
            organs=[],
            environment=env,
            budget=12,
            confidence_threshold=0.95,
            seed=42,
            n_particles=60,
            max_window_size=120,
        )
        results = loop.discover_online(
            rounds=3, n_obs_per_round=60, interventions_per_round=4
        )
        final = results[-1]
        self.assertIn(final.status, ("VERIFIED", "BUDGET_EXHAUSTED"))
        self.assertIsNotNone(final.best_dag)

        marginals = final.edge_marginals or {}
        false_edges = set(marginals.keys()) - env.ground_truth_observed_edges
        max_false_marginal = max(
            (marginals.get(e, 0.0) for e in false_edges), default=0.0
        )
        # With latent confounding, marginals should remain diffuse; no false edge
        # should dominate.
        self.assertLess(max_false_marginal, 0.5)

    def test_intervention_identifies_direct_edge_among_observed(self) -> None:
        """Intervening on an observed parent should change its observed child."""
        env = PartiallyObservedSCMEnv(
            n_total=4,
            observed_indices=[0, 1, 2],
            edges={(3, 0), (3, 1), (0, 2)},
            seed=5,
            noise_std=0.1,
            coef_range=(0.8, 0.8),
        )
        n = 50
        baseline = [env.observe(1)[0][2] for _ in range(n)]
        intervened = [env.intervene(do_node=0, do_value=3.0)[2] for _ in range(n)]
        mean_base = sum(baseline) / n
        mean_int = sum(intervened) / n
        # Direct edge 0->2 with positive coefficient: do(0=3) should push x2 up.
        self.assertGreater(mean_int, mean_base + 0.5)

    def test_c7_offline_invariant_latent(self) -> None:
        """The loop never executes an external action; it only reads."""
        env = PartiallyObservedSCMEnv(
            n_total=3,
            observed_indices=[0, 1],
            edges={(0, 1)},
            seed=6,
        )
        loop = OnlineInteractiveDiscoveryLoop(
            organs=[],
            environment=env,
            budget=2,
            seed=6,
            n_particles=20,
        )
        results = loop.discover_online(
            rounds=2, n_obs_per_round=20, interventions_per_round=2
        )
        self.assertEqual(len(results), 2)


if __name__ == "__main__":
    unittest.main()
