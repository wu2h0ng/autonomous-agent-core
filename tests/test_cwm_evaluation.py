"""Tests for ground-truth-free CWM evaluation metrics."""
from __future__ import annotations

import unittest

from aac.cwm_evaluation import (
    interventional_agreement_score,
    predictive_validation_score,
)
from aac.live_intervention_env import CausalSimulationEnv


class CwmEvaluationTest(unittest.TestCase):
    def _generate(self, seed: int, n_obs: int = 200, n_int: int = 30):
        env = CausalSimulationEnv(
            n_nodes=3,
            edges={(0, 1), (1, 2)},
            seed=seed,
            noise_std=0.2,
            coef_range=(0.8, 0.8),
        )
        obs = env.observe(n_obs)
        int_data = []
        for i in range(n_int):
            node = i % env.n_nodes
            value = 1.0 if i % 2 == 0 else -1.0
            sample = env.intervene(node, value)
            int_data.append((node, value, sample))
        return obs, int_data

    def test_true_dag_beats_empty_dag_predictive(self) -> None:
        obs, int_data = self._generate(42)
        true_score = predictive_validation_score(obs, int_data, {(0, 1), (1, 2)})
        empty_score = predictive_validation_score(obs, int_data, set())
        self.assertIsNotNone(true_score["relative_improvement"])
        self.assertIsNotNone(empty_score["relative_improvement"])
        self.assertGreater(
            true_score["relative_improvement"],
            empty_score["relative_improvement"],
        )

    def test_true_dag_improves_interventional_agreement(self) -> None:
        obs, int_data = self._generate(43)
        true_score = interventional_agreement_score(obs, int_data, {(0, 1), (1, 2)})
        empty_score = interventional_agreement_score(obs, int_data, set())
        self.assertIsNotNone(true_score["direction_accuracy"])
        self.assertIsNotNone(empty_score["direction_accuracy"])
        self.assertGreaterEqual(
            true_score["direction_accuracy"],
            empty_score["direction_accuracy"],
        )

    def test_empty_data_returns_none(self) -> None:
        score = predictive_validation_score([], [], {(0, 1)})
        self.assertIsNone(score["model_rmse"])
        score2 = interventional_agreement_score([], [], {(0, 1)})
        self.assertIsNone(score2["direction_accuracy"])


if __name__ == "__main__":
    unittest.main()
