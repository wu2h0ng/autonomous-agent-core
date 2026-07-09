from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (
    ROOT / "packages" / "contracts" / "src",
    ROOT / "packages" / "os_core" / "src",
    ROOT / "packages" / "persistence" / "src",
    ROOT / "action_connectors",
    ROOT / "apps" / "api_server" / "src",
):
    sys.path.insert(0, str(_p))

_FASTAPI = importlib.util.find_spec("fastapi") is not None

SNAPSHOT = ROOT / "apps" / "api_server" / "openapi.json"


@unittest.skipUnless(_FASTAPI, "fastapi not installed (install .[http])")
class OpenApiContractTest(unittest.TestCase):
    """The committed OpenAPI snapshot is the API contract (AR-20260611).

    Any route/model/parameter/status-code change must regenerate the snapshot
    (`python -m agent_os_api.openapi_contract`), turning API changes into
    reviewable contract diffs. This test is the drift gate.
    """

    def test_snapshot_matches_live_schema(self) -> None:
        from agent_os_api.openapi_contract import generate_openapi_spec, render

        self.assertTrue(SNAPSHOT.exists(), f"missing API contract snapshot: {SNAPSHOT}")
        self.assertEqual(
            SNAPSHOT.read_text(encoding="utf-8"),
            render(generate_openapi_spec()),
            "OpenAPI contract drift: run `python -m agent_os_api.openapi_contract` "
            "and commit the regenerated apps/api_server/openapi.json",
        )

    def test_contract_covers_all_trigger_surfaces(self) -> None:
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        self.assertEqual(
            sorted(spec["paths"]),
            [
                "/adoptions",
                "/agent-runtime/runs/{runtime_run_id}/resume",
                "/approvals",
                "/approvals/{approval_id}",
                "/approvals/{approval_id}/execute",
                "/dashboards",
                "/dashboards/{dashboard_id}",
                "/health",
                "/knowledge/assets",
                "/knowledge/assets/quality-summary",
                "/knowledge/assets/{asset_id}",
                "/knowledge/assets/{asset_id}/decision-quality",
                "/knowledge/assets/{asset_id}/deprecate",
                "/knowledge/assets/{asset_id}/lifecycle-events",
                "/knowledge/assets/{asset_id}/publish",
                "/knowledge/assets/{asset_id}/usage-events",
                "/knowledge/review-queue",
                "/knowledge/review-queue/{asset_id}/decision",
                "/knowledge/search",
                "/mcp/servers",
                "/mcp/servers/{server_id}/tools",
                "/metrics",
                "/nl-build",
                "/nl-parse",
                "/outcomes",
                "/runs",
                "/runs/{trace_id}/report",
                "/tenants",
                "/tenants/{tenant_id}",
                "/tenants/{tenant_id}/auto-execution-policy",
                "/traces/{trace_id}",
                "/workflow-instances/{instance_id}",
                "/workflow-instances/{instance_id}/approve",
                "/workflow-instances/{instance_id}/delegate",
                "/workflow-instances/{instance_id}/reject",
                "/workflow-instances/{instance_id}/timeout-check",
                "/workflows",
                "/workflows/{workflow_id}/instances",
            ],
        )

    def test_knowledge_review_queue_contract_declares_quality_triage_fields(self) -> None:
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        queue = spec["paths"]["/knowledge/review-queue"]["get"]
        self.assertEqual(
            queue["responses"]["200"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/KnowledgeReviewQueueResponse"},
        )
        self.assertGreaterEqual(
            {param["name"] for param in queue["parameters"]},
            {
                "quality_status",
                "review_priority",
                "recommended_review_action",
                "review_rationale_code",
                "order_by",
                "limit",
                "offset",
            },
        )
        review_rationale_code_param = next(
            parameter
            for parameter in queue["parameters"]
            if parameter["in"] == "query" and parameter["name"] == "review_rationale_code"
        )
        order_by_param = next(
            parameter
            for parameter in queue["parameters"]
            if parameter["in"] == "query" and parameter["name"] == "order_by"
        )
        limit_param = next(
            parameter
            for parameter in queue["parameters"]
            if parameter["in"] == "query" and parameter["name"] == "limit"
        )
        offset_param = next(
            parameter
            for parameter in queue["parameters"]
            if parameter["in"] == "query" and parameter["name"] == "offset"
        )
        self.assertFalse(review_rationale_code_param["required"])
        self.assertEqual(
            review_rationale_code_param["schema"]["enum"],
            [
                "unused_context_candidate",
                "proposal_context_needs_outcome",
                "outcome_supported_context",
                "adoption_supported_context",
            ],
        )
        self.assertFalse(order_by_param["required"])
        self.assertEqual(
            order_by_param["schema"]["enum"],
            ["review_priority", "review_rationale_code"],
        )
        self.assertFalse(limit_param["required"])
        self.assertFalse(offset_param["required"])
        self.assertIn({"type": "integer"}, limit_param["schema"]["anyOf"])
        self.assertIn({"type": "integer"}, offset_param["schema"]["anyOf"])
        item_schema = spec["components"]["schemas"]["KnowledgeReviewQueueItem"]
        self.assertGreaterEqual(
            set(item_schema["required"]),
            {
                "asset_id",
                "state",
                "knowledge_version",
                "latest_usage_event",
                "proposal_usage_count",
                "correction_usage_count",
                "outcome_correction_count",
                "adoption_correction_count",
                "distinct_usage_trace_count",
                "quality_status",
                "review_priority",
                "recommended_review_action",
                "review_rationale_codes",
            },
        )
        response_schema = spec["components"]["schemas"]["KnowledgeReviewQueueResponse"]
        self.assertGreaterEqual(
            set(response_schema["required"]),
            {
                "quality_status_filter",
                "review_priority_filter",
                "recommended_review_action_filter",
                "review_rationale_code_filter",
                "order_by",
                "quality_status_counts",
                "review_priority_counts",
                "recommended_review_action_counts",
                "review_rationale_code_counts",
                "limit",
                "offset",
                "total_count",
                "has_more",
            },
        )
        self.assertEqual(
            item_schema["properties"]["latest_usage_event"]["anyOf"],
            [
                {"$ref": "#/components/schemas/KnowledgeAssetUsageEventSummary"},
                {"type": "null"},
            ],
        )
        self.assertEqual(
            item_schema["properties"]["quality_status"]["enum"],
            ["unused", "proposal_only", "outcome_observed", "adoption_observed"],
        )
        self.assertEqual(
            item_schema["properties"]["review_priority"]["enum"],
            ["high", "medium", "low"],
        )
        self.assertEqual(
            item_schema["properties"]["recommended_review_action"]["enum"],
            [
                "review_or_reject",
                "collect_outcome_feedback",
                "monitor_for_adoption",
                "consider_publish",
            ],
        )
        self.assertEqual(
            item_schema["properties"]["review_rationale_codes"]["items"]["enum"],
            [
                "unused_context_candidate",
                "proposal_context_needs_outcome",
                "outcome_supported_context",
                "adoption_supported_context",
            ],
        )
        self.assertEqual(
            response_schema["properties"]["review_rationale_code_counts"]["additionalProperties"],
            {"type": "integer"},
        )

    def test_knowledge_asset_detail_contract_declares_review_state(self) -> None:
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        detail = spec["paths"]["/knowledge/assets/{asset_id}"]["get"]
        self.assertEqual(
            detail["responses"]["200"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/KnowledgeAssetDetailResponse"},
        )
        response_schema = spec["components"]["schemas"]["KnowledgeAssetDetailResponse"]
        self.assertGreaterEqual(
            set(response_schema["required"]),
            {
                "status",
                "asset_id",
                "state",
                "knowledge_version",
                "has_source_trace",
                "lifecycle_event_count",
                "latest_lifecycle_event",
                "latest_usage_event",
                "proposal_usage_count",
                "correction_usage_count",
                "outcome_correction_count",
                "adoption_correction_count",
                "distinct_usage_trace_count",
                "quality_status",
                "review_priority",
                "recommended_review_action",
                "review_rationale_codes",
            },
        )
        self.assertEqual(
            response_schema["properties"]["lifecycle_event_count"]["type"],
            "integer",
        )
        latest_schema = response_schema["properties"]["latest_lifecycle_event"]
        self.assertEqual(
            latest_schema["anyOf"],
            [
                {"$ref": "#/components/schemas/KnowledgeAssetLifecycleEventSummary"},
                {"type": "null"},
            ],
        )
        usage_schema = response_schema["properties"]["latest_usage_event"]
        self.assertEqual(
            usage_schema["anyOf"],
            [
                {"$ref": "#/components/schemas/KnowledgeAssetUsageEventSummary"},
                {"type": "null"},
            ],
        )
        self.assertEqual(
            response_schema["properties"]["quality_status"]["enum"],
            ["unused", "proposal_only", "outcome_observed", "adoption_observed"],
        )
        self.assertEqual(
            response_schema["properties"]["review_priority"]["enum"],
            ["high", "medium", "low"],
        )
        self.assertEqual(
            response_schema["properties"]["recommended_review_action"]["enum"],
            [
                "review_or_reject",
                "collect_outcome_feedback",
                "monitor_for_adoption",
                "consider_publish",
            ],
        )
        self.assertEqual(
            response_schema["properties"]["review_rationale_codes"]["items"]["enum"],
            [
                "unused_context_candidate",
                "proposal_context_needs_outcome",
                "outcome_supported_context",
                "adoption_supported_context",
            ],
        )

    def test_knowledge_asset_catalog_item_contract_declares_review_state(self) -> None:
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        catalog = spec["paths"]["/knowledge/assets"]["get"]
        self.assertEqual(
            catalog["responses"]["200"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/KnowledgeAssetCatalogResponse"},
        )
        catalog_params = catalog["parameters"]
        quality_status_param = next(
            parameter
            for parameter in catalog_params
            if parameter["in"] == "query" and parameter["name"] == "quality_status"
        )
        review_priority_param = next(
            parameter
            for parameter in catalog_params
            if parameter["in"] == "query" and parameter["name"] == "review_priority"
        )
        recommended_review_action_param = next(
            parameter
            for parameter in catalog_params
            if parameter["in"] == "query" and parameter["name"] == "recommended_review_action"
        )
        review_rationale_code_param = next(
            parameter
            for parameter in catalog_params
            if parameter["in"] == "query" and parameter["name"] == "review_rationale_code"
        )
        order_by_param = next(
            parameter
            for parameter in catalog_params
            if parameter["in"] == "query" and parameter["name"] == "order_by"
        )
        limit_param = next(
            parameter
            for parameter in catalog_params
            if parameter["in"] == "query" and parameter["name"] == "limit"
        )
        offset_param = next(
            parameter
            for parameter in catalog_params
            if parameter["in"] == "query" and parameter["name"] == "offset"
        )
        self.assertFalse(quality_status_param["required"])
        self.assertFalse(review_priority_param["required"])
        self.assertFalse(recommended_review_action_param["required"])
        self.assertFalse(review_rationale_code_param["required"])
        self.assertFalse(order_by_param["required"])
        self.assertFalse(limit_param["required"])
        self.assertFalse(offset_param["required"])
        self.assertEqual(
            order_by_param["schema"]["enum"],
            [
                "quality_status",
                "recommended_review_action",
                "review_priority",
                "review_rationale_code",
            ],
        )
        self.assertIn({"type": "integer"}, limit_param["schema"]["anyOf"])
        self.assertIn({"type": "integer"}, offset_param["schema"]["anyOf"])
        self.assertEqual(
            quality_status_param["schema"]["enum"],
            ["unused", "proposal_only", "outcome_observed", "adoption_observed"],
        )
        self.assertEqual(review_priority_param["schema"]["enum"], ["high", "medium", "low"])
        self.assertEqual(
            recommended_review_action_param["schema"]["enum"],
            [
                "review_or_reject",
                "collect_outcome_feedback",
                "monitor_for_adoption",
                "consider_publish",
            ],
        )
        self.assertEqual(
            review_rationale_code_param["schema"]["enum"],
            [
                "unused_context_candidate",
                "proposal_context_needs_outcome",
                "outcome_supported_context",
                "adoption_supported_context",
            ],
        )
        item_schema = spec["components"]["schemas"]["KnowledgeAssetCatalogItem"]
        self.assertGreaterEqual(
            set(item_schema["required"]),
            {
                "asset_id",
                "state",
                "knowledge_version",
                "lifecycle_event_count",
                "latest_lifecycle_event",
                "latest_usage_event",
                "proposal_usage_count",
                "correction_usage_count",
                "outcome_correction_count",
                "adoption_correction_count",
                "distinct_usage_trace_count",
                "quality_status",
                "review_priority",
                "recommended_review_action",
                "review_rationale_codes",
                "latest_usage_event",
            },
        )
        self.assertEqual(
            item_schema["properties"]["latest_usage_event"]["anyOf"],
            [
                {"$ref": "#/components/schemas/KnowledgeAssetUsageEventSummary"},
                {"type": "null"},
            ],
        )
        self.assertEqual(
            item_schema["properties"]["lifecycle_event_count"]["type"],
            "integer",
        )
        self.assertEqual(
            item_schema["properties"]["latest_lifecycle_event"]["anyOf"],
            [
                {"$ref": "#/components/schemas/KnowledgeAssetLifecycleEventSummary"},
                {"type": "null"},
            ],
        )
        self.assertEqual(
            item_schema["properties"]["latest_usage_event"]["anyOf"],
            [
                {"$ref": "#/components/schemas/KnowledgeAssetUsageEventSummary"},
                {"type": "null"},
            ],
        )
        self.assertEqual(
            item_schema["properties"]["quality_status"]["enum"],
            ["unused", "proposal_only", "outcome_observed", "adoption_observed"],
        )
        self.assertEqual(
            item_schema["properties"]["review_priority"]["enum"],
            ["high", "medium", "low"],
        )
        self.assertEqual(
            item_schema["properties"]["recommended_review_action"]["enum"],
            [
                "review_or_reject",
                "collect_outcome_feedback",
                "monitor_for_adoption",
                "consider_publish",
            ],
        )
        self.assertEqual(
            item_schema["properties"]["review_rationale_codes"]["items"]["enum"],
            [
                "unused_context_candidate",
                "proposal_context_needs_outcome",
                "outcome_supported_context",
                "adoption_supported_context",
            ],
        )
        response_schema = spec["components"]["schemas"]["KnowledgeAssetCatalogResponse"]
        for field in ("order_by", "total_count", "has_more", "limit", "offset"):
            self.assertIn(field, response_schema["required"])
        self.assertIn(
            {
                "enum": [
                    "quality_status",
                    "recommended_review_action",
                    "review_priority",
                    "review_rationale_code",
                ],
                "type": "string",
            },
            response_schema["properties"]["order_by"]["anyOf"],
        )
        self.assertIn("quality_status_filter", response_schema["required"])
        self.assertIn(
            {
                "enum": ["unused", "proposal_only", "outcome_observed", "adoption_observed"],
                "type": "string",
            },
            response_schema["properties"]["quality_status_filter"]["anyOf"],
        )
        self.assertIn("quality_status_counts", response_schema["required"])
        self.assertEqual(
            response_schema["properties"]["quality_status_counts"]["additionalProperties"],
            {"type": "integer"},
        )
        self.assertIn("review_priority_counts", response_schema["required"])
        self.assertEqual(
            response_schema["properties"]["review_priority_counts"]["additionalProperties"],
            {"type": "integer"},
        )
        self.assertIn("recommended_review_action_counts", response_schema["required"])
        self.assertEqual(
            response_schema["properties"]["recommended_review_action_counts"][
                "additionalProperties"
            ],
            {"type": "integer"},
        )
        self.assertIn("review_rationale_code_counts", response_schema["required"])
        self.assertEqual(
            response_schema["properties"]["review_rationale_code_counts"]["additionalProperties"],
            {"type": "integer"},
        )

    def test_approval_execution_contract_is_declared(self) -> None:
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        approval_execute = spec["paths"]["/approvals/{approval_id}/execute"]["post"]
        rendered_route = json.dumps(approval_execute)
        self.assertIn("X-Operator-Key", rendered_route)
        self.assertNotIn("X-API-Key", rendered_route)
        operator_key = next(
            parameter
            for parameter in approval_execute["parameters"]
            if parameter["in"] == "header" and parameter["name"] == "X-Operator-Key"
        )
        self.assertIs(operator_key["required"], True)
        self.assertEqual(operator_key["schema"]["type"], "string")
        self.assertIn("404", approval_execute["responses"])
        self.assertIn("409", approval_execute["responses"])
        request_schema = spec["components"]["schemas"]["ApprovalExecuteRequest"]
        self.assertEqual(set(request_schema["required"]), {"reason", "approved_by"})
        response_schema = spec["components"]["schemas"]["ApprovalExecuteResponse"]
        self.assertIn("execution_audit", response_schema["properties"])
        self.assertEqual(
            response_schema["properties"]["execution_audit"],
            {"$ref": "#/components/schemas/ApprovalExecutionAudit"},
        )
        execution_audit_schema = spec["components"]["schemas"]["ApprovalExecutionAudit"]
        self.assertEqual(
            set(execution_audit_schema["properties"]),
            {
                "durability_scope",
                "execution_outcome",
                "replay_status",
                "external_ack_status",
                "ledger_status",
                "record_id",
                "external_request_id",
                "execution_certainty",
                "ack_status",
            },
        )
        self.assertEqual(
            set(response_schema["required"]),
            {
                "approval_id",
                "approval_status",
                "proposal_id",
                "operation_trace_id",
                "state",
                "evidence_chain_id",
            },
        )
        error_schema = spec["components"]["schemas"]["ApprovalExecuteErrorResponse"]
        self.assertEqual(set(error_schema["required"]), {"detail"})

    def test_approval_choice_set_contract_is_declared(self) -> None:
        """ADR-0014: the approval detail and decision projections expose the choice set."""
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        approval_detail = spec["paths"]["/approvals/{approval_id}"]["get"]
        self.assertEqual(
            approval_detail["responses"]["200"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/ApprovalDetailResponse"},
        )
        schemas = spec["components"]["schemas"]
        detail_schema = schemas["ApprovalDetailResponse"]
        self.assertIn("alternatives", detail_schema["properties"])
        self.assertIn("single_option_rationale", detail_schema["properties"])
        self.assertEqual(
            detail_schema["properties"]["alternatives"]["items"],
            {"$ref": "#/components/schemas/ActionAlternativeItem"},
        )

        alternative_schema = schemas["ActionAlternativeItem"]
        self.assertGreaterEqual(
            set(alternative_schema["properties"]),
            {"action", "rationale", "risk_level", "recommended"},
        )
        self.assertGreaterEqual(set(alternative_schema["required"]), {"action", "rationale"})

        decision_schema = schemas["UserResultDecision"]
        self.assertIn("alternatives", decision_schema["properties"])
        self.assertIn("single_option_rationale", decision_schema["properties"])
        self.assertEqual(
            decision_schema["properties"]["alternatives"]["items"],
            {"$ref": "#/components/schemas/ActionAlternativeItem"},
        )

    def test_adoption_contract_declares_causal_attribution_request_field(self) -> None:
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        adoption = spec["components"]["schemas"]["AdoptionRequest"]
        self.assertIn("causal_attribution", adoption["properties"])
        causal = spec["components"]["schemas"]["CausalAttributionRequest"]
        self.assertEqual(
            set(causal["required"]),
            {
                "metric_name",
                "observed_value",
                "counterfactual_value",
                "delta_absolute",
                "method",
                "comparison_ref",
                "window_start",
                "window_end",
                "confidence",
            },
        )

    def test_correction_responses_declare_knowledge_context_refs(self) -> None:
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        outcome_response = spec["components"]["schemas"]["OutcomeResponse"]
        adoption_response = spec["components"]["schemas"]["AdoptionResponse"]

        for response_schema in (outcome_response, adoption_response):
            self.assertIn("knowledge_context_refs", response_schema["properties"])
            self.assertIn("knowledge_context_rationale", response_schema["required"])
            self.assertIn("knowledge_context_rationale", response_schema["properties"])
            self.assertEqual(
                response_schema["properties"]["knowledge_context_refs"],
                {
                    "items": {"type": "string"},
                    "type": "array",
                    "title": "Knowledge Context Refs",
                },
            )
            self.assertEqual(
                response_schema["properties"]["knowledge_context_rationale"]["items"],
                {"$ref": "#/components/schemas/KnowledgeContextRationaleItem"},
            )

    def test_knowledge_asset_lifecycle_events_contract_is_declared(self) -> None:
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        lifecycle = spec["paths"]["/knowledge/assets/{asset_id}/lifecycle-events"]["get"]
        self.assertEqual(
            lifecycle["responses"]["200"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/KnowledgeAssetLifecycleEventsResponse"},
        )
        limit_param = next(
            parameter
            for parameter in lifecycle["parameters"]
            if parameter["in"] == "query" and parameter["name"] == "limit"
        )
        offset_param = next(
            parameter
            for parameter in lifecycle["parameters"]
            if parameter["in"] == "query" and parameter["name"] == "offset"
        )
        self.assertFalse(limit_param["required"])
        self.assertFalse(offset_param["required"])
        self.assertEqual(limit_param["schema"]["minimum"], 1)
        self.assertEqual(limit_param["schema"]["maximum"], 100)
        self.assertEqual(offset_param["schema"]["minimum"], 0)
        response_schema = spec["components"]["schemas"]["KnowledgeAssetLifecycleEventsResponse"]
        self.assertGreaterEqual(
            set(response_schema["required"]),
            {"status", "asset_id", "count", "total_count", "has_more", "limit", "offset"},
        )
        self.assertIn({"type": "integer"}, response_schema["properties"]["limit"]["anyOf"])
        self.assertEqual(response_schema["properties"]["offset"]["type"], "integer")
        self.assertEqual(
            response_schema["properties"]["source_trace_id"]["anyOf"],
            [{"type": "string"}, {"type": "null"}],
        )
        item_schema = spec["components"]["schemas"]["KnowledgeAssetLifecycleEvent"]
        self.assertEqual(
            set(item_schema["properties"]),
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

    def test_knowledge_asset_usage_events_contract_is_declared(self) -> None:
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        usage = spec["paths"]["/knowledge/assets/{asset_id}/usage-events"]["get"]
        self.assertEqual(
            usage["responses"]["200"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/KnowledgeAssetUsageEventsResponse"},
        )
        limit_param = next(
            parameter
            for parameter in usage["parameters"]
            if parameter["in"] == "query" and parameter["name"] == "limit"
        )
        offset_param = next(
            parameter
            for parameter in usage["parameters"]
            if parameter["in"] == "query" and parameter["name"] == "offset"
        )
        self.assertFalse(limit_param["required"])
        self.assertFalse(offset_param["required"])
        self.assertEqual(limit_param["schema"]["minimum"], 1)
        self.assertEqual(limit_param["schema"]["maximum"], 100)
        self.assertEqual(offset_param["schema"]["minimum"], 0)
        response_schema = spec["components"]["schemas"]["KnowledgeAssetUsageEventsResponse"]
        self.assertGreaterEqual(
            set(response_schema["required"]),
            {"status", "asset_id", "count", "total_count", "has_more", "limit", "offset"},
        )
        self.assertIn({"type": "integer"}, response_schema["properties"]["limit"]["anyOf"])
        self.assertEqual(response_schema["properties"]["offset"]["type"], "integer")
        self.assertEqual(
            response_schema["properties"]["source_trace_id"]["anyOf"],
            [{"type": "string"}, {"type": "null"}],
        )
        item_schema = spec["components"]["schemas"]["KnowledgeAssetUsageEventItem"]
        self.assertEqual(
            set(item_schema["properties"]),
            {
                "trace_id",
                "step",
                "usage_kind",
                "asset_id",
                "knowledge_context_refs",
                "knowledge_context_rationale",
                "tool_name",
            },
        )
        self.assertEqual(
            item_schema["properties"]["knowledge_context_rationale"]["items"],
            {"$ref": "#/components/schemas/KnowledgeContextRationaleItem"},
        )
        rendered_schema = json.dumps(item_schema)
        self.assertNotIn("related_knowledge", rendered_schema)
        self.assertNotIn("metric_deltas", rendered_schema)

    def test_knowledge_asset_quality_summary_contract_is_declared(self) -> None:
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        summary = spec["paths"]["/knowledge/assets/quality-summary"]["get"]
        quality_status_param = next(
            parameter
            for parameter in summary["parameters"]
            if parameter["in"] == "query" and parameter["name"] == "quality_status"
        )
        self.assertFalse(quality_status_param["required"])
        self.assertEqual(
            quality_status_param["schema"]["enum"],
            ["unused", "proposal_only", "outcome_observed", "adoption_observed"],
        )
        review_priority_param = next(
            parameter
            for parameter in summary["parameters"]
            if parameter["in"] == "query" and parameter["name"] == "review_priority"
        )
        recommended_action_param = next(
            parameter
            for parameter in summary["parameters"]
            if parameter["in"] == "query" and parameter["name"] == "recommended_review_action"
        )
        review_rationale_code_param = next(
            parameter
            for parameter in summary["parameters"]
            if parameter["in"] == "query" and parameter["name"] == "review_rationale_code"
        )
        order_by_param = next(
            parameter
            for parameter in summary["parameters"]
            if parameter["in"] == "query" and parameter["name"] == "order_by"
        )
        limit_param = next(
            parameter
            for parameter in summary["parameters"]
            if parameter["in"] == "query" and parameter["name"] == "limit"
        )
        offset_param = next(
            parameter
            for parameter in summary["parameters"]
            if parameter["in"] == "query" and parameter["name"] == "offset"
        )
        self.assertFalse(review_priority_param["required"])
        self.assertFalse(recommended_action_param["required"])
        self.assertFalse(review_rationale_code_param["required"])
        self.assertFalse(order_by_param["required"])
        self.assertFalse(limit_param["required"])
        self.assertFalse(offset_param["required"])
        self.assertEqual(review_priority_param["schema"]["enum"], ["high", "medium", "low"])
        self.assertEqual(
            recommended_action_param["schema"]["enum"],
            [
                "review_or_reject",
                "collect_outcome_feedback",
                "monitor_for_adoption",
                "consider_publish",
            ],
        )
        self.assertEqual(
            review_rationale_code_param["schema"]["enum"],
            [
                "unused_context_candidate",
                "proposal_context_needs_outcome",
                "outcome_supported_context",
                "adoption_supported_context",
            ],
        )
        self.assertEqual(order_by_param["schema"]["enum"], ["review_priority"])
        self.assertEqual(limit_param["schema"]["minimum"], 1)
        self.assertEqual(limit_param["schema"]["maximum"], 100)
        self.assertEqual(offset_param["schema"]["minimum"], 0)
        self.assertIn("400", summary["responses"])
        self.assertEqual(
            summary["responses"]["200"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/KnowledgeAssetQualitySummaryResponse"},
        )
        response_schema = spec["components"]["schemas"]["KnowledgeAssetQualitySummaryResponse"]
        self.assertGreaterEqual(
            set(response_schema["required"]),
            {
                "status",
                "count",
                "items",
                "quality_status_filter",
                "review_priority_filter",
                "recommended_review_action_filter",
                "review_rationale_code_filter",
                "order_by",
                "quality_status_counts",
                "review_priority_counts",
                "recommended_review_action_counts",
                "review_rationale_code_counts",
                "limit",
                "offset",
                "total_count",
                "has_more",
            },
        )
        self.assertEqual(
            response_schema["properties"]["quality_status_filter"]["anyOf"],
            [
                {
                    "enum": [
                        "unused",
                        "proposal_only",
                        "outcome_observed",
                        "adoption_observed",
                    ],
                    "type": "string",
                },
                {"type": "null"},
            ],
        )
        self.assertEqual(
            response_schema["properties"]["review_priority_filter"]["anyOf"],
            [
                {"enum": ["high", "medium", "low"], "type": "string"},
                {"type": "null"},
            ],
        )
        self.assertEqual(
            response_schema["properties"]["recommended_review_action_filter"]["anyOf"],
            [
                {
                    "enum": [
                        "review_or_reject",
                        "collect_outcome_feedback",
                        "monitor_for_adoption",
                        "consider_publish",
                    ],
                    "type": "string",
                },
                {"type": "null"},
            ],
        )
        self.assertEqual(
            response_schema["properties"]["review_rationale_code_filter"]["anyOf"],
            [
                {
                    "enum": [
                        "unused_context_candidate",
                        "proposal_context_needs_outcome",
                        "outcome_supported_context",
                        "adoption_supported_context",
                    ],
                    "type": "string",
                },
                {"type": "null"},
            ],
        )
        self.assertEqual(
            response_schema["properties"]["order_by"]["anyOf"],
            [
                {"const": "review_priority", "type": "string"},
                {"type": "null"},
            ],
        )
        self.assertEqual(
            response_schema["properties"]["quality_status_counts"]["additionalProperties"],
            {"type": "integer"},
        )
        self.assertEqual(
            response_schema["properties"]["review_priority_counts"]["additionalProperties"],
            {"type": "integer"},
        )
        self.assertEqual(
            response_schema["properties"]["recommended_review_action_counts"][
                "additionalProperties"
            ],
            {"type": "integer"},
        )
        self.assertEqual(
            response_schema["properties"]["review_rationale_code_counts"]["additionalProperties"],
            {"type": "integer"},
        )
        item_ref = response_schema["properties"]["items"]["items"]
        self.assertEqual(
            item_ref, {"$ref": "#/components/schemas/KnowledgeAssetQualitySummaryItem"}
        )
        item_schema = spec["components"]["schemas"]["KnowledgeAssetQualitySummaryItem"]
        self.assertEqual(
            set(item_schema["required"]),
            {
                "asset_id",
                "state",
                "lifecycle_event_count",
                "proposal_usage_count",
                "correction_usage_count",
                "outcome_correction_count",
                "adoption_correction_count",
                "distinct_usage_trace_count",
                "quality_status",
                "review_priority",
                "recommended_review_action",
                "review_rationale_codes",
                "latest_usage_event",
            },
        )
        self.assertEqual(
            item_schema["properties"]["latest_usage_event"]["anyOf"],
            [
                {"$ref": "#/components/schemas/KnowledgeAssetUsageEventSummary"},
                {"type": "null"},
            ],
        )
        self.assertEqual(
            item_schema["properties"]["lifecycle_event_count"]["type"],
            "integer",
        )
        self.assertEqual(
            item_schema["properties"]["review_rationale_codes"]["items"]["enum"],
            [
                "unused_context_candidate",
                "proposal_context_needs_outcome",
                "outcome_supported_context",
                "adoption_supported_context",
            ],
        )
        self.assertEqual(
            item_schema["properties"]["review_priority"]["enum"],
            ["high", "medium", "low"],
        )
        self.assertEqual(
            item_schema["properties"]["recommended_review_action"]["enum"],
            [
                "review_or_reject",
                "collect_outcome_feedback",
                "monitor_for_adoption",
                "consider_publish",
            ],
        )
        self.assertNotIn("title", item_schema["properties"])
        self.assertNotIn("content", item_schema["properties"])
        self.assertNotIn("related_knowledge", item_schema["properties"])
        self.assertNotIn("usage_trace_ids", item_schema["properties"])
        self.assertNotIn("metric_deltas", item_schema["properties"])

    def test_knowledge_asset_decision_quality_contract_is_declared(self) -> None:
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        quality = spec["paths"]["/knowledge/assets/{asset_id}/decision-quality"]["get"]
        self.assertEqual(
            quality["responses"]["200"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/KnowledgeAssetDecisionQualityResponse"},
        )
        response_schema = spec["components"]["schemas"]["KnowledgeAssetDecisionQualityResponse"]
        self.assertGreaterEqual(
            set(response_schema["required"]),
            {
                "status",
                "asset_id",
                "proposal_usage_count",
                "correction_usage_count",
                "outcome_correction_count",
                "adoption_correction_count",
                "distinct_usage_trace_count",
            },
        )
        self.assertEqual(
            response_schema["properties"]["usage_trace_ids"],
            {
                "items": {"type": "string"},
                "type": "array",
                "title": "Usage Trace Ids",
            },
        )
        rendered_schema = json.dumps(response_schema)
        self.assertNotIn("related_knowledge", rendered_schema)
        self.assertNotIn("metric_deltas", rendered_schema)

    def test_unified_block_contract_is_declared_on_runs(self) -> None:
        # AR-20260606-unified-block-outcome: the 422 business-block shape must be
        # part of the published schema, not folklore.
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        responses = spec["paths"]["/runs"]["post"]["responses"]
        self.assertIn("422", responses)
        block = spec["components"]["schemas"]["BlockDetail"]
        self.assertEqual(
            set(block["required"]) | set(block["properties"]),
            # trace_id: refusals reference their persisted RunTrace (AR-20260611).
            {"code", "message", "stage", "details", "trace_id"},
        )

    def test_agent_runtime_error_contract_is_declared_on_runs(self) -> None:
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        responses = spec["paths"]["/runs"]["post"]["responses"]
        self.assertIn("500", responses)
        self.assertEqual(
            responses["500"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/AgentRuntimeErrorResponse"},
        )
        detail = spec["components"]["schemas"]["AgentRuntimeErrorDetail"]
        self.assertEqual(
            set(detail["required"]),
            {"code", "message", "stage"},
        )
        self.assertIn("trace_id", detail["properties"])

    def test_agent_runtime_resume_contract_is_declared(self) -> None:
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        run_response = spec["components"]["schemas"]["RunResponse"]
        self.assertIn("runtime_checkpoint_ref", run_response["properties"])
        self.assertEqual(
            run_response["properties"]["runtime_checkpoint_ref"]["anyOf"][0],
            {"$ref": "#/components/schemas/RuntimeCheckpointRef"},
        )

        resume = spec["paths"]["/agent-runtime/runs/{runtime_run_id}/resume"]["post"]
        self.assertEqual(
            resume["requestBody"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/RuntimeResumeRequest"},
        )
        self.assertEqual(
            resume["responses"]["200"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/RuntimeResumeResponse"},
        )
        request_schema = spec["components"]["schemas"]["RuntimeResumeRequest"]
        self.assertEqual(set(request_schema["required"]), {"runtime_trace_id", "question"})
        response_schema = spec["components"]["schemas"]["RuntimeResumeResponse"]
        self.assertGreaterEqual(
            set(response_schema["required"]),
            {"runtime_run_id", "runtime_trace_id", "tool_name", "status", "resumed"},
        )
        for status_code in ("404", "409", "500", "503"):
            self.assertEqual(
                resume["responses"][status_code]["content"]["application/json"]["schema"],
                {"$ref": "#/components/schemas/RuntimeResumeErrorResponse"},
            )
        error_detail = spec["components"]["schemas"]["RuntimeResumeErrorDetail"]
        self.assertEqual(
            set(error_detail["required"]),
            {"code", "message", "stage", "runtime_run_id"},
        )
        self.assertIn("runtime_trace_id", error_detail["properties"])
        output_ref = spec["components"]["schemas"]["RuntimeResumeOutputRef"]
        self.assertNotIn("parameters", json.dumps(output_ref))
        self.assertNotIn("raw", json.dumps(output_ref).lower())

    def test_user_result_evidence_cards_are_strongly_typed(self) -> None:
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        run_request = spec["components"]["schemas"]["RunRequest"]
        self.assertEqual(run_request["properties"]["audience"]["default"], "internal")
        self.assertEqual(
            run_request["properties"]["audience"]["enum"],
            ["internal", "external"],
        )

        artifact = spec["components"]["schemas"]["UserResultArtifact"]
        self.assertIn("audience", artifact["required"])
        self.assertIn("redaction", artifact["required"])
        redaction = spec["components"]["schemas"]["UserResultRedaction"]
        self.assertGreaterEqual(
            set(redaction["required"]),
            {"audience", "applied", "data_classification", "redacted_fields"},
        )

        report = spec["components"]["schemas"]["UserResultReport"]
        self.assertIn("evidence_cards", report["required"])
        evidence_items = report["properties"]["evidence_cards"]["items"]
        self.assertEqual(evidence_items["discriminator"]["propertyName"], "type")
        self.assertEqual(len(evidence_items["oneOf"]), 3)

        schemas = spec["components"]["schemas"]
        decision = schemas["UserResultDecision"]
        self.assertIn("knowledge_context_rationale", decision["required"])
        self.assertEqual(
            decision["properties"]["knowledge_context_rationale"]["items"],
            {"$ref": "#/components/schemas/KnowledgeContextRationaleItem"},
        )
        rationale_item = schemas["KnowledgeContextRationaleItem"]
        self.assertEqual(
            set(rationale_item["required"]),
            {"asset_id", "score", "context_quality_boost", "reason_code"},
        )
        self.assertEqual(
            rationale_item["properties"]["reason_code"]["enum"],
            ["retrieved_reviewed_context", "prior_outcome_or_adoption_context"],
        )
        metric_card = schemas["MetricContractEvidenceCard"]
        self.assertGreaterEqual(
            set(metric_card["required"]),
            {
                "card_id",
                "type",
                "title",
                "evidence_chain_id",
                "trace_id",
                "derived_from",
                "metric_name",
                "metric_version",
                "display_name",
                "owner",
                "unit",
                "dimensions",
                "data_classification",
            },
        )
        sql_card = schemas["SQLSafetyEvidenceCard"]
        self.assertGreaterEqual(
            set(sql_card["required"]),
            {
                "card_id",
                "type",
                "title",
                "evidence_chain_id",
                "trace_id",
                "derived_from",
                "query_metric_name",
                "sql_safety_allowed",
                "checked_schemas",
                "checked_tables",
                "bound_parameter_names",
                "sql_fingerprint",
            },
        )
        query_card = schemas["QueryResultEvidenceCard"]
        self.assertGreaterEqual(
            set(query_card["required"]),
            {
                "card_id",
                "type",
                "title",
                "evidence_chain_id",
                "trace_id",
                "derived_from",
                "row_count",
                "columns",
                "preview_row_count",
            },
        )
        widget = spec["components"]["schemas"]["UserResultDashboardWidget"]
        self.assertIn("redacted_fields", widget["properties"])

    def test_check_mode_detects_drift(self) -> None:
        # Negative path: --check must exit 1 when the snapshot disagrees.
        import io
        from unittest import mock

        from agent_os_api import openapi_contract

        out = io.StringIO()
        self.assertEqual(openapi_contract.main(["--check"], stdout=out), 0)
        with mock.patch.object(
            openapi_contract, "generate_openapi_spec", return_value={"drifted": True}
        ):
            self.assertEqual(openapi_contract.main(["--check"], stdout=out), 1)
        self.assertIn("drift", out.getvalue())


if __name__ == "__main__":
    unittest.main()
