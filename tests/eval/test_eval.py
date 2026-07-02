from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))

from agent_os_core import IntentParser  # noqa: E402
from tests.eval.threshold_report import (  # noqa: E402
    DEFAULT_GOLDEN_QUERIES,
    build_golden_eval_threshold_report,
)


class GoldenQueryEvalTest(unittest.TestCase):
    def test_intent_parser_fallback(self) -> None:
        parser = IntentParser()
        import json

        golden = json.loads(DEFAULT_GOLDEN_QUERIES.read_text(encoding="utf-8"))
        passed = 0
        failed = 0
        failures: list[str] = []
        for c in golden:
            with self.subTest(case_id=c["id"]):
                intent = parser.parse(c["question"])
                if intent.metric_name == c["expected_metric"]:
                    passed += 1
                else:
                    failed += 1
                    failures.append(
                        f"{c['id']}: expected '{c['expected_metric']}' "
                        f"got '{intent.metric_name}' for '{c['question']}'"
                    )
        if failures:
            self.fail(f"Intent: {passed} passed, {failed} failed.\n" + "\n".join(failures))

    def test_golden_query_runs_trusted_loop(self) -> None:
        report = build_golden_eval_threshold_report()

        self.assertTrue(report.passed, report.failures)
        self.assertEqual(report.case_count, 5)
        self.assertEqual(report.dimension("evidence").pass_rate, 1.0)
        self.assertEqual(report.dimension("trace").pass_rate, 1.0)


if __name__ == "__main__":
    unittest.main()
