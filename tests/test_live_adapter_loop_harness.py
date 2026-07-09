"""Tests for the end-to-end adapter harness (simulation env + adapter + loop + metrics)."""
from __future__ import annotations

import unittest

from aac.live_intervention_env import CausalSimulationEnv
from experiments.live_adapter_loop_harness import (
    run_csv_adapter_harness,
    run_queue_adapter_harness,
)


def _env_factory(seed: int) -> CausalSimulationEnv:
    return CausalSimulationEnv(
        n_nodes=4,
        edges={(0, 1), (1, 2), (2, 3)},
        seed=seed,
        noise_std=0.2,
        coef_range=(0.8, 0.8),
    )


class LiveAdapterLoopHarnessTest(unittest.TestCase):
    def test_queue_adapter_harness_runs_and_scores(self) -> None:
        result = run_queue_adapter_harness(
            _env_factory,
            seed=42,
            n_obs_initial=80,
            rounds=2,
            n_obs_per_round=40,
            interventions_per_round=3,
            budget=6,
            n_particles=20,
            confidence_threshold=1.0,
        )
        self.assertEqual(result.interventions_spent, 6)
        self.assertIn("model_rmse", result.predictive_validation)
        self.assertIn("direction_accuracy", result.interventional_agreement)
        self.assertIsNotNone(result.predictive_validation["model_rmse"])
        self.assertIsNotNone(result.interventional_agreement["direction_accuracy"])

    def test_csv_adapter_harness_runs_and_scores(self) -> None:
        result = run_csv_adapter_harness(
            _env_factory,
            seed=43,
            n_obs=120,
            budget=6,
            rounds=2,
            n_obs_per_round=40,
            interventions_per_round=3,
            n_particles=20,
            confidence_threshold=1.0,
        )
        self.assertEqual(result.interventions_spent, 6)
        self.assertIn("model_rmse", result.predictive_validation)
        self.assertIn("direction_accuracy", result.interventional_agreement)
        self.assertIsNotNone(result.predictive_validation["model_rmse"])
        self.assertIsNotNone(result.interventional_agreement["direction_accuracy"])

    def test_csv_harness_uses_readback_samples(self) -> None:
        result = run_csv_adapter_harness(
            _env_factory,
            seed=44,
            n_obs=120,
            budget=3,
            rounds=1,
            n_obs_per_round=40,
            interventions_per_round=3,
            n_particles=20,
            confidence_threshold=1.0,
        )
        self.assertEqual(result.interventions_spent, 3)
        self.assertGreater(len(result.int_data), 0)
        for node, value, sample in result.int_data:
            self.assertEqual(len(sample), 4)


if __name__ == "__main__":
    unittest.main()
