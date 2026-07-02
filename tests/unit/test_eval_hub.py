from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_core.eval_hub import (  # noqa: E402
    EvalCaseOutcome,
    EvalThresholdReporter,
    thresholds_from_json,
)


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

    def test_threshold_json_rejects_boolean_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be numeric"):
            thresholds_from_json('{"intent": true}')

    def test_report_serializes_gate_ready_summary(self) -> None:
        reporter = EvalThresholdReporter({"intent": 1.0, "evidence": 1.0})

        report = reporter.build(
            (
                EvalCaseOutcome(
                    case_id="gmv_daily",
                    checks={"intent": True, "evidence": True},
                ),
            )
        )

        self.assertTrue(hasattr(report, "to_dict"))
        self.assertEqual(
            report.to_dict(),
            {
                "passed": True,
                "case_count": 1,
                "dimensions": [
                    {
                        "name": "intent",
                        "passed": 1,
                        "total": 1,
                        "threshold": 1.0,
                        "pass_rate": 1.0,
                        "meets_threshold": True,
                    },
                    {
                        "name": "evidence",
                        "passed": 1,
                        "total": 1,
                        "threshold": 1.0,
                        "pass_rate": 1.0,
                        "meets_threshold": True,
                    },
                ],
                "failures": [],
            },
        )

    def test_cli_exits_nonzero_when_threshold_report_fails(self) -> None:
        thresholds = json.dumps({"intent": 1.0, "evidence": 1.0})
        outcomes = json.dumps(
            [
                {
                    "case_id": "gmv_daily",
                    "checks": {"intent": True, "evidence": False},
                    "reasons": ["EvidenceChain incomplete"],
                }
            ]
        )

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_os_core.eval_hub",
                "--thresholds-json",
                thresholds,
                "--outcomes-json",
                outcomes,
            ],
            cwd=ROOT,
            env={
                "PYTHONPATH": f"{ROOT / 'packages' / 'contracts' / 'src'}:"
                f"{ROOT / 'packages' / 'os_core' / 'src'}"
            },
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["passed"])
        self.assertIn("gmv_daily:evidence failed", payload["failures"])
        self.assertIn("gmv_daily: EvidenceChain incomplete", payload["failures"])


if __name__ == "__main__":
    unittest.main()
