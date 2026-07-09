"""Tests for Perturb-seq placebo generator and §4.4 validation gate."""

from __future__ import annotations

import math
import unittest

from aac.placebo_perturb_seq import (
    generate_placebo_perturb_seq,
    validate_placebo_nonidentifiability_perturb_seq,
    _covariance_matrix,
    _correlation_scores,
)


class TestPlaceboPerturbSeq(unittest.TestCase):
    def _synthetic_observational(self, n: int = 80, seed: float = 1.0) -> list[list[float]]:
        """Generate n 3-dim rows with correlated structure."""
        rows: list[list[float]] = []
        for i in range(n):
            x0 = math.sin(i * 0.1 + seed) + 0.1 * (i % 3)
            x1 = x0 * 0.8 + math.cos(i * 0.2)
            x2 = x0 * 0.5 - x1 * 0.3 + (i % 5) * 0.05
            rows.append([x0, x1, x2])
        return rows

    def test_generate_placebo_preserves_count(self) -> None:
        obs = self._synthetic_observational(80)
        interventions: dict[tuple[int, str], list[list[float]]] = {
            (0, "ko"): [[1.0, 2.0, 3.0] for _ in range(20)],
            (1, "ko"): [[4.0, 5.0, 6.0] for _ in range(30)],
        }
        placebo, p_obs = generate_placebo_perturb_seq(obs, interventions, seed=123)
        self.assertEqual(len(p_obs), len(obs))
        for key, original in interventions.items():
            self.assertIn(key, placebo)
            self.assertEqual(len(placebo[key]), len(original))
            # placebo rows are sampled from observational pool, so each row has same dimension
            self.assertEqual(len(placebo[key][0]), len(obs[0]))

    def test_generate_placebo_empty_obs(self) -> None:
        placebo, p_obs = generate_placebo_perturb_seq([], {(0, "ko"): [[1.0]]}, seed=1)
        self.assertEqual(p_obs, [])
        self.assertEqual(placebo, {})

    def test_covariance_symmetric(self) -> None:
        obs = self._synthetic_observational(50)
        cov = _covariance_matrix(obs)
        n = len(obs[0])
        self.assertEqual(len(cov), n)
        for i in range(n):
            self.assertEqual(len(cov[i]), n)
            for j in range(n):
                self.assertAlmostEqual(cov[i][j], cov[j][i], places=10)

    def test_validate_placebo_passes_on_randomized_data(self) -> None:
        obs = self._synthetic_observational(120)
        # interventions are also just more observational draws, so KO labels are meaningless
        interventions: dict[tuple[int, str], list[list[float]]] = {
            (0, "ko"): self._synthetic_observational(40, seed=2.0),
            (1, "ko"): self._synthetic_observational(40, seed=3.0),
        }
        placebo, p_obs = generate_placebo_perturb_seq(obs, interventions, seed=456)
        result = validate_placebo_nonidentifiability_perturb_seq(
            obs, p_obs, placebo, effect_threshold=1.5, ap_threshold=0.55, cov_threshold=0.05
        )
        self.assertTrue(result.passes)
        self.assertLessEqual(result.max_ap, 0.55)
        self.assertLessEqual(result.covariance_distance, 0.05)


if __name__ == "__main__":
    unittest.main()
