from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_core.eval_hub import EvalCaseOutcome, EvalThresholdReporter  # noqa: E402


class EvalThresholdReporterTest(unittest.TestCase):
    def test_report_passes_when_all_dimensions_meet_thresholds(self) -> None:
        reporter = EvalThresholdReporter(
            {
                "intent": 1.0,
                "metric": 1.0,
                "sql_safety": 1.0,
                "evidence": 1.0,
                "action": 1.0,
            }
        )

        report = reporter.build(
            (
                EvalCaseOutcome(
                    case_id="gmv_daily",
                    checks={
                        "intent": True,
                        "metric": True,
                        "sql_safety": True,
                        "evidence": True,
                        "action": True,
                    },
                ),
            )
        )

        self.assertTrue(report.passed)
        self.assertEqual(report.case_count, 1)
        self.assertEqual(report.dimension("evidence").pass_rate, 1.0)
        self.assertEqual(report.failures, ())

    def test_report_fails_when_dimension_below_threshold_or_missing(self) -> None:
        reporter = EvalThresholdReporter(
            {
                "intent": 1.0,
                "metric": 1.0,
                "sql_safety": 1.0,
                "evidence": 1.0,
                "action": 1.0,
            }
        )

        report = reporter.build(
            (
                EvalCaseOutcome(
                    case_id="gmv_daily",
                    checks={
                        "intent": True,
                        "metric": True,
                        "sql_safety": True,
                        "evidence": True,
                        "action": True,
                    },
                ),
                EvalCaseOutcome(
                    case_id="roi_trend",
                    checks={
                        "intent": True,
                        "metric": True,
                        "evidence": True,
                        "action": False,
                    },
                    reasons=("proposal risk level missing",),
                ),
            )
        )

        self.assertFalse(report.passed)
        self.assertEqual(report.case_count, 2)
        self.assertEqual(report.dimension("sql_safety").passed, 1)
        self.assertEqual(report.dimension("sql_safety").total, 2)
        self.assertEqual(report.dimension("action").pass_rate, 0.5)
        self.assertIn("roi_trend:sql_safety missing", report.failures)
        self.assertIn("roi_trend:action failed", report.failures)
        self.assertIn("roi_trend: proposal risk level missing", report.failures)

    def test_report_rejects_empty_outcomes(self) -> None:
        reporter = EvalThresholdReporter({"intent": 1.0})

        with self.assertRaisesRegex(ValueError, "at least one eval outcome"):
            reporter.build(())


if __name__ == "__main__":
    unittest.main()
