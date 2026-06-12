from __future__ import annotations

import unittest

from experiments.causal_relevance_g2 import B0, B1, B2, B3, B4, B5, judge_g2


def _rows(steps: float, adaptation: float, n: int = 10) -> list[dict[str, float]]:
    return [
        {
            "steps": steps,
            "adaptation_area": adaptation,
            "regret_per_step": 0.0,
            "adaptation_windows": 1.0,
        }
        for _ in range(n)
    ]


class TestG2Gate(unittest.TestCase):
    def test_met_when_all_pre_registered_thresholds_pass(self) -> None:
        results = {
            B0: _rows(100.0, 0.8),
            B1: _rows(90.0, 0.7),
            B2: _rows(80.0, 0.9),
            B3: _rows(70.0, 0.6),
            B4: _rows(60.0, 0.5),
            B5: _rows(95.0, 0.4),
        }

        self.assertEqual(judge_g2(results).verdict, "MET")

    def test_not_met_when_random_posterior_ablation_matches_adaptation(self) -> None:
        results = {
            B0: _rows(100.0, 0.8),
            B1: _rows(90.0, 0.7),
            B2: _rows(80.0, 0.7),
            B3: _rows(70.0, 0.6),
            B4: _rows(60.0, 0.5),
            B5: _rows(95.0, 0.8),
        }

        verdict = judge_g2(results)

        self.assertEqual(verdict.verdict, "NOT MET")
        self.assertEqual(verdict.adaptation_b5, 0)


if __name__ == "__main__":
    unittest.main()
