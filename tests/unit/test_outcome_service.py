from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace
import unittest
from pathlib import Path

from agent_os_contracts import (
    ActionProposal,
    BusinessIntent,
    CausalAttributionMethod,
    CausalOutcomeAttribution,
    DataClassification,
    EvidenceChain,
    LifecycleState,
    MetricContract,
    QueryPlan,
    QueryResult,
    RiskLevel,
    SQLSafetyResult,
)
from agent_os_api.outcome_service import (
    _build_user_result_artifact,
    approve_and_execute_service,
    attest_adoption_service,
    knowledge_publish_service,
    knowledge_review_action_service,
    knowledge_review_queue_service,
    record_outcome_service,
    run_service,
)
import agent_os_api.outcome_service as outcome_service
from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

DOMAIN_PACK = Path("domain_packs/content_commerce")
RUN_PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}


def _build_runtime():
    return ContentCommerceRuntimeFactory(RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK)).build()


def _build_result_for_classification(classification: DataClassification) -> SimpleNamespace:
    metric = MetricContract(
        metric_name="orders",
        display_name="Orders",
        definition="Count of completed orders",
        owner="RevOps",
        unit="orders",
        allowed_schemas=("ops",),
        version="v9",
        dimensions=("channel",),
        data_classification=classification,
    )
    evidence = EvidenceChain(
        evidence_chain_id="evidence-orders",
        intent=BusinessIntent(
            intent_id="intent-orders",
            question="orders by channel",
            metric_name="orders",
        ),
        metric_contract=metric,
        query_plan=QueryPlan(
            metric_name="orders",
            sql=(
                "SELECT channel, COUNT(*) AS orders FROM ops.daily_orders "
                "WHERE day >= :start_date AND secret = :secret_token LIMIT :limit"
            ),
            parameters={
                "start_date": "2026-06-01",
                "secret_token": "do-not-leak",
                "limit": 7,
            },
        ),
        sql_safety=SQLSafetyResult(
            allowed=True,
            reasons=("ok",),
            checked_schemas=("ops",),
            checked_tables=("ops.daily_orders",),
            bound_parameters=("limit", "secret_token", "start_date"),
            limit_value=7,
        ),
        query_result=QueryResult(rows=({"channel": "email", "orders": 5},), row_count=1),
        conclusion="Orders are 5.",
        confidence=0.74,
        limitations=("sample data",),
        trace_id="trace-orders",
    )
    proposal = ActionProposal(
        proposal_id="proposal-orders",
        evidence_chain_id=evidence.evidence_chain_id,
        target_object="orders",
        recommended_action="review orders",
        reason="needs review",
        risk_level=RiskLevel.R2,
        expected_impact="better visibility",
        approval_required=False,
        approver_role=None,
    )
    return SimpleNamespace(
        evidence_chain=evidence,
        action_proposal=proposal,
        action_result={},
    )


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
        self.assertEqual(artifact["audience"], "internal")
        self.assertEqual(
            artifact["redaction"],
            {
                "audience": "internal",
                "applied": False,
                "data_classification": "internal",
                "redacted_fields": [],
                "reason": None,
            },
        )
        self.assertEqual(artifact["kind"], "data_agent_result")
        self.assertEqual(artifact["trace_id"], summary["trace_id"])
        self.assertEqual(artifact["evidence_chain_id"], summary["evidence_chain_id"])
        self.assertEqual(
            artifact["analysis"]["evidence_chain_id"],
            summary["evidence_chain_id"],
        )
        self.assertGreater(artifact["analysis"]["confidence"], 0)
        self.assertTrue(artifact["report"]["sections"])

        report = artifact["report"]
        self.assertIn("evidence_cards", report)
        cards = {card["card_id"]: card for card in report["evidence_cards"]}
        self.assertEqual(set(cards), {"metric_contract", "sql_safety", "query_result"})
        self.assertEqual(cards["metric_contract"]["metric_name"], "gmv")
        self.assertEqual(cards["metric_contract"]["metric_version"], "v1")
        self.assertEqual(cards["metric_contract"]["display_name"], "GMV")
        self.assertEqual(
            cards["metric_contract"]["derived_from"], ["EvidenceChain.metric_contract"]
        )
        self.assertEqual(
            cards["metric_contract"]["evidence_chain_id"], summary["evidence_chain_id"]
        )
        self.assertEqual(cards["sql_safety"]["sql_safety_allowed"], True)
        self.assertEqual(cards["sql_safety"]["query_metric_name"], "gmv")
        self.assertEqual(cards["sql_safety"]["checked_schemas"], ["sales"])
        self.assertEqual(cards["sql_safety"]["checked_tables"], ["sales.orders"])
        self.assertEqual(
            cards["sql_safety"]["bound_parameter_names"],
            ["end_date", "limit", "start_date"],
        )
        self.assertEqual(cards["sql_safety"]["limit_value"], 100)
        self.assertTrue(cards["sql_safety"]["sql_fingerprint"].startswith("sha256:"))
        self.assertEqual(
            cards["sql_safety"]["derived_from"],
            ["EvidenceChain.query_plan", "EvidenceChain.sql_safety"],
        )
        self.assertEqual(cards["query_result"]["row_count"], summary["row_count"])
        self.assertEqual(cards["query_result"]["columns"], ["order_date", "value"])
        self.assertEqual(cards["query_result"]["preview_row_count"], 1)
        self.assertEqual(cards["query_result"]["derived_from"], ["EvidenceChain.query_result"])
        rendered_cards = json.dumps(report["evidence_cards"], sort_keys=True)
        self.assertNotIn("select order_date", rendered_cards.lower())
        self.assertNotIn("2026-05-25", rendered_cards)
        self.assertNotIn("2026-06-01", rendered_cards)

        dashboard = artifact["dashboard"]
        widget_types = {widget["type"] for widget in dashboard["widgets"]}
        self.assertIn("kpi", widget_types)
        self.assertIn("line_chart", widget_types)
        self.assertIn("table", widget_types)
        chart = next(widget for widget in dashboard["widgets"] if widget["type"] == "line_chart")
        self.assertEqual(chart["x_field"], "order_date")
        self.assertEqual(chart["y_field"], "value")
        self.assertEqual(chart["row_count"], summary["row_count"])
        self.assertEqual(chart["preview_rows"], [{"order_date": "2026-05-31", "value": 128800.0}])
        self.assertEqual(chart["evidence_chain_id"], summary["evidence_chain_id"])
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
        self.assertEqual(business_action["evidence_chain_id"], summary["evidence_chain_id"])
        self.assertEqual(business_action["trace_id"], summary["trace_id"])

    def test_external_audience_redacts_internal_table_columns_and_previews(self) -> None:
        runtime = _build_runtime()

        summary = run_service(
            runtime,
            question="GMV 记录行动",
            parameters=RUN_PARAMS,
            audience="external",
        )

        artifact = summary["user_result"]
        self.assertEqual(artifact["audience"], "external")
        self.assertEqual(
            artifact["redaction"],
            {
                "audience": "external",
                "applied": True,
                "data_classification": "internal",
                "redacted_fields": [
                    "checked_schemas",
                    "checked_tables",
                    "metric_dimensions",
                    "bound_parameter_names",
                    "limit_value",
                    "sql_fingerprint",
                    "columns",
                    "preview_rows",
                    "chart_fields",
                    "metric_values",
                ],
                "reason": "external audience cannot view non-public result details",
            },
        )

        cards = {card["card_id"]: card for card in artifact["report"]["evidence_cards"]}
        self.assertEqual(cards["sql_safety"]["checked_schemas"], [])
        self.assertEqual(cards["sql_safety"]["checked_tables"], [])
        self.assertEqual(cards["sql_safety"]["bound_parameter_names"], [])
        self.assertIsNone(cards["sql_safety"]["limit_value"])
        self.assertIsNone(cards["sql_safety"]["sql_fingerprint"])
        self.assertEqual(cards["query_result"]["columns"], [])
        self.assertEqual(cards["query_result"]["preview_row_count"], 0)

        for widget in artifact["dashboard"]["widgets"]:
            self.assertEqual(widget["columns"], [])
            self.assertEqual(widget["preview_rows"], [])
            self.assertIsNone(widget["x_field"])
            self.assertIsNone(widget["y_field"])
            if widget["type"] == "kpi":
                self.assertIsNone(widget["value"])

        rendered = json.dumps(artifact, sort_keys=True)
        self.assertNotIn("sales.orders", rendered)
        self.assertNotIn("order_date", rendered)
        self.assertNotIn("sha256:", rendered)
        self.assertNotIn("start_date", rendered)
        self.assertNotIn("2026-05-31", rendered)
        self.assertNotIn("128800.0", rendered)

    def test_external_audience_keeps_public_metric_details(self) -> None:
        artifact = _build_user_result_artifact(
            _build_result_for_classification(DataClassification.PUBLIC),
            audience="external",
        )

        self.assertEqual(artifact["audience"], "external")
        self.assertEqual(
            artifact["redaction"],
            {
                "audience": "external",
                "applied": True,
                "data_classification": "public",
                "redacted_fields": [
                    "checked_schemas",
                    "checked_tables",
                    "bound_parameter_names",
                    "limit_value",
                    "sql_fingerprint",
                ],
                "reason": "external audience cannot view source or SQL infrastructure",
            },
        )
        cards = {card["card_id"]: card for card in artifact["report"]["evidence_cards"]}
        self.assertEqual(cards["metric_contract"]["dimensions"], ["channel"])
        self.assertEqual(cards["sql_safety"]["checked_schemas"], [])
        self.assertEqual(cards["sql_safety"]["checked_tables"], [])
        self.assertEqual(cards["sql_safety"]["bound_parameter_names"], [])
        self.assertIsNone(cards["sql_safety"]["limit_value"])
        self.assertIsNone(cards["sql_safety"]["sql_fingerprint"])
        self.assertEqual(cards["query_result"]["columns"], ["channel", "orders"])
        table = next(
            widget for widget in artifact["dashboard"]["widgets"] if widget["type"] == "table"
        )
        self.assertEqual(table["preview_rows"], [{"channel": "email", "orders": 5}])
        chart = next(
            widget for widget in artifact["dashboard"]["widgets"] if widget["type"] == "line_chart"
        )
        self.assertEqual(chart["x_field"], "channel")
        self.assertEqual(chart["y_field"], "orders")

        rendered = json.dumps(artifact, sort_keys=True)
        self.assertNotIn("ops.daily_orders", rendered)
        self.assertNotIn("secret_token", rendered)
        self.assertNotIn("sha256:", rendered)

    def test_run_service_rejects_unknown_report_audience(self) -> None:
        runtime = _build_runtime()

        with self.assertRaises(ValueError):
            run_service(runtime, question="GMV", parameters=RUN_PARAMS, audience="partner")

    def test_report_evidence_cards_are_derived_from_runtime_contracts(self) -> None:
        result = _build_result_for_classification(DataClassification.CONFIDENTIAL)
        evidence = result.evidence_chain
        query_plan = evidence.query_plan

        artifact = _build_user_result_artifact(result)
        cards = {card["card_id"]: card for card in artifact["report"]["evidence_cards"]}

        self.assertEqual(cards["metric_contract"]["metric_name"], "orders")
        self.assertEqual(cards["metric_contract"]["display_name"], "Orders")
        self.assertEqual(cards["metric_contract"]["owner"], "RevOps")
        self.assertEqual(cards["metric_contract"]["data_classification"], "confidential")
        self.assertEqual(cards["sql_safety"]["query_metric_name"], "orders")
        self.assertEqual(cards["sql_safety"]["checked_tables"], ["ops.daily_orders"])
        self.assertEqual(
            cards["sql_safety"]["bound_parameter_names"],
            ["limit", "secret_token", "start_date"],
        )
        self.assertEqual(cards["sql_safety"]["limit_value"], 7)
        self.assertEqual(cards["query_result"]["columns"], ["channel", "orders"])
        self.assertEqual(cards["query_result"]["preview_row_count"], 1)

        second_evidence = replace(
            evidence,
            query_plan=replace(
                evidence.query_plan,
                sql="SELECT channel, COUNT(*) AS orders FROM ops.other_orders LIMIT :limit",
            ),
        )
        second_artifact = _build_user_result_artifact(
            SimpleNamespace(
                evidence_chain=second_evidence,
                action_proposal=result.action_proposal,
                action_result={},
            )
        )
        second_cards = {
            card["card_id"]: card for card in second_artifact["report"]["evidence_cards"]
        }
        self.assertNotEqual(
            cards["sql_safety"]["sql_fingerprint"],
            second_cards["sql_safety"]["sql_fingerprint"],
        )

        rendered_cards = json.dumps(artifact["report"]["evidence_cards"], sort_keys=True)
        self.assertNotIn(query_plan.sql, rendered_cards)
        self.assertNotIn("do-not-leak", rendered_cards)

    def test_dashboard_chart_fields_are_derived_from_rows_and_metric_contract(self) -> None:
        runtime = ContentCommerceRuntimeFactory(
            RuntimeFactoryConfig(
                domain_pack_path=DOMAIN_PACK,
                sample_rows=(
                    {"campaign": "search", "gmv": 10.0},
                    {"campaign": "social", "gmv": 20.0},
                ),
            )
        ).build()

        summary = run_service(runtime, question="GMV", parameters=RUN_PARAMS)

        widgets = summary["user_result"]["dashboard"]["widgets"]
        chart = next(widget for widget in widgets if widget["type"] == "line_chart")
        self.assertEqual(chart["x_field"], "campaign")
        self.assertEqual(chart["y_field"], "gmv")
        self.assertEqual(
            chart["preview_rows"],
            [{"campaign": "search", "gmv": 10.0}, {"campaign": "social", "gmv": 20.0}],
        )
        kpi = next(widget for widget in widgets if widget["type"] == "kpi")
        self.assertEqual(kpi["value"], 10.0)

    def test_dashboard_does_not_fabricate_chart_without_numeric_measure(self) -> None:
        runtime = ContentCommerceRuntimeFactory(
            RuntimeFactoryConfig(
                domain_pack_path=DOMAIN_PACK,
                sample_rows=({"campaign": "search", "segment": "new"},),
            )
        ).build()

        summary = run_service(runtime, question="GMV", parameters=RUN_PARAMS)

        widget_types = {widget["type"] for widget in summary["user_result"]["dashboard"]["widgets"]}
        self.assertIn("kpi", widget_types)
        self.assertIn("table", widget_types)
        self.assertNotIn("line_chart", widget_types)

    def test_business_action_status_distinguishes_proposal_from_approval_wait(self) -> None:
        runtime = _build_runtime()

        proposal_summary = run_service(runtime, question="GMV", parameters=RUN_PARAMS)
        governed_action_summary = run_service(
            runtime, question="GMV 记录行动", parameters=RUN_PARAMS
        )

        proposal = proposal_summary["user_result"]["business_action"]
        self.assertEqual(proposal["connector_name"], "manual_review")
        self.assertEqual(proposal["action_type"], "propose")
        self.assertFalse(proposal["approval_required"])
        self.assertIsNone(proposal["approval_id"])
        self.assertEqual(proposal["status"], "proposed")

        governed_action = governed_action_summary["user_result"]["business_action"]
        self.assertEqual(governed_action["connector_name"], "action_record")
        self.assertEqual(governed_action["action_type"], "execute")
        self.assertTrue(governed_action["approval_required"])
        self.assertTrue(governed_action["approval_id"].startswith("approval-"))
        self.assertEqual(governed_action["status"], "awaiting_approval")

    def test_run_service_blocked_returns_structured_block(self) -> None:
        # 'revenue' parses to a metric the pack does not define -> UNKNOWN_METRIC.
        runtime = _build_runtime()
        summary = run_service(runtime, question="revenue", parameters=RUN_PARAMS)

        self.assertEqual(summary["status"], "blocked")
        self.assertNotIn("trace_id", summary)
        self.assertNotIn("user_result", summary)
        self.assertEqual(summary["block"]["code"], "unknown_metric")
        self.assertEqual(summary["block"]["stage"], "metric_resolution")


class ApprovalExecutionServiceTest(unittest.TestCase):
    def test_approve_and_execute_service_runs_approval_bound_action(self) -> None:
        runtime = _build_runtime()
        summary = run_service(runtime, question="GMV 记录行动", parameters=RUN_PARAMS)
        approval_id = summary["user_result"]["business_action"]["approval_id"]

        result = approve_and_execute_service(
            runtime,
            approval_id=approval_id,
            reason="approved by operator",
            approved_by="ops@example.com",
        )

        self.assertEqual(result["approval_id"], approval_id)
        self.assertEqual(result["approval_status"], "approved")
        self.assertEqual(result["approved_by"], "ops@example.com")
        self.assertEqual(result["state"], "executed")
        self.assertTrue(result["operation_trace_id"].startswith("optrace-"))
        self.assertEqual(
            result["operation_id"],
            summary["user_result"]["business_action"]["operation_id"],
        )
        self.assertIn("connector_executed", [event["step"] for event in result["events"]])

    def test_approve_and_execute_service_does_not_approve_without_pending_context(self) -> None:
        runtime = _build_runtime()
        runtime.approval_runtime.create_pending(
            approval_id="approval-orphan",
            proposal_id="proposal-orphan",
            approver_role="Business Owner",
            operation_fingerprint="digest-orphan",
        )

        with self.assertRaises(KeyError):
            approve_and_execute_service(
                runtime,
                approval_id="approval-orphan",
                reason="approved by operator",
                approved_by="ops@example.com",
            )

        self.assertEqual(runtime.approval_runtime.get("approval-orphan").status, "pending")

    def test_approve_and_execute_service_rejected_approval_stays_rejected(self) -> None:
        runtime = _build_runtime()
        summary = run_service(runtime, question="GMV 记录行动", parameters=RUN_PARAMS)
        approval_id = summary["user_result"]["business_action"]["approval_id"]
        runtime.approval_runtime.reject(approval_id, reason="not acceptable")

        with self.assertRaises(ValueError):
            approve_and_execute_service(
                runtime,
                approval_id=approval_id,
                reason="approved by operator",
                approved_by="ops@example.com",
            )

        self.assertEqual(runtime.approval_runtime.get(approval_id).status, "rejected")


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

    def test_correction_responses_project_used_knowledge_context_refs(self) -> None:
        factory = ContentCommerceRuntimeFactory(RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK))
        runtime = factory.build()
        first = run_service(runtime, question="GMV reusable context", parameters=RUN_PARAMS)
        first_asset_id = first["knowledge_asset_id"]
        knowledge_review_action_service(
            runtime,
            asset_id=first_asset_id,
            action="approve",
            reviewer="founder",
        )
        third = run_service(runtime, question="GMV reusable context", parameters=RUN_PARAMS)
        trace_id = third["trace_id"]
        self.assertEqual(
            third["user_result"]["decision"]["knowledge_context_refs"],
            [first_asset_id],
        )

        outcome = record_outcome_service(
            runtime,
            trace_id=trace_id,
            outcome="adopted",
            reviewer="ops@example.com",
        )
        adoption = attest_adoption_service(
            runtime,
            factory.adoption_ingest(),
            trace_id=trace_id,
            outcome="adopted",
            reviewer="ops@example.com",
        )

        self.assertEqual(outcome["knowledge_context_refs"], [first_asset_id])
        self.assertEqual(adoption["knowledge_context_refs"], [first_asset_id])
        self.assertEqual(outcome["knowledge_version"], 1)
        self.assertEqual(adoption["knowledge_version"], 2)


class KnowledgeReviewQueueServiceTest(unittest.TestCase):
    def test_lists_three_draft_candidates_without_mutating_store(self) -> None:
        runtime = _build_runtime()
        trace_ids = [
            run_service(
                runtime,
                question=f"GMV review candidate {index}",
                parameters={**RUN_PARAMS, "limit": 10 + index},
            )["trace_id"]
            for index in range(3)
        ]
        before_versions = {
            trace_id: runtime.knowledge_store.version_of(trace_id) for trace_id in trace_ids
        }

        result = knowledge_review_queue_service(runtime)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["review_state"], "draft")
        self.assertEqual(
            [item["source_trace_id"] for item in result["items"]],
            trace_ids,
        )
        self.assertEqual(
            {item["state"] for item in result["items"]},
            {"draft"},
        )
        self.assertTrue(all(item["asset_id"].startswith("knowledge-") for item in result["items"]))
        self.assertTrue(all(item["owner"] for item in result["items"]))
        self.assertEqual(
            {item["knowledge_version"] for item in result["items"]},
            {1},
        )
        self.assertEqual(len(runtime.knowledge_store.all_assets()), 3)
        self.assertEqual(
            {trace_id: runtime.knowledge_store.version_of(trace_id) for trace_id in trace_ids},
            before_versions,
        )


class KnowledgeReviewActionServiceTest(unittest.TestCase):
    def test_approve_marks_draft_asset_active_without_value_promotion(self) -> None:
        runtime = _build_runtime()
        run = run_service(runtime, question="GMV candidate to approve", parameters=RUN_PARAMS)
        trace_id = run["trace_id"]
        original = runtime.knowledge_store.get_by_trace(trace_id)
        self.assertIsNotNone(original)

        result = knowledge_review_action_service(
            runtime,
            asset_id=original.asset_id,
            action="approve",
            reviewer="founder",
            reason="safe enough for reuse",
        )

        stored = runtime.knowledge_store.get_by_trace(trace_id)
        self.assertIsNotNone(stored)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["action"], "approve")
        self.assertEqual(result["asset_id"], original.asset_id)
        self.assertEqual(result["source_trace_id"], trace_id)
        self.assertEqual(result["previous_state"], "draft")
        self.assertEqual(result["state"], "active")
        self.assertEqual(result["reviewer"], "founder")
        self.assertEqual(result["knowledge_version"], 2)
        self.assertEqual(stored.state, LifecycleState.ACTIVE)
        self.assertEqual(stored.result_weight, original.result_weight)
        self.assertEqual(stored.outcome, original.outcome)
        self.assertEqual(runtime.knowledge_store.version_of(trace_id), 2)

    def test_reject_marks_draft_asset_deprecated_and_removes_it_from_queue(self) -> None:
        runtime = _build_runtime()
        run = run_service(runtime, question="GMV candidate to reject", parameters=RUN_PARAMS)
        trace_id = run["trace_id"]
        original = runtime.knowledge_store.get_by_trace(trace_id)
        self.assertIsNotNone(original)

        result = knowledge_review_action_service(
            runtime,
            asset_id=original.asset_id,
            action="reject",
            reviewer="founder",
            reason="not reusable",
        )

        stored = runtime.knowledge_store.get_by_trace(trace_id)
        self.assertIsNotNone(stored)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["action"], "reject")
        self.assertEqual(result["previous_state"], "draft")
        self.assertEqual(result["state"], "deprecated")
        self.assertEqual(result["knowledge_version"], 2)
        self.assertEqual(stored.state, LifecycleState.DEPRECATED)
        self.assertEqual(stored.result_weight, original.result_weight)
        self.assertEqual(knowledge_review_queue_service(runtime)["count"], 0)

    def test_review_action_rejects_unknown_action(self) -> None:
        runtime = _build_runtime()
        run = run_service(runtime, question="GMV candidate", parameters=RUN_PARAMS)
        asset = runtime.knowledge_store.get_by_trace(run["trace_id"])
        self.assertIsNotNone(asset)

        with self.assertRaisesRegex(ValueError, "Unsupported knowledge review action"):
            knowledge_review_action_service(
                runtime,
                asset_id=asset.asset_id,
                action="publish",
                reviewer="founder",
                reason="too much authority",
            )

    def test_review_action_appends_safe_audit_event_to_run_trace(self) -> None:
        runtime = _build_runtime()
        run = run_service(runtime, question="GMV candidate to audit", parameters=RUN_PARAMS)
        trace_id = run["trace_id"]
        asset = runtime.knowledge_store.get_by_trace(trace_id)
        self.assertIsNotNone(asset)

        result = knowledge_review_action_service(
            runtime,
            asset_id=asset.asset_id,
            action="approve",
            reviewer="founder",
            reason="contains sensitive customer rationale",
        )

        stored_trace = runtime.trace_store.get(trace_id)
        self.assertIsNotNone(stored_trace)
        audit_events = [
            event for event in stored_trace.events if event.step == "knowledge_review_decision"
        ]
        self.assertEqual(len(audit_events), 1)
        payload = audit_events[0].payload
        self.assertEqual(payload["asset_id"], asset.asset_id)
        self.assertEqual(payload["action"], "approve")
        self.assertEqual(payload["previous_state"], "draft")
        self.assertEqual(payload["state"], "active")
        self.assertEqual(payload["reviewer"], "founder")
        self.assertEqual(payload["knowledge_version"], result["knowledge_version"])
        self.assertTrue(payload["reason_present"])
        self.assertNotIn("reason", payload)
        self.assertNotIn("sensitive customer rationale", str(payload))

    def test_review_action_fails_closed_when_source_trace_is_missing(self) -> None:
        class MissingTraceStore:
            def get(self, trace_id: str) -> None:
                del trace_id
                return None

            def save(self, run_trace: object) -> None:
                del run_trace
                raise AssertionError("review action must not save without a persisted trace")

        runtime = _build_runtime()
        run = run_service(
            runtime, question="GMV candidate with missing trace", parameters=RUN_PARAMS
        )
        trace_id = run["trace_id"]
        asset = runtime.knowledge_store.get_by_trace(trace_id)
        self.assertIsNotNone(asset)
        runtime.trace_store = MissingTraceStore()

        with self.assertRaisesRegex(RuntimeError, "source trace is not persisted"):
            knowledge_review_action_service(
                runtime,
                asset_id=asset.asset_id,
                action="approve",
                reviewer="founder",
                reason="must not mutate without audit",
            )

        stored = runtime.knowledge_store.get_by_trace(trace_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.state.value, "draft")
        self.assertEqual(runtime.knowledge_store.version_of(trace_id), 1)


class KnowledgeAssetCatalogServiceTest(unittest.TestCase):
    def test_catalog_lists_active_and_published_assets_without_mutating_store(self) -> None:
        runtime = _build_runtime()
        draft = run_service(runtime, question="GMV draft", parameters=RUN_PARAMS)
        active = run_service(runtime, question="GMV active", parameters=RUN_PARAMS)
        published = run_service(runtime, question="GMV published", parameters=RUN_PARAMS)
        deprecated = run_service(runtime, question="GMV deprecated", parameters=RUN_PARAMS)

        active_asset = runtime.knowledge_store.get_by_trace(active["trace_id"])
        published_asset = runtime.knowledge_store.get_by_trace(published["trace_id"])
        deprecated_asset = runtime.knowledge_store.get_by_trace(deprecated["trace_id"])
        self.assertIsNotNone(active_asset)
        self.assertIsNotNone(published_asset)
        self.assertIsNotNone(deprecated_asset)

        knowledge_review_action_service(
            runtime,
            asset_id=active_asset.asset_id,
            action="approve",
            reviewer="founder",
        )
        knowledge_review_action_service(
            runtime,
            asset_id=published_asset.asset_id,
            action="approve",
            reviewer="founder",
        )
        knowledge_publish_service(
            runtime,
            asset_id=published_asset.asset_id,
            reviewer="founder",
        )
        knowledge_review_action_service(
            runtime,
            asset_id=deprecated_asset.asset_id,
            action="reject",
            reviewer="founder",
        )
        before_versions = {
            trace_id: runtime.knowledge_store.version_of(trace_id)
            for trace_id in (
                draft["trace_id"],
                active["trace_id"],
                published["trace_id"],
                deprecated["trace_id"],
            )
        }

        self.assertTrue(
            hasattr(outcome_service, "knowledge_asset_catalog_service"),
            "knowledge_asset_catalog_service is required for the internal catalog surface",
        )
        default_catalog = outcome_service.knowledge_asset_catalog_service(runtime)

        self.assertEqual(default_catalog["status"], "ok")
        self.assertEqual(default_catalog["catalog_state"], "active,published")
        self.assertEqual(default_catalog["count"], 2)
        self.assertEqual(
            {item["state"] for item in default_catalog["items"]},
            {"active", "published"},
        )
        self.assertEqual(
            {item["source_trace_id"] for item in default_catalog["items"]},
            {active["trace_id"], published["trace_id"]},
        )
        self.assertEqual(
            {item["knowledge_version"] for item in default_catalog["items"]},
            {2, 3},
        )

        all_catalog = outcome_service.knowledge_asset_catalog_service(
            runtime, lifecycle_state="all"
        )
        self.assertEqual(all_catalog["count"], 4)
        self.assertEqual(
            {item["state"] for item in all_catalog["items"]},
            {"draft", "active", "published", "deprecated"},
        )
        self.assertEqual(
            {
                trace_id: runtime.knowledge_store.version_of(trace_id)
                for trace_id in before_versions
            },
            before_versions,
        )

    def test_catalog_rejects_unknown_lifecycle_filter(self) -> None:
        runtime = _build_runtime()

        with self.assertRaisesRegex(ValueError, "Unsupported KnowledgeAsset lifecycle filter"):
            self.assertTrue(
                hasattr(outcome_service, "knowledge_asset_catalog_service"),
                "knowledge_asset_catalog_service is required for the internal catalog surface",
            )
            outcome_service.knowledge_asset_catalog_service(runtime, lifecycle_state="external")


class KnowledgeAssetDetailServiceTest(unittest.TestCase):
    def test_returns_single_asset_detail_without_mutating_store(self) -> None:
        runtime = _build_runtime()
        run = run_service(runtime, question="GMV asset detail", parameters=RUN_PARAMS)
        trace_id = run["trace_id"]
        asset = runtime.knowledge_store.get_by_trace(trace_id)
        self.assertIsNotNone(asset)
        knowledge_review_action_service(
            runtime,
            asset_id=asset.asset_id,
            action="approve",
            reviewer="founder",
        )
        before_version = runtime.knowledge_store.version_of(trace_id)

        self.assertTrue(
            hasattr(outcome_service, "knowledge_asset_detail_service"),
            "knowledge_asset_detail_service is required for internal asset drill-down",
        )
        detail = outcome_service.knowledge_asset_detail_service(
            runtime,
            asset_id=asset.asset_id,
        )

        self.assertEqual(detail["status"], "ok")
        self.assertEqual(detail["asset_id"], asset.asset_id)
        self.assertEqual(detail["title"], asset.title)
        self.assertEqual(detail["asset_type"], asset.asset_type)
        self.assertEqual(detail["source_trace_id"], trace_id)
        self.assertEqual(detail["owner"], asset.owner)
        self.assertEqual(detail["state"], "active")
        self.assertEqual(detail["knowledge_version"], before_version)
        self.assertTrue(detail["has_source_trace"])
        self.assertNotIn("events", detail)
        self.assertNotIn("reason", detail)
        self.assertEqual(runtime.knowledge_store.version_of(trace_id), before_version)

    def test_unknown_asset_detail_raises_key_error(self) -> None:
        runtime = _build_runtime()

        self.assertTrue(
            hasattr(outcome_service, "knowledge_asset_detail_service"),
            "knowledge_asset_detail_service is required for internal asset drill-down",
        )
        with self.assertRaises(KeyError):
            outcome_service.knowledge_asset_detail_service(runtime, asset_id="knowledge-missing")


class KnowledgeAssetLifecycleEventsServiceTest(unittest.TestCase):
    def test_returns_safe_lifecycle_events_without_raw_reasons_or_mutation(self) -> None:
        runtime = _build_runtime()
        run = run_service(runtime, question="GMV lifecycle history", parameters=RUN_PARAMS)
        trace_id = run["trace_id"]
        asset = runtime.knowledge_store.get_by_trace(trace_id)
        self.assertIsNotNone(asset)
        knowledge_review_action_service(
            runtime,
            asset_id=asset.asset_id,
            action="approve",
            reviewer="founder",
            reason="contains sensitive review rationale",
        )
        knowledge_publish_service(
            runtime,
            asset_id=asset.asset_id,
            reviewer="founder",
            reason="contains sensitive publish rationale",
        )
        outcome_service.knowledge_deprecate_service(
            runtime,
            asset_id=asset.asset_id,
            reviewer="founder",
            reason="contains sensitive deprecate rationale",
        )
        before_version = runtime.knowledge_store.version_of(trace_id)

        self.assertTrue(
            hasattr(outcome_service, "knowledge_asset_lifecycle_events_service"),
            "knowledge_asset_lifecycle_events_service is required for internal audit drill-down",
        )
        result = outcome_service.knowledge_asset_lifecycle_events_service(
            runtime,
            asset_id=asset.asset_id,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["asset_id"], asset.asset_id)
        self.assertEqual(result["source_trace_id"], trace_id)
        self.assertTrue(result["has_source_trace"])
        self.assertEqual(result["count"], 3)
        self.assertEqual(
            [event["step"] for event in result["events"]],
            [
                "knowledge_review_decision",
                "knowledge_publish_decision",
                "knowledge_deprecate_decision",
            ],
        )
        self.assertEqual(
            [event["state"] for event in result["events"]],
            ["active", "published", "deprecated"],
        )
        self.assertEqual(
            [event["knowledge_version"] for event in result["events"]],
            [2, 3, 4],
        )
        for event in result["events"]:
            self.assertEqual(event["asset_id"], asset.asset_id)
            self.assertEqual(event["trace_id"], trace_id)
            self.assertEqual(event["reviewer"], "founder")
            self.assertTrue(event["reason_present"])
            self.assertNotIn("reason", event)
            self.assertNotIn("contains sensitive", str(event))
            self.assertLessEqual(
                set(event),
                {
                    "trace_id",
                    "step",
                    "asset_id",
                    "action",
                    "previous_state",
                    "state",
                    "reviewer",
                    "knowledge_version",
                    "reason_present",
                },
            )
        self.assertEqual(runtime.knowledge_store.version_of(trace_id), before_version)

    def test_unknown_asset_lifecycle_events_raise_key_error(self) -> None:
        runtime = _build_runtime()

        self.assertTrue(
            hasattr(outcome_service, "knowledge_asset_lifecycle_events_service"),
            "knowledge_asset_lifecycle_events_service is required for internal audit drill-down",
        )
        with self.assertRaises(KeyError):
            outcome_service.knowledge_asset_lifecycle_events_service(
                runtime,
                asset_id="knowledge-missing",
            )


class KnowledgeAssetUsageEventsServiceTest(unittest.TestCase):
    def test_returns_safe_usage_events_without_asset_content_or_mutation(self) -> None:
        runtime = _build_runtime()
        first = run_service(runtime, question="GMV usage history", parameters=RUN_PARAMS)
        source_trace_id = first["trace_id"]
        asset = runtime.knowledge_store.get_by_trace(source_trace_id)
        self.assertIsNotNone(asset)
        knowledge_review_action_service(
            runtime,
            asset_id=asset.asset_id,
            action="approve",
            reviewer="founder",
        )
        used = run_service(runtime, question="GMV usage history", parameters=RUN_PARAMS)
        usage_trace_id = used["trace_id"]
        stored_usage_trace = runtime.trace_store.get(usage_trace_id)
        self.assertIsNotNone(stored_usage_trace)
        runtime.trace_store.save(
            replace(
                stored_usage_trace,
                events=stored_usage_trace.events
                + (
                    outcome_service.TraceEvent(
                        trace_id=usage_trace_id,
                        step="agent_runtime.tool_succeeded",
                        payload={
                            "tool_name": "trusted_loop.record_outcome",
                            "knowledge_context_refs": [asset.asset_id],
                            "metric_deltas": {"secret_token": "do-not-leak"},
                        },
                    ),
                ),
            )
        )
        before_version = runtime.knowledge_store.version_of(source_trace_id)

        self.assertTrue(
            hasattr(outcome_service, "knowledge_asset_usage_events_service"),
            "knowledge_asset_usage_events_service is required for internal usage audit",
        )
        result = outcome_service.knowledge_asset_usage_events_service(
            runtime,
            asset_id=asset.asset_id,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["asset_id"], asset.asset_id)
        self.assertEqual(result["source_trace_id"], source_trace_id)
        self.assertEqual(result["count"], 2)
        self.assertEqual(
            [event["usage_kind"] for event in result["events"]],
            ["proposal_context", "correction_context"],
        )
        self.assertEqual(
            [event["step"] for event in result["events"]],
            ["action_proposal", "agent_runtime.tool_succeeded"],
        )
        for event in result["events"]:
            self.assertEqual(event["asset_id"], asset.asset_id)
            self.assertEqual(event["trace_id"], usage_trace_id)
            self.assertEqual(event["knowledge_context_refs"], [asset.asset_id])
            self.assertNotIn("title", event)
            self.assertNotIn("content", event)
            self.assertNotIn("related_knowledge", event)
            self.assertNotIn("metric_deltas", event)
            self.assertNotIn("secret_token", str(event))
            self.assertLessEqual(
                set(event),
                {
                    "trace_id",
                    "step",
                    "usage_kind",
                    "asset_id",
                    "knowledge_context_refs",
                    "tool_name",
                },
            )
        self.assertEqual(runtime.knowledge_store.version_of(source_trace_id), before_version)

    def test_unknown_asset_usage_events_raise_key_error(self) -> None:
        runtime = _build_runtime()

        self.assertTrue(
            hasattr(outcome_service, "knowledge_asset_usage_events_service"),
            "knowledge_asset_usage_events_service is required for internal usage audit",
        )
        with self.assertRaises(KeyError):
            outcome_service.knowledge_asset_usage_events_service(
                runtime,
                asset_id="knowledge-missing",
            )


class KnowledgeDeprecateServiceTest(unittest.TestCase):
    def test_deprecates_published_asset_without_value_promotion(self) -> None:
        runtime = _build_runtime()
        run = run_service(runtime, question="GMV asset to deprecate", parameters=RUN_PARAMS)
        trace_id = run["trace_id"]
        asset = runtime.knowledge_store.get_by_trace(trace_id)
        self.assertIsNotNone(asset)
        knowledge_review_action_service(
            runtime,
            asset_id=asset.asset_id,
            action="approve",
            reviewer="founder",
        )
        knowledge_publish_service(
            runtime,
            asset_id=asset.asset_id,
            reviewer="founder",
        )
        published = runtime.knowledge_store.get_by_trace(trace_id)
        self.assertIsNotNone(published)

        self.assertTrue(
            hasattr(outcome_service, "knowledge_deprecate_service"),
            "knowledge_deprecate_service is required for internal correction of reviewed assets",
        )
        result = outcome_service.knowledge_deprecate_service(
            runtime,
            asset_id=asset.asset_id,
            reviewer="founder",
            reason="superseded by stronger evidence",
        )

        stored = runtime.knowledge_store.get_by_trace(trace_id)
        self.assertIsNotNone(stored)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["asset_id"], asset.asset_id)
        self.assertEqual(result["action"], "deprecate")
        self.assertEqual(result["previous_state"], "published")
        self.assertEqual(result["state"], "deprecated")
        self.assertEqual(result["knowledge_version"], 4)
        self.assertEqual(stored.state, LifecycleState.DEPRECATED)
        self.assertEqual(stored.result_weight, published.result_weight)
        self.assertEqual(stored.outcome, published.outcome)
        self.assertEqual(
            outcome_service.knowledge_asset_catalog_service(runtime)["count"],
            0,
        )

        stored_trace = runtime.trace_store.get(trace_id)
        self.assertIsNotNone(stored_trace)
        deprecate_events = [
            event for event in stored_trace.events if event.step == "knowledge_deprecate_decision"
        ]
        self.assertEqual(len(deprecate_events), 1)
        payload = deprecate_events[0].payload
        self.assertEqual(payload["asset_id"], asset.asset_id)
        self.assertEqual(payload["previous_state"], "published")
        self.assertEqual(payload["state"], "deprecated")
        self.assertTrue(payload["reason_present"])
        self.assertNotIn("reason", payload)
        self.assertNotIn("superseded by stronger evidence", str(payload))

    def test_deprecate_rejects_draft_asset(self) -> None:
        runtime = _build_runtime()
        run = run_service(runtime, question="GMV draft cannot deprecate", parameters=RUN_PARAMS)
        asset = runtime.knowledge_store.get_by_trace(run["trace_id"])
        self.assertIsNotNone(asset)

        self.assertTrue(
            hasattr(outcome_service, "knowledge_deprecate_service"),
            "knowledge_deprecate_service is required for internal correction of reviewed assets",
        )
        with self.assertRaisesRegex(RuntimeError, "is not active or published"):
            outcome_service.knowledge_deprecate_service(
                runtime,
                asset_id=asset.asset_id,
                reviewer="founder",
                reason="must pass review first",
            )


if __name__ == "__main__":
    unittest.main()
