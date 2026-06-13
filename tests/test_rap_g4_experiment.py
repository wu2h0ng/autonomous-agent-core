"""Unit tests for the G4 experiment accounting helpers."""
from __future__ import annotations

import unittest

from experiments.rap_g4 import (
    EPSILON,
    RunMetrics,
    SeedResult,
    _segments,
    _tax,
    judge_g4,
)


def _metrics(
    mean: float,
    drop: float,
    tax: float = 0.2,
    *,
    audit_ok: bool = True,
    evidence_ok: bool = True,
) -> RunMetrics:
    return RunMetrics(
        mean_regret=mean,
        drop_regret_area=drop,
        drop_steps=10,
        orchestration_tax=tax,
        bonds=10,
        audit_ok=audit_ok,
        evidence_ok=evidence_ok,
    )


class TestG4Accounting(unittest.TestCase):
    def test_tax_is_overhead_fraction(self) -> None:
        self.assertEqual(_tax(0, 3), 0.0)
        self.assertAlmostEqual(_tax(2, 2), 0.5)
        self.assertEqual(_tax(0, 0), 1.0)

    def test_segments_cover_gate_steps_and_include_disturbance(self) -> None:
        segments = _segments(0, disturbed=True)
        self.assertEqual(sum(s.length for s in segments), 1500)
        self.assertTrue(any(s.disturbance.value == "node_drop" for s in segments))

    def test_judge_g4_requires_all_four_criteria(self) -> None:
        rows = [
            SeedResult(
                seed=i,
                fixed_node_id="fixed",
                c_rap=_metrics(1.0, 1.0, 0.2),
                b_fixed=_metrics(2.0, 2.0, 0.0),
                b_central=_metrics(1.0 + EPSILON, 1.0, 0.25),
            )
            for i in range(10)
        ]
        self.assertEqual(judge_g4(rows).verdict, "MET")

        failed_tax = [
            SeedResult(
                seed=i,
                fixed_node_id="fixed",
                c_rap=_metrics(1.0, 1.0, 0.9),
                b_fixed=_metrics(2.0, 2.0, 0.0),
                b_central=_metrics(1.0 + EPSILON, 1.0, 0.25),
            )
            for i in range(10)
        ]
        self.assertEqual(judge_g4(failed_tax).verdict, "NOT MET")


if __name__ == "__main__":
    unittest.main()
