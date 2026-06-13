"""Deterministic tests for shared G7 experiment utilities."""
from __future__ import annotations

import unittest

from experiments._g7_common import wilcoxon_one_sided


class TestWilcoxonOneSided(unittest.TestCase):
    def test_ranks_are_by_absolute_difference_not_input_order(self) -> None:
        # abs ranks: -1 -> 1, +2 -> 2, +3 -> 3; observed W+ = 5.
        # Under all 8 sign flips, sums >= 5 are {2+3, 1+2+3}.
        self.assertAlmostEqual(wilcoxon_one_sided([2.0, -1.0, 3.0]), 0.25)

    def test_average_ranks_for_ties(self) -> None:
        # Tied |1| values both get rank 1.5; +2 gets rank 3.
        # Observed W+ = 4.5. Sign-flip sums >= 4.5 occur in 3/8 cases.
        self.assertAlmostEqual(wilcoxon_one_sided([1.0, -1.0, 2.0]), 0.375)

    def test_all_positive_has_minimum_one_sided_probability(self) -> None:
        self.assertAlmostEqual(wilcoxon_one_sided([1.0, 2.0, 3.0]), 0.125)

    def test_zero_differences_are_dropped(self) -> None:
        self.assertAlmostEqual(wilcoxon_one_sided([0.0, 1.0, 2.0]), 0.25)


if __name__ == "__main__":
    unittest.main()
