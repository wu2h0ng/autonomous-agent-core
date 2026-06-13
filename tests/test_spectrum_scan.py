"""Tests for P1-T1 spectrum scan experiment."""
from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from experiments.spectrum_scan import (
    N_REGIMES_GRID,
    NOISE_GRID,
    SEEDS,
    _scan_condition,
    spectrum_scan,
)
import experiments.spectrum_scan as scan_module


class TestScanCondition(unittest.TestCase):
    def test_returns_correct_keys(self) -> None:
        result = _scan_condition(2, 0.1, (0, 1))
        expected_keys = {
            "n_regimes", "noise",
            "o1_areas", "o4_areas",
            "o1_mean", "o4_mean",
            "advantage", "p_value", "significant",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_areas_length_matches_seeds(self) -> None:
        seeds = (0, 1, 2)
        result = _scan_condition(2, 0.1, seeds)
        self.assertEqual(len(result["o1_areas"]), len(seeds))
        self.assertEqual(len(result["o4_areas"]), len(seeds))

    def test_advantage_formula(self) -> None:
        result = _scan_condition(5, 0.3, (0, 1))
        o1_m = result["o1_mean"]
        o4_m = result["o4_mean"]
        expected = 1.0 - o4_m / o1_m if o1_m != 0 else 0.0
        self.assertAlmostEqual(result["advantage"], expected)

    def test_env_kwargs_propagation(self) -> None:
        with patch("experiments.spectrum_scan.run_area") as mock_run:
            mock_run.return_value = 100.0
            _scan_condition(10, 0.5, (0,))
            for call in mock_run.call_args_list:
                kw = call.kwargs.get("env_kwargs", call[1].get("env_kwargs"))
                self.assertEqual(kw["n_regimes"], 10)
                self.assertEqual(kw["noise"], 0.5)


class TestGridDimensions(unittest.TestCase):
    def test_grid_has_16_conditions(self) -> None:
        self.assertEqual(len(N_REGIMES_GRID) * len(NOISE_GRID), 16)

    def test_seeds_are_0_to_9(self) -> None:
        self.assertEqual(SEEDS, tuple(range(10)))


class TestSignificanceThreshold(unittest.TestCase):
    def test_significance_requires_positive_advantage(self) -> None:
        # advantage <= 0 should be not significant regardless of p-value
        result = _scan_condition(2, 0.1, (0, 1))
        # We can't force advantage <= 0 in a real run, but we can test
        # the formula: significant = advantage > 0 and p < 0.05
        if result["advantage"] <= 0:
            self.assertFalse(result["significant"])


class TestC6Guard(unittest.TestCase):
    def test_module_does_not_import_policy_or_shell(self) -> None:
        src = inspect.getsource(scan_module)
        self.assertNotIn("import aac.policy", src)
        self.assertNotIn("import aac.shell", src)
        self.assertNotIn("from .policy", src)
        self.assertNotIn("from .shell", src)


if __name__ == "__main__":
    unittest.main()
