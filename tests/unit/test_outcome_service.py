from __future__ import annotations

import unittest
from pathlib import Path

from agent_os_api.outcome_service import record_outcome_service, run_service
from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

DOMAIN_PACK = Path("domain_packs/content_commerce")
RUN_PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}


def _build_runtime():
    return ContentCommerceRuntimeFactory(RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK)).build()


class RunServiceTest(unittest.TestCase):
    def test_run_service_returns_trace_and_summary(self) -> None:
        runtime = _build_runtime()
        summary = run_service(runtime, question="GMV", parameters=RUN_PARAMS)

        self.assertEqual(summary["status"], "ok")
        self.assertTrue(summary["trace_id"].startswith("trace-"))
        self.assertIsInstance(summary["intent"], str)
        self.assertEqual(summary["row_count"], 1)
        # A run sediments a DRAFT knowledge asset for the trace.
        self.assertIsNotNone(summary["knowledge_asset_id"])
        self.assertEqual(runtime.knowledge_store.version_of(summary["trace_id"]), 1)

    def test_run_service_blocked_returns_structured_block(self) -> None:
        # 'revenue' parses to a metric the pack does not define -> UNKNOWN_METRIC.
        runtime = _build_runtime()
        summary = run_service(runtime, question="revenue", parameters=RUN_PARAMS)

        self.assertEqual(summary["status"], "blocked")
        self.assertNotIn("trace_id", summary)
        self.assertEqual(summary["block"]["code"], "unknown_metric")
        self.assertEqual(summary["block"]["stage"], "metric_resolution")


class RecordOutcomeServiceTest(unittest.TestCase):
    def test_record_outcome_bumps_knowledge_version(self) -> None:
        runtime = _build_runtime()
        summary = run_service(runtime, question="GMV", parameters=RUN_PARAMS)
        trace_id = summary["trace_id"]

        result = record_outcome_service(
            runtime,
            trace_id=trace_id,
            outcome="adopted",
            reviewer="ops@example.com",
            metric_deltas={"gmv": 1000.0},
        )

        self.assertEqual(result["trace_id"], trace_id)
        self.assertEqual(result["outcome"], "adopted")
        self.assertEqual(result["reviewer"], "ops@example.com")
        self.assertTrue(result["feedback_id"].startswith("feedback-"))
        # Recording an outcome supersedes the DRAFT candidate: version bumps to 2.
        self.assertEqual(result["knowledge_version"], 2)
        self.assertEqual(runtime.knowledge_store.version_of(trace_id), 2)
        self.assertIsNotNone(result["knowledge_asset_id"])

    def test_record_outcome_unknown_trace_is_recorded_without_asset(self) -> None:
        runtime = _build_runtime()
        result = record_outcome_service(
            runtime,
            trace_id="trace-does-not-exist",
            outcome="rejected",
        )

        self.assertEqual(result["trace_id"], "trace-does-not-exist")
        self.assertEqual(result["outcome"], "rejected")
        self.assertIsNone(result["reviewer"])
        self.assertTrue(result["feedback_id"].startswith("feedback-"))
        # No prior run for this trace: no asset fabricated, version stays 0.
        self.assertIsNone(result["knowledge_asset_id"])
        self.assertEqual(result["knowledge_version"], 0)


if __name__ == "__main__":
    unittest.main()
