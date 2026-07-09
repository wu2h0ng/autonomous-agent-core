"""Tests for the unified live-environment harness."""
from __future__ import annotations

import unittest

from aac.live_env_harness import (
    ENV_SPECS,
    make_latent_env,
    make_linear_env,
    make_nonlinear_env,
    make_regime_shift_env,
    run_env_single_seed,
    run_suite,
    run_suite_adaptive,
)


class EnvFactoryTest(unittest.TestCase):
    def test_linear_factory(self) -> None:
        env = make_linear_env(seed=1)
        self.assertEqual(env.n_nodes, 4)
        obs = env.observe(10)
        self.assertEqual(len(obs[0]), 4)
        self.assertEqual(env.ground_truth_edges, {(0, 1), (1, 2), (2, 3)})

    def test_regime_shift_factory(self) -> None:
        env = make_regime_shift_env(seed=2)
        self.assertEqual(env.n_nodes, 4)
        obs = env.observe(10)
        self.assertEqual(len(obs[0]), 4)

    def test_nonlinear_factory(self) -> None:
        env = make_nonlinear_env(seed=3)
        self.assertEqual(env.n_nodes, 3)
        obs = env.observe(10)
        self.assertEqual(len(obs[0]), 3)

    def test_latent_factory(self) -> None:
        env = make_latent_env(seed=4)
        self.assertEqual(env.n_nodes, 3)
        obs = env.observe(10)
        self.assertEqual(len(obs[0]), 3)
        self.assertEqual(env.ground_truth_observed_edges, {(0, 2)})


class SingleSeedRunnerTest(unittest.TestCase):
    def test_run_env_single_seed_linear(self) -> None:
        result = run_env_single_seed(
            make_linear_env,
            seed=42,
            budget=6,
            rounds=2,
            n_obs_per_round=30,
            interventions_per_round=3,
            n_particles=20,
        )
        self.assertEqual(result["seed"], 42)
        self.assertIn(result["status"], ("VERIFIED", "BUDGET_EXHAUSTED"))
        self.assertGreaterEqual(result["shd"], 0)
        self.assertIn("precision", result)
        self.assertIn("recall", result)
        self.assertIn("f1", result)

    def test_run_env_single_seed_nonlinear_uses_poly2(self) -> None:
        result = run_env_single_seed(
            make_nonlinear_env,
            seed=42,
            budget=6,
            rounds=2,
            n_obs_per_round=30,
            interventions_per_round=3,
            n_particles=20,
            likelihood_mode="poly2",
        )
        self.assertIn(result["status"], ("VERIFIED", "BUDGET_EXHAUSTED"))
        self.assertGreaterEqual(result["shd"], 0)


class SuiteTest(unittest.TestCase):
    def test_run_suite_returns_all_families(self) -> None:
        result = run_suite(seeds=[42, 43], budget=6, n_particles=20)
        self.assertIn("seeds", result)
        self.assertEqual(set(result["families"].keys()), {s.name for s in ENV_SPECS})
        for family in result["families"].values():
            self.assertEqual(len(family["per_seed"]), 2)
            agg = family["aggregate"]
            self.assertIn("shd_mean", agg)
            self.assertIn("f1_mean", agg)
            self.assertGreaterEqual(agg["shd_mean"], 0)

    def test_suite_is_deterministic_for_fixed_seed(self) -> None:
        result1 = run_suite(seeds=[42], budget=6, n_particles=20)
        result2 = run_suite(seeds=[42], budget=6, n_particles=20)
        for name in result1["families"]:
            self.assertEqual(
                result1["families"][name]["per_seed"][0]["shd"],
                result2["families"][name]["per_seed"][0]["shd"],
            )

    def test_run_suite_adaptive_returns_all_families(self) -> None:
        result = run_suite_adaptive(seeds=[42], budget=6, n_particles=20)
        self.assertEqual(set(result["families"].keys()), {s.name for s in ENV_SPECS})
        for family in result["families"].values():
            self.assertEqual(len(family["per_seed"]), 1)
            agg = family["aggregate"]
            self.assertIn("shd_mean", agg)
            self.assertGreaterEqual(agg["shd_mean"], 0)


if __name__ == "__main__":
    unittest.main()
