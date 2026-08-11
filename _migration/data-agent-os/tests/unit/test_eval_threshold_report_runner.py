from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class EvalThresholdReportRunnerTest(unittest.TestCase):
    def test_golden_eval_report_runner_emits_passing_threshold_report(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = (
            f"{ROOT / 'packages' / 'contracts' / 'src'}:"
            f"{ROOT / 'packages' / 'os_core' / 'src'}:"
            f"{ROOT / 'action_connectors'}"
        )

        result = subprocess.run(
            [sys.executable, "-m", "tests.eval.threshold_report"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["case_count"], 20)
        dimensions = {item["name"]: item for item in payload["dimensions"]}
        self.assertEqual(dimensions["intent"]["pass_rate"], 1.0)
        self.assertEqual(dimensions["nl_intent"]["pass_rate"], 1.0)
        self.assertEqual(dimensions["sql_safety"]["pass_rate"], 1.0)
        self.assertEqual(dimensions["evidence"]["pass_rate"], 1.0)
        self.assertEqual(dimensions["evidence_typed"]["pass_rate"], 1.0)
        self.assertEqual(dimensions["action"]["pass_rate"], 1.0)
        self.assertEqual(dimensions["feedback"]["pass_rate"], 1.0)
        self.assertEqual(payload["failures"], [])

    def test_golden_eval_report_runner_writes_output_file(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = (
            f"{ROOT / 'packages' / 'contracts' / 'src'}:"
            f"{ROOT / 'packages' / 'os_core' / 'src'}:"
            f"{ROOT / 'action_connectors'}"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "golden-threshold-report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tests.eval.threshold_report",
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            stdout_payload = json.loads(result.stdout)
            file_payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(file_payload, stdout_payload)
            self.assertTrue(file_payload["passed"])

    def test_golden_eval_report_runner_fail_closed_report_can_be_written(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = (
            f"{ROOT / 'packages' / 'contracts' / 'src'}:"
            f"{ROOT / 'packages' / 'os_core' / 'src'}:"
            f"{ROOT / 'action_connectors'}"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "failed-threshold-report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tests.eval.threshold_report",
                    "--thresholds-json",
                    '{"missing_gate":1.0}',
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertFalse(payload["passed"])
            self.assertEqual(payload["case_count"], 20)
            self.assertIn("gmv_daily:missing_gate missing", payload["failures"])
            self.assertEqual(json.loads(result.stdout), payload)

    def test_make_eval_threshold_report_writes_gate_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "make-threshold-report.json"
            result = subprocess.run(
                [
                    "make",
                    "eval-threshold-report",
                    f"PYTHON={sys.executable}",
                    f"EVAL_THRESHOLD_REPORT_OUT={output_path}",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["passed"])
            self.assertEqual(payload["case_count"], 20)

    def test_ci_target_includes_eval_threshold_report_gate(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        ci_line = next(line for line in makefile.splitlines() if line.startswith("ci: "))

        self.assertIn("eval-threshold-report", ci_line)

    def test_make_eval_threshold_report_uses_reviewable_threshold_file(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("EVAL_THRESHOLDS_FILE ?= tests/eval/golden_thresholds.json", makefile)
        self.assertIn("--thresholds-file $(EVAL_THRESHOLDS_FILE)", makefile)

        thresholds_path = ROOT / "tests" / "eval" / "golden_thresholds.json"
        thresholds = json.loads(thresholds_path.read_text(encoding="utf-8"))
        self.assertEqual(
            thresholds,
            {
                "intent": 1.0,
                "nl_intent": 1.0,
                "metric": 1.0,
                "provider": 1.0,
                "data_product": 1.0,
                "sql_safety": 1.0,
                "evidence": 1.0,
                "evidence_typed": 1.0,
                "action": 1.0,
                "trace": 1.0,
                "feedback": 1.0,
                # P2-C (ADR-0017): bypass-detecting confidence-derivation gate.
                "confidence_derivation": 1.0,
            },
        )


if __name__ == "__main__":
    unittest.main()
