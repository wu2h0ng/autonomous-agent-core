from __future__ import annotations

import unittest
from pathlib import Path

from agent_os_contracts import CausalAttributionMethod, CausalOutcomeAttribution
from agent_os_api.outcome_service import (
    attest_adoption_service,
    record_outcome_service,
    run_service,
)
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

    def test_run_service_returns_user_facing_result_artifact(self) -> None:
        runtime = _build_runtime()
        summary = run_service(runtime, question="GMV 记录行动", parameters=RUN_PARAMS)

        artifact = summary["user_result"]
        self.assertEqual(artifact["kind"], "data_agent_result")
        self.assertEqual(artifact["trace_id"], summary["trace_id"])
        self.assertEqual(artifact["evidence_chain_id"], summary["evidence_chain_id"])
        self.assertEqual(
            artifact["analysis"]["evidence_chain_id"],
            summary["evidence_chain_id"],
        )
        self.assertGreater(artifact["analysis"]["confidence"], 0)
        self.assertTrue(artifact["report"]["sections"])

        dashboard = artifact["dashboard"]
        widget_types = {widget["type"] for widget in dashboard["widgets"]}
        self.assertIn("kpi", widget_types)
        self.assertIn("table", widget_types)
        table = next(widget for widget in dashboard["widgets"] if widget["type"] == "table")
        self.assertEqual(table["row_count"], summary["row_count"])
        self.assertEqual(table["evidence_chain_id"], summary["evidence_chain_id"])
        self.assertTrue(table["preview_rows"])

        decision = artifact["decision"]
        self.assertEqual(decision["action_proposal_id"], summary["action_proposal_id"])
        self.assertEqual(decision["risk_level"], "R3")
        self.assertTrue(decision["approval_required"])

        business_action = artifact["business_action"]
        self.assertEqual(business_action["connector_name"], "action_record")
        self.assertEqual(business_action["action_type"], "execute")
        self.assertEqual(business_action["status"], "awaiting_approval")
        self.assertTrue(business_action["approval_id"].startswith("approval-"))
        self.assertEqual(
            business_action["action_parameters"]["evidence_chain_id"],
            summary["evidence_chain_id"],
        )

    def test_run_service_blocked_returns_structured_block(self) -> None:
        # 'revenue' parses to a metric the pack does not define -> UNKNOWN_METRIC.
        runtime = _build_runtime()
        summary = run_service(runtime, question="revenue", parameters=RUN_PARAMS)

        self.assertEqual(summary["status"], "blocked")
        self.assertNotIn("trace_id", summary)
        self.assertEqual(summary["block"]["code"], "unknown_metric")
        self.assertEqual(summary["block"]["stage"], "metric_resolution")


class RecordOutcomeServiceTest(unittest.TestCase):
    def test_record_outcome_does_not_promote_knowledge(self) -> None:
        # P5.1b: a self-report records feedback but MUST NOT promote knowledge.
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
        # Self-report does NOT promote knowledge (wirehead closed): version stays 1.
        self.assertEqual(result["knowledge_version"], 1)
        self.assertEqual(runtime.knowledge_store.version_of(trace_id), 1)

    def test_attest_adoption_promotes_knowledge(self) -> None:
        # P5.1b: realized external value (operator adoption) DOES promote knowledge.
        factory = ContentCommerceRuntimeFactory(RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK))
        runtime = factory.build()
        trace_id = run_service(runtime, question="GMV", parameters=RUN_PARAMS)["trace_id"]

        result = attest_adoption_service(
            runtime,
            factory.adoption_ingest(),
            trace_id=trace_id,
            outcome="adopted",
            reviewer="ops@example.com",
        )

        self.assertEqual(result["trace_id"], trace_id)
        self.assertTrue(result["adoption_id"].startswith("feedback-"))
        # Realized adoption promotes the DRAFT candidate: version bumps to 2.
        self.assertEqual(result["knowledge_version"], 2)
        self.assertEqual(runtime.knowledge_store.version_of(trace_id), 2)
        self.assertIsNotNone(result["knowledge_asset_id"])

    def test_attest_adoption_surfaces_causal_result_weight(self) -> None:
        factory = ContentCommerceRuntimeFactory(RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK))
        runtime = factory.build()
        trace_id = run_service(runtime, question="GMV", parameters=RUN_PARAMS)["trace_id"]

        result = attest_adoption_service(
            runtime,
            factory.adoption_ingest(),
            trace_id=trace_id,
            outcome="adopted",
            reviewer="ops@example.com",
            causal_attribution=CausalOutcomeAttribution(
                metric_name="gmv",
                observed_value=11200.0,
                counterfactual_value=10000.0,
                delta_absolute=1200.0,
                delta_percent=0.12,
                method=CausalAttributionMethod.HOLDOUT,
                comparison_ref="holdout:campaign-42",
                window_start="2026-06-01",
                window_end="2026-06-07",
                confidence=0.8,
            ),
        )

        self.assertEqual(result["result_weight"], 0.8)
        asset = runtime.knowledge_store.get_by_trace(trace_id)
        self.assertIsNotNone(asset)
        self.assertEqual(asset.result_weight, 0.8)

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
