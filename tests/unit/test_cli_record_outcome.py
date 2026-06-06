from __future__ import annotations

import io
import json
import unittest

from agent_os_api.cli import run_cli


class CliQueryStillWorksTest(unittest.TestCase):
    def test_default_query_subcommand_emits_evidence(self) -> None:
        out = io.StringIO()
        rc = run_cli(
            [
                "query",
                "--question",
                "GMV",
                "--start-date",
                "2026-05-25",
                "--end-date",
                "2026-06-01",
                "--limit",
                "100",
            ],
            stdout=out,
        )
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertIn("evidence_chain_id", payload)
        self.assertIn("trace_id", payload)
        self.assertEqual(payload["row_count"], 1)


class CliRecordOutcomeTest(unittest.TestCase):
    def test_record_outcome_subcommand_emits_json(self) -> None:
        out = io.StringIO()
        rc = run_cli(
            [
                "record-outcome",
                "--trace-id",
                "trace-unknown-cli",
                "--outcome",
                "adopted",
                "--reviewer",
                "ops@example.com",
                "--metric",
                "gmv=1000.0",
                "--metric",
                "orders=12",
            ],
            stdout=out,
        )
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["trace_id"], "trace-unknown-cli")
        self.assertEqual(payload["outcome"], "adopted")
        self.assertEqual(payload["reviewer"], "ops@example.com")
        self.assertTrue(payload["feedback_id"].startswith("feedback-"))
        # Fresh process: the in-memory store has no prior run for this trace.
        self.assertIsNone(payload["knowledge_asset_id"])
        self.assertEqual(payload["knowledge_version"], 0)

    def test_record_outcome_rejects_bad_metric_format(self) -> None:
        out = io.StringIO()
        with self.assertRaises(SystemExit):
            run_cli(
                [
                    "record-outcome",
                    "--trace-id",
                    "trace-x",
                    "--outcome",
                    "adopted",
                    "--metric",
                    "no_equals_sign",
                ],
                stdout=out,
            )


if __name__ == "__main__":
    unittest.main()
