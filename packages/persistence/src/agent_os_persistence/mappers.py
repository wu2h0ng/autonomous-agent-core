"""Explicit (de)serialization between frozen contracts and JSON payloads.

Explicit mappers (not reflective magic) so schema evolution is visible and
round-trip-tested. Tuples/dicts on the frozen dataclasses round-trip through JSON
arrays/objects; enums are stored by value and reconstructed.
"""

from __future__ import annotations

from typing import Any

from agent_os_contracts import (
    BusinessIntent,
    CausalAttributionMethod,
    CausalOutcomeAttribution,
    DataClassification,
    EvidenceChain,
    FeedbackEvent,
    KnowledgeAsset,
    LifecycleState,
    MetricContract,
    OperationContract,
    QueryPlan,
    QueryResult,
    RunTrace,
    SQLSafetyIssue,
    SQLSafetyResult,
    StateSnapshot,
    TelemetryDimension,
    TelemetryEvent,
    TraceEvent,
)
from agent_os_core import ApprovalOperationContext, ApprovalRecord
from agent_os_core.agent_runtime import AgentToolCall, AgentToolResult, RunStateSnapshot


def feedback_to_payload(event: FeedbackEvent) -> dict[str, Any]:
    causal = event.causal_attribution
    return {
        "feedback_id": event.feedback_id,
        "trace_id": event.trace_id,
        "outcome": event.outcome,
        "metrics": dict(event.metrics),
        "reviewer": event.reviewer,
        "causal_attribution": (
            {
                "metric_name": causal.metric_name,
                "observed_value": causal.observed_value,
                "counterfactual_value": causal.counterfactual_value,
                "delta_absolute": causal.delta_absolute,
                "delta_percent": causal.delta_percent,
                "method": causal.method.value,
                "comparison_ref": causal.comparison_ref,
                "window_start": causal.window_start,
                "window_end": causal.window_end,
                "confidence": causal.confidence,
                "notes": causal.notes,
            }
            if causal is not None
            else None
        ),
    }


def feedback_from_payload(payload: dict[str, Any]) -> FeedbackEvent:
    causal = payload.get("causal_attribution")
    return FeedbackEvent(
        feedback_id=payload["feedback_id"],
        trace_id=payload["trace_id"],
        outcome=payload["outcome"],
        metrics=dict(payload.get("metrics") or {}),
        reviewer=payload.get("reviewer"),
        causal_attribution=(
            CausalOutcomeAttribution(
                metric_name=causal["metric_name"],
                observed_value=causal["observed_value"],
                counterfactual_value=causal["counterfactual_value"],
                delta_absolute=causal["delta_absolute"],
                delta_percent=causal.get("delta_percent"),
                method=CausalAttributionMethod(causal["method"]),
                comparison_ref=causal["comparison_ref"],
                window_start=causal["window_start"],
                window_end=causal["window_end"],
                confidence=causal["confidence"],
                notes=causal.get("notes"),
            )
            if causal is not None
            else None
        ),
    )


def knowledge_to_payload(asset: KnowledgeAsset) -> dict[str, Any]:
    return {
        "asset_id": asset.asset_id,
        "title": asset.title,
        "asset_type": asset.asset_type,
        "source_trace_id": asset.source_trace_id,
        "owner": asset.owner,
        "state": asset.state.value,
        "outcome": asset.outcome,
        "result_weight": asset.result_weight,
    }


def knowledge_from_payload(payload: dict[str, Any]) -> KnowledgeAsset:
    return KnowledgeAsset(
        asset_id=payload["asset_id"],
        title=payload["title"],
        asset_type=payload["asset_type"],
        source_trace_id=payload.get("source_trace_id"),
        owner=payload["owner"],
        state=LifecycleState(payload["state"]),
        outcome=payload.get("outcome"),
        result_weight=float(payload.get("result_weight") or 0.0),
    )


def snapshot_to_payload(snapshot: StateSnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "operation_id": snapshot.operation_id,
        "connector_name": snapshot.connector_name,
        "snapshot_type": snapshot.snapshot_type,
        "state_payload": dict(snapshot.state_payload),
        "created_at": snapshot.created_at,
        "metadata": dict(snapshot.metadata),
    }


def snapshot_from_payload(payload: dict[str, Any]) -> StateSnapshot:
    return StateSnapshot(
        snapshot_id=payload["snapshot_id"],
        operation_id=payload["operation_id"],
        connector_name=payload["connector_name"],
        snapshot_type=payload["snapshot_type"],
        state_payload=dict(payload.get("state_payload") or {}),
        created_at=payload["created_at"],
        metadata=dict(payload.get("metadata") or {}),
    )


def agent_tool_call_to_payload(call: AgentToolCall) -> dict[str, Any]:
    return {
        "call_id": call.call_id,
        "tool_name": call.tool_name,
        "args": dict(call.args),
        "context_ref": call.context_ref,
    }


def agent_tool_call_from_payload(payload: dict[str, Any]) -> AgentToolCall:
    return AgentToolCall(
        call_id=payload["call_id"],
        tool_name=payload["tool_name"],
        args=dict(payload.get("args") or {}),
        context_ref=payload.get("context_ref"),
    )


def agent_tool_result_to_payload(result: AgentToolResult) -> dict[str, Any]:
    return {
        "call_id": result.call_id,
        "tool_name": result.tool_name,
        "status": result.status,
        "output": result.output,
        "error_code": result.error_code,
        "error_message": result.error_message,
        "trace_id": result.trace_id,
        "metadata": dict(result.metadata),
    }


def agent_tool_result_from_payload(payload: dict[str, Any]) -> AgentToolResult:
    return AgentToolResult(
        call_id=payload["call_id"],
        tool_name=payload["tool_name"],
        status=payload["status"],
        output=payload.get("output"),
        error_code=payload.get("error_code"),
        error_message=payload.get("error_message"),
        trace_id=payload.get("trace_id", ""),
        metadata=dict(payload.get("metadata") or {}),
    )


def run_state_snapshot_to_payload(snapshot: RunStateSnapshot) -> dict[str, Any]:
    return {
        "run_id": snapshot.run_id,
        "trace_id": snapshot.trace_id,
        "step_id": snapshot.step_id,
        "status": snapshot.status,
        "pending_tool_call": (
            agent_tool_call_to_payload(snapshot.pending_tool_call)
            if snapshot.pending_tool_call is not None
            else None
        ),
        "last_result": (
            agent_tool_result_to_payload(snapshot.last_result)
            if snapshot.last_result is not None
            else None
        ),
        "metadata": dict(snapshot.metadata),
        "last_completed_boundary": snapshot.last_completed_boundary,
    }


def run_state_snapshot_from_payload(payload: dict[str, Any]) -> RunStateSnapshot:
    pending_tool_call = payload.get("pending_tool_call")
    last_result = payload.get("last_result")
    return RunStateSnapshot(
        run_id=payload["run_id"],
        trace_id=payload["trace_id"],
        step_id=payload["step_id"],
        status=payload["status"],
        pending_tool_call=(
            agent_tool_call_from_payload(pending_tool_call)
            if pending_tool_call is not None
            else None
        ),
        last_result=agent_tool_result_from_payload(last_result)
        if last_result is not None
        else None,
        metadata=dict(payload.get("metadata") or {}),
        last_completed_boundary=payload.get("last_completed_boundary"),
    )


def approval_to_payload(record: ApprovalRecord) -> dict[str, Any]:
    return {
        "approval_id": record.approval_id,
        "proposal_id": record.proposal_id,
        "status": record.status,
        "approver_role": record.approver_role,
        "reason": record.reason,
        "operation_fingerprint": record.operation_fingerprint,
        "approved_by": record.approved_by,
    }


def approval_from_payload(payload: dict[str, Any]) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id=payload["approval_id"],
        proposal_id=payload["proposal_id"],
        status=payload["status"],
        approver_role=payload.get("approver_role"),
        reason=payload.get("reason"),
        operation_fingerprint=payload.get("operation_fingerprint"),
        approved_by=payload.get("approved_by"),
    )


def operation_to_payload(operation: OperationContract) -> dict[str, Any]:
    return {
        "operation_id": operation.operation_id,
        "name": operation.name,
        "target_connector": operation.target_connector,
        "risk_level": operation.risk_level,
        "approval_required": operation.approval_required,
        "dry_run_required": operation.dry_run_required,
        "rollback_supported": operation.rollback_supported,
        "snapshot_required": operation.snapshot_required,
        "snapshot_id": operation.snapshot_id,
        "compensating_action": operation.compensating_action,
        "connector_name": operation.connector_name,
        "action_type": operation.action_type,
        "idempotency_key": operation.idempotency_key,
    }


def operation_from_payload(payload: dict[str, Any]) -> OperationContract:
    return OperationContract(
        operation_id=payload["operation_id"],
        name=payload["name"],
        target_connector=payload["target_connector"],
        risk_level=payload["risk_level"],
        approval_required=payload["approval_required"],
        dry_run_required=payload.get("dry_run_required", True),
        rollback_supported=payload.get("rollback_supported", False),
        snapshot_required=payload.get("snapshot_required", False),
        snapshot_id=payload.get("snapshot_id"),
        compensating_action=payload.get("compensating_action"),
        connector_name=payload.get("connector_name", "manual_review"),
        action_type=payload.get("action_type", "propose"),
        idempotency_key=payload.get("idempotency_key"),
    )


def evidence_to_payload(evidence: EvidenceChain) -> dict[str, Any]:
    return {
        "evidence_chain_id": evidence.evidence_chain_id,
        "intent": {
            "intent_id": evidence.intent.intent_id,
            "question": evidence.intent.question,
            "metric_name": evidence.intent.metric_name,
            "tenant_id": evidence.intent.tenant_id,
            "workspace_id": evidence.intent.workspace_id,
        },
        "metric_contract": {
            "metric_name": evidence.metric_contract.metric_name,
            "display_name": evidence.metric_contract.display_name,
            "definition": evidence.metric_contract.definition,
            "owner": evidence.metric_contract.owner,
            "unit": evidence.metric_contract.unit,
            "allowed_schemas": list(evidence.metric_contract.allowed_schemas),
            "version": evidence.metric_contract.version,
            "dimensions": list(evidence.metric_contract.dimensions),
            "data_classification": evidence.metric_contract.data_classification.value,
        },
        "query_plan": {
            "metric_name": evidence.query_plan.metric_name,
            "sql": evidence.query_plan.sql,
            "parameters": dict(evidence.query_plan.parameters),
        },
        "sql_safety": {
            "allowed": evidence.sql_safety.allowed,
            "reasons": list(evidence.sql_safety.reasons),
            "checked_schemas": list(evidence.sql_safety.checked_schemas),
            "checked_tables": list(evidence.sql_safety.checked_tables),
            "bound_parameters": list(evidence.sql_safety.bound_parameters),
            "limit_value": evidence.sql_safety.limit_value,
            "issues": [
                {
                    "code": issue.code,
                    "message": issue.message,
                    "severity": issue.severity,
                }
                for issue in evidence.sql_safety.issues
            ],
        },
        "query_result": {
            "rows": [dict(row) for row in evidence.query_result.rows],
            "row_count": evidence.query_result.row_count,
        },
        "conclusion": evidence.conclusion,
        "confidence": evidence.confidence,
        "limitations": list(evidence.limitations),
        "trace_id": evidence.trace_id,
    }


def evidence_from_payload(payload: dict[str, Any]) -> EvidenceChain:
    intent = payload["intent"]
    metric = payload["metric_contract"]
    query_plan = payload["query_plan"]
    sql_safety = payload["sql_safety"]
    query_result = payload["query_result"]
    return EvidenceChain(
        evidence_chain_id=payload["evidence_chain_id"],
        intent=BusinessIntent(
            intent_id=intent["intent_id"],
            question=intent["question"],
            metric_name=intent["metric_name"],
            tenant_id=intent.get("tenant_id", "default"),
            workspace_id=intent.get("workspace_id", "default"),
        ),
        metric_contract=MetricContract(
            metric_name=metric["metric_name"],
            display_name=metric["display_name"],
            definition=metric["definition"],
            owner=metric["owner"],
            unit=metric["unit"],
            allowed_schemas=tuple(metric.get("allowed_schemas") or ()),
            version=metric.get("version", "v1"),
            dimensions=tuple(metric.get("dimensions") or ()),
            data_classification=DataClassification(
                metric.get("data_classification", DataClassification.INTERNAL.value)
            ),
        ),
        query_plan=QueryPlan(
            metric_name=query_plan["metric_name"],
            sql=query_plan["sql"],
            parameters=dict(query_plan.get("parameters") or {}),
        ),
        sql_safety=SQLSafetyResult(
            allowed=sql_safety["allowed"],
            reasons=tuple(sql_safety.get("reasons") or ()),
            checked_schemas=tuple(sql_safety.get("checked_schemas") or ()),
            checked_tables=tuple(sql_safety.get("checked_tables") or ()),
            bound_parameters=tuple(sql_safety.get("bound_parameters") or ()),
            limit_value=sql_safety.get("limit_value"),
            issues=tuple(
                SQLSafetyIssue(
                    code=issue["code"],
                    message=issue["message"],
                    severity=issue.get("severity", "error"),
                )
                for issue in sql_safety.get("issues") or ()
            ),
        ),
        query_result=QueryResult(
            rows=tuple(dict(row) for row in query_result.get("rows") or ()),
            row_count=query_result["row_count"],
        ),
        conclusion=payload["conclusion"],
        confidence=payload["confidence"],
        limitations=tuple(payload.get("limitations") or ()),
        trace_id=payload["trace_id"],
    )


def approval_context_to_payload(context: ApprovalOperationContext) -> dict[str, Any]:
    return {
        "approval_id": context.approval_id,
        "proposal_id": context.proposal_id,
        "operation": operation_to_payload(context.operation),
        "action_parameters": dict(context.action_parameters),
        "evidence_chain": evidence_to_payload(context.evidence_chain),
    }


def approval_context_from_payload(payload: dict[str, Any]) -> ApprovalOperationContext:
    return ApprovalOperationContext(
        approval_id=payload["approval_id"],
        proposal_id=payload["proposal_id"],
        operation=operation_from_payload(payload["operation"]),
        action_parameters=dict(payload.get("action_parameters") or {}),
        evidence_chain=evidence_from_payload(payload["evidence_chain"]),
    )


def run_trace_to_payload(run_trace: RunTrace) -> dict[str, Any]:
    return {
        "trace_id": run_trace.trace_id,
        "status": run_trace.status,
        "events": [
            {"trace_id": e.trace_id, "step": e.step, "payload": e.payload} for e in run_trace.events
        ],
        "telemetry_events": [
            {
                "trace_id": t.trace_id,
                "dimension": t.dimension.value,
                "name": t.name,
                "value": t.value,
                "unit": t.unit,
                "attributes": t.attributes,
            }
            for t in run_trace.telemetry_events
        ],
    }


def run_trace_from_payload(payload: dict[str, Any]) -> RunTrace:
    return RunTrace(
        trace_id=payload["trace_id"],
        status=payload["status"],
        events=tuple(
            TraceEvent(trace_id=e["trace_id"], step=e["step"], payload=e["payload"])
            for e in payload["events"]
        ),
        telemetry_events=tuple(
            TelemetryEvent(
                trace_id=t["trace_id"],
                dimension=TelemetryDimension(t["dimension"]),
                name=t["name"],
                value=t["value"],
                unit=t["unit"],
                attributes=t.get("attributes", {}),
            )
            for t in payload.get("telemetry_events", [])
        ),
    )
