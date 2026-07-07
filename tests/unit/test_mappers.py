"""Direct round-trip tests for the persistence (de)serialization mappers.

``test_repositories`` exercises the stores (and thus the mappers) indirectly.
This module tests the mapper contract directly so contract-field drift is
caught at the serialization boundary, and asserts payloads are JSON-storable
(they are persisted in JSON columns on SQLite and PostgreSQL).
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for seg in ("packages/contracts/src", "packages/os_core/src", "packages/persistence/src"):
    sys.path.insert(0, str(ROOT / seg))

from agent_os_contracts import (  # noqa: E402
    BusinessIntent,
    EvidenceChain,
    FeedbackEvent,
    KnowledgeAsset,
    LifecycleState,
    MetricContract,
    OperationContract,
    PolicyApprovalRecord,
    QueryPlan,
    QueryResult,
    RunTrace,
    SQLSafetyResult,
    StateSnapshot,
    TelemetryDimension,
    TelemetryEvent,
    TraceEvent,
)
from agent_os_core import ApprovalOperationContext  # noqa: E402
from agent_os_core.agent_runtime import AgentToolCall, AgentToolResult, RunStateSnapshot  # noqa: E402
from agent_os_persistence import mappers  # noqa: E402


def _round_trip(to_payload, from_payload, obj):
    payload = to_payload(obj)
    # Must be JSON-storable in a JSON column.
    json.loads(json.dumps(payload))
    return from_payload(payload)


class MapperRoundTripTest(unittest.TestCase):
    def test_feedback_round_trip(self) -> None:
        event = FeedbackEvent(
            feedback_id="fb-1",
            trace_id="trace-1",
            outcome="adopted",
            metrics={"gmv": 1200.0},
            reviewer="ops@example.com",
        )
        self.assertEqual(
            _round_trip(mappers.feedback_to_payload, mappers.feedback_from_payload, event), event
        )

    def test_knowledge_round_trip(self) -> None:
        asset = KnowledgeAsset(
            asset_id="ka-1",
            title="[gmv] last 7 days",
            asset_type="decision_loop",
            source_trace_id="trace-1",
            owner="revenue_ops",
            state=LifecycleState.DRAFT,
        )
        self.assertEqual(
            _round_trip(mappers.knowledge_to_payload, mappers.knowledge_from_payload, asset), asset
        )

    def test_snapshot_round_trip(self) -> None:
        snap = StateSnapshot(
            snapshot_id="snap-1",
            operation_id="op-1",
            connector_name="action_record",
            snapshot_type="full",
            state_payload={"records": [1, 2, 3]},
            created_at="2026-06-06T00:00:00Z",
            metadata={"note": "pre-exec"},
        )
        self.assertEqual(
            _round_trip(mappers.snapshot_to_payload, mappers.snapshot_from_payload, snap), snap
        )

    def test_operation_round_trip(self) -> None:
        op = OperationContract(
            operation_id="op-1",
            name="operation_for_gmv",
            target_connector="action_record",
            risk_level="R3",
            approval_required=True,
            rollback_supported=True,
            snapshot_required=True,
            connector_name="action_record",
            action_type="execute",
            idempotency_key="idem-1",
        )
        self.assertEqual(
            _round_trip(mappers.operation_to_payload, mappers.operation_from_payload, op), op
        )

    def test_evidence_round_trip(self) -> None:
        metric = MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="Gross merchandise value.",
            owner="revenue_ops",
            unit="CNY",
            allowed_schemas=("sales",),
        )
        evidence = EvidenceChain(
            evidence_chain_id="evidence-1",
            intent=BusinessIntent(
                intent_id="intent-1",
                question="GMV 是多少",
                metric_name="gmv",
            ),
            metric_contract=metric,
            query_plan=QueryPlan(
                metric_name="gmv",
                sql="select sum(paid_amount) as gmv from sales.orders limit :limit",
                parameters={"limit": 100},
            ),
            sql_safety=SQLSafetyResult(
                allowed=True,
                reasons=(),
                checked_schemas=("sales",),
                checked_tables=("sales.orders",),
                bound_parameters=("limit",),
                limit_value=100,
            ),
            query_result=QueryResult(rows=({"gmv": 128800.0},), row_count=1),
            conclusion="GMV is 128800.0.",
            confidence=0.9,
            limitations=(),
            trace_id="trace-1",
        )
        self.assertEqual(
            _round_trip(mappers.evidence_to_payload, mappers.evidence_from_payload, evidence),
            evidence,
        )

    def test_run_trace_round_trip_with_telemetry(self) -> None:
        run_trace = RunTrace(
            trace_id="trace-1",
            status="ok",
            events=(TraceEvent(trace_id="trace-1", step="intent.parsed", payload={"q": "gmv"}),),
            telemetry_events=(
                TelemetryEvent(
                    trace_id="trace-1",
                    dimension=TelemetryDimension.COST,
                    name="loop.duration_ms",
                    value=42.0,
                    unit="ms",
                    attributes={"phase": "loop"},
                ),
            ),
        )
        self.assertEqual(
            _round_trip(mappers.run_trace_to_payload, mappers.run_trace_from_payload, run_trace),
            run_trace,
        )

    def test_agent_tool_call_and_result_round_trip(self) -> None:
        call = AgentToolCall(
            call_id="call-1",
            tool_name="safe.echo",
            args={"msg": "hi"},
            context_ref="ctx-1",
        )
        self.assertEqual(
            _round_trip(
                mappers.agent_tool_call_to_payload, mappers.agent_tool_call_from_payload, call
            ),
            call,
        )
        result = AgentToolResult(
            call_id="call-1",
            tool_name="safe.echo",
            status="ok",
            output={"value": "ok"},
            trace_id="trace-1",
            metadata={"result_class": "safe"},
        )
        self.assertEqual(
            _round_trip(
                mappers.agent_tool_result_to_payload, mappers.agent_tool_result_from_payload, result
            ),
            result,
        )

    def test_run_state_snapshot_round_trip(self) -> None:
        snap = RunStateSnapshot(
            run_id="run-1",
            trace_id="trace-1",
            step_id="call-1",
            status="ok",
            pending_tool_call=None,
            last_result=AgentToolResult(
                call_id="call-1",
                tool_name="safe.echo",
                status="ok",
                output={"value": "ok"},
                trace_id="trace-1",
                metadata={"result_class": "safe"},
            ),
            metadata={"tool_name": "safe.echo"},
            last_completed_boundary="agent_runtime.invoke_tool",
        )
        self.assertEqual(
            _round_trip(
                mappers.run_state_snapshot_to_payload, mappers.run_state_snapshot_from_payload, snap
            ),
            snap,
        )

    def test_approval_context_round_trip(self) -> None:
        metric = MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="Gross merchandise value.",
            owner="revenue_ops",
            unit="CNY",
            allowed_schemas=("sales",),
        )
        evidence = EvidenceChain(
            evidence_chain_id="evidence-1",
            intent=BusinessIntent(intent_id="intent-1", question="GMV", metric_name="gmv"),
            metric_contract=metric,
            query_plan=QueryPlan(metric_name="gmv", sql="select 1", parameters={}),
            sql_safety=SQLSafetyResult(
                allowed=True,
                reasons=(),
                checked_schemas=("sales",),
                checked_tables=(),
                bound_parameters=(),
                limit_value=None,
            ),
            query_result=QueryResult(rows=({"gmv": 1.0},), row_count=1),
            conclusion="ok",
            confidence=0.9,
            limitations=(),
            trace_id="trace-1",
        )
        operation = OperationContract(
            operation_id="op-1",
            name="operation_for_gmv",
            target_connector="action_record",
            risk_level="R3",
            approval_required=True,
            rollback_supported=True,
            snapshot_required=True,
            connector_name="action_record",
            action_type="execute",
            idempotency_key="idem-1",
        )
        ctx = ApprovalOperationContext(
            approval_id="approval-1",
            proposal_id="proposal-1",
            operation=operation,
            action_parameters={"amount": 100},
            evidence_chain=evidence,
        )
        self.assertEqual(
            _round_trip(
                mappers.approval_context_to_payload, mappers.approval_context_from_payload, ctx
            ),
            ctx,
        )

    def test_policy_approval_round_trip_and_status_default(self) -> None:
        active = PolicyApprovalRecord(
            record_id="par-1",
            trace_id="trace-1",
            proposal_id="proposal-1",
            rule_id="rule-1",
            policy_version="v1",
            tenant_id="tenant-1",
            created_at="2026-07-07T00:00:00+00:00",
        )
        # revoked_at defaults to None; status defaults to "active" when absent.
        self.assertIsNone(active.revoked_at)
        self.assertEqual(active.status, "active")
        self.assertEqual(
            _round_trip(
                mappers.policy_approval_to_payload, mappers.policy_approval_from_payload, active
            ),
            active,
        )
        # A revoked record survives the round trip (non-None revoked_at, non-default status).
        revoked = active.revoke("2026-07-07T01:00:00+00:00")
        self.assertEqual(revoked.status, "revoked")
        self.assertEqual(
            _round_trip(
                mappers.policy_approval_to_payload, mappers.policy_approval_from_payload, revoked
            ),
            revoked,
        )
        # Missing status key reconstructs the "active" default (old rows / partial payloads).
        payload = mappers.policy_approval_to_payload(active)
        payload.pop("status")
        self.assertEqual(mappers.policy_approval_from_payload(payload).status, "active")


if __name__ == "__main__":
    unittest.main()
