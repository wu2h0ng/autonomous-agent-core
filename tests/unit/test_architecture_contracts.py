from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))

from agent_os_contracts import (  # noqa: E402
    ConnectorExecutionAudit,
    DataProductCandidate,
    DataRequirement,
    FeedbackEvent,
    KnowledgeAsset,
    LineageSnapshot,
    OperationContract,
    OperationTrace,
    ProviderContract,
    ProviderKind,
    SemanticObject,
)


class ArchitectureContractsTest(unittest.TestCase):
    def test_product_shape_contracts_are_importable_and_stable(self) -> None:
        semantic_object = SemanticObject(
            object_id="metric.gmv",
            name="gmv",
            object_type="metric",
            owner="revenue_ops",
            description="Gross merchandise value.",
            aliases=("sales amount",),
        )
        provider = ProviderContract(
            provider_id="provider-sales",
            kind=ProviderKind.WAREHOUSE,
            name="sales warehouse",
            owner="data_platform",
            allowed_schemas=("sales",),
        )
        requirement = DataRequirement(
            requirement_id="req-1",
            intent_id="intent-1",
            metric_names=("gmv",),
            dimensions=("order_date",),
            time_window={"start_date": "2026-05-31", "end_date": "2026-06-01"},
        )
        lineage = LineageSnapshot(
            lineage_id="lineage-1",
            provider_id=provider.provider_id,
            source_objects=("sales.orders",),
            generated_by="unit_test",
            metadata={"query_hash": "abc123"},
        )
        candidate = DataProductCandidate(
            data_product_id="dp-1",
            name="gmv_daily",
            requirement_id=requirement.requirement_id,
            owner="revenue_ops",
            query_plan_id="gmv",
            lineage_snapshot_id=lineage.lineage_id,
        )
        operation = OperationContract(
            operation_id="op-1",
            name="approve_daily_report",
            target_connector="email",
            risk_level="R2",
            approval_required=False,
        )
        trace = OperationTrace(
            trace_id="trace-1",
            proposal_id="proposal-1",
            operation_id=operation.operation_id,
            state="proposed",
            evidence_chain_id="evidence-1",
            events=({"step": "proposed"},),
        )
        feedback = FeedbackEvent(
            feedback_id="fb-1",
            trace_id=trace.trace_id,
            outcome="useful",
            reviewer="analyst",
        )
        asset = KnowledgeAsset(
            asset_id="ka-1",
            title="GMV口径",
            asset_type="metric_definition",
            source_trace_id=trace.trace_id,
            owner="revenue_ops",
        )

        self.assertEqual(lineage.provider_id, "provider-sales")
        self.assertEqual(semantic_object.name, "gmv")
        self.assertEqual(candidate.lineage_snapshot_id, "lineage-1")
        self.assertEqual(trace.events[0]["step"], "proposed")
        self.assertEqual(feedback.trace_id, "trace-1")
        self.assertEqual(asset.source_trace_id, "trace-1")

    def test_connector_execution_audit_projects_safe_external_connector_fields(self) -> None:
        audit = ConnectorExecutionAudit.from_event(
            {
                "status": "accepted",
                "durability_scope": "external_connector",
                "external_request_id": "ext-req-1",
                "replay_status": "not_replayed",
                "ledger_status": "connector_reported",
                "secret_token": "must-not-leak",
                "raw_parameters": {"customer_id": "cust-1"},
            }
        )

        self.assertEqual(audit.execution_outcome, "accepted")
        self.assertEqual(audit.durability_scope, "external_connector")
        self.assertEqual(audit.external_request_id, "ext-req-1")
        self.assertEqual(audit.external_ack_status, "unknown")
        self.assertEqual(audit.replay_status, "not_replayed")
        self.assertEqual(audit.ledger_status, "connector_reported")
        self.assertIsNone(audit.record_id)
        self.assertEqual(
            audit.to_dict(),
            {
                "durability_scope": "external_connector",
                "execution_outcome": "accepted",
                "replay_status": "not_replayed",
                "external_ack_status": "unknown",
                "ledger_status": "connector_reported",
                "record_id": None,
                "external_request_id": "ext-req-1",
                "execution_certainty": None,
                "ack_status": None,
            },
        )
        self.assertNotIn("secret_token", audit.to_dict())
        self.assertNotIn("raw_parameters", audit.to_dict())


if __name__ == "__main__":
    unittest.main()
