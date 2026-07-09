"""Explicit (de)serialization between frozen contracts and JSON payloads.

Explicit mappers (not reflective magic) so schema evolution is visible and
round-trip-tested. Tuples/dicts on the frozen dataclasses round-trip through JSON
arrays/objects; enums are stored by value and reconstructed.
"""

from __future__ import annotations

from typing import Any

from agent_os_contracts import (
    ActionAlternative,
    BusinessIntent,
    CausalAttributionMethod,
    CausalOutcomeAttribution,
    ApprovalWorkflow,
    AutoExecutionPolicy,
    DataClassification,
    EvidenceChain,
    FeedbackEvent,
    KnowledgeAsset,
    LifecycleState,
    MetricContract,
    OperationContract,
    PolicyApprovalRecord,
    QueryPlan,
    QueryResult,
    RiskLevel,
    RunTrace,
    SQLSafetyIssue,
    SQLSafetyResult,
    StateSnapshot,
    TelemetryDimension,
    WorkflowInstance,
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
        "output": _agent_tool_output_to_payload(result.output),
        "error_code": result.error_code,
        "error_message": result.error_message,
        "trace_id": result.trace_id,
        "metadata": dict(result.metadata),
    }


def _agent_tool_output_to_payload(output: Any) -> Any:
    """Persist only JSON-safe Agent Runtime checkpoint output.

    Most tool outputs are already primitive JSON-like payloads and round-trip
    unchanged. TrustedLoop objects carry rich business/evidence structures, so
    checkpoints persist an allowlisted summary instead of raw contracts or
    connector payloads.
    """
    if output is None or isinstance(output, str | int | float | bool):
        return output
    if isinstance(output, dict):
        return {str(key): _agent_tool_output_to_payload(value) for key, value in output.items()}
    if isinstance(output, tuple | list):
        return [_agent_tool_output_to_payload(value) for value in output]
    if output.__class__.__name__ == "TrustedLoopOutcome":
        return _trusted_loop_outcome_to_payload(output)
    return {"type": output.__class__.__name__, "omitted": True}


def _trusted_loop_outcome_to_payload(outcome: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": "TrustedLoopOutcome", "status": outcome.status}
    result = getattr(outcome, "result", None)
    if result is not None:
        evidence = result.evidence_chain
        proposal = result.action_proposal
        payload["result"] = {
            "trace_id": evidence.trace_id,
            "evidence_chain_id": evidence.evidence_chain_id,
            "intent_metric_name": result.intent.metric_name,
            "query_metric_name": result.query_plan.metric_name,
            "row_count": evidence.query_result.row_count,
            "action_proposal_id": proposal.proposal_id,
            "approval_required": proposal.approval_required,
            "approval_id": (
                getattr(result.approval_record, "approval_id", None)
                if result.approval_record is not None
                else None
            ),
        }
    block = getattr(outcome, "block", None)
    if block is not None:
        payload["block"] = {
            "code": block.code.value,
            "stage": block.stage,
            "trace_id": block.trace_id,
        }
    return payload


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
        # ADR-0014: durable choice-set snapshot for the approval detail surface.
        "alternatives": [
            {
                "action": alternative.action,
                "rationale": alternative.rationale,
                "risk_level": (
                    alternative.risk_level.value if alternative.risk_level is not None else None
                ),
                "recommended": alternative.recommended,
            }
            for alternative in context.alternatives
        ],
        "single_option_rationale": context.single_option_rationale,
    }


def approval_context_from_payload(payload: dict[str, Any]) -> ApprovalOperationContext:
    return ApprovalOperationContext(
        approval_id=payload["approval_id"],
        proposal_id=payload["proposal_id"],
        operation=operation_from_payload(payload["operation"]),
        action_parameters=dict(payload.get("action_parameters") or {}),
        evidence_chain=evidence_from_payload(payload["evidence_chain"]),
        # Legacy payloads (pre ADR-0014) reconstruct the empty defaults.
        alternatives=tuple(
            ActionAlternative(
                action=alternative["action"],
                rationale=alternative["rationale"],
                risk_level=(
                    RiskLevel(alternative["risk_level"]) if alternative.get("risk_level") else None
                ),
                recommended=bool(alternative.get("recommended", False)),
            )
            for alternative in payload.get("alternatives") or ()
        ),
        single_option_rationale=payload.get("single_option_rationale"),
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


def policy_approval_to_payload(record: PolicyApprovalRecord) -> dict[str, Any]:
    """Serialize a ``PolicyApprovalRecord`` for JSON column storage."""
    return {
        "record_id": record.record_id,
        "trace_id": record.trace_id,
        "proposal_id": record.proposal_id,
        "rule_id": record.rule_id,
        "policy_version": record.policy_version,
        "tenant_id": record.tenant_id,
        "created_at": record.created_at,
        "revoked_at": record.revoked_at,
        "status": record.status,
    }


def policy_approval_from_payload(payload: dict[str, Any]) -> PolicyApprovalRecord:
    """Deserialize a ``PolicyApprovalRecord`` from a JSON column payload."""
    return PolicyApprovalRecord(
        record_id=payload["record_id"],
        trace_id=payload["trace_id"],
        proposal_id=payload["proposal_id"],
        rule_id=payload["rule_id"],
        policy_version=payload["policy_version"],
        tenant_id=payload["tenant_id"],
        created_at=payload["created_at"],
        revoked_at=payload.get("revoked_at"),
        status=payload.get("status", "active"),
    )


def approval_workflow_to_payload(workflow: ApprovalWorkflow) -> dict[str, Any]:
    return {
        "workflow_id": workflow.workflow_id,
        "name": workflow.name,
        "action_type": workflow.action_type,
        "risk_levels": list(workflow.risk_levels),
        "state": workflow.state,
        "steps": [
            {
                "step_id": s.step_id,
                "step_type": s.step_type,
                "approver_role": s.approver_role,
                "timeout_seconds": s.timeout_seconds,
                "next_step_id": s.next_step_id,
                "fallback_step_id": s.fallback_step_id,
            }
            for s in workflow.steps
        ],
    }


def approval_workflow_from_payload(payload: dict[str, Any]) -> ApprovalWorkflow:
    from agent_os_contracts import ApprovalWorkflow, WorkflowStep

    return ApprovalWorkflow(
        workflow_id=payload["workflow_id"],
        name=payload["name"],
        action_type=payload["action_type"],
        risk_levels=tuple(payload["risk_levels"]),
        steps=tuple(WorkflowStep(**step) for step in payload["steps"]),
        state=payload.get("state", "draft"),
    )


def workflow_instance_record_to_payload(
    *,
    tenant_id: str,
    instance: WorkflowInstance,
    assigned_role: str = "",
    step_started_at: str = "",
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "assigned_role": assigned_role,
        "step_started_at": step_started_at,
        "instance": workflow_instance_to_payload(instance),
    }


def workflow_instance_to_payload(instance: WorkflowInstance) -> dict[str, Any]:
    return {
        "instance_id": instance.instance_id,
        "workflow_id": instance.workflow_id,
        "proposal_id": instance.proposal_id,
        "current_step_id": instance.current_step_id,
        "state": instance.state,
        "events": [
            {
                "event_id": e.event_id,
                "instance_id": e.instance_id,
                "step_id": e.step_id,
                "event_type": e.event_type,
                "actor": e.actor,
                "timestamp": e.timestamp,
                "payload": e.payload,
            }
            for e in instance.events
        ],
    }


def workflow_instance_from_payload(payload: dict[str, Any]) -> WorkflowInstance:
    from agent_os_contracts import WorkflowEvent, WorkflowInstance

    return WorkflowInstance(
        instance_id=payload["instance_id"],
        workflow_id=payload["workflow_id"],
        proposal_id=payload["proposal_id"],
        current_step_id=payload["current_step_id"],
        state=payload["state"],
        events=tuple(WorkflowEvent(**event) for event in payload.get("events", [])),
    )


def workflow_instance_record_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return normalized record fields; caller builds ``WorkflowInstanceRecord``."""
    return {
        "tenant_id": payload["tenant_id"],
        "instance": workflow_instance_from_payload(payload["instance"]),
        "assigned_role": payload.get("assigned_role", ""),
        "step_started_at": payload.get("step_started_at", ""),
    }


def auto_execution_policy_to_payload(policy: AutoExecutionPolicy) -> dict[str, Any]:
    return {
        "version": policy.version,
        "tenant_id": policy.tenant_id,
        "owner": policy.owner,
        "default_mode": policy.default_mode,
        "rules": [
            {
                "rule_id": r.rule_id,
                "action_type": r.action_type,
                "risk_levels": list(r.risk_levels),
                "mode": r.mode,
                "guard_conditions": dict(r.guard_conditions),
                "compensating_action": r.compensating_action,
            }
            for r in policy.rules
        ],
    }


def auto_execution_policy_from_payload(payload: dict[str, Any]) -> AutoExecutionPolicy:
    from agent_os_contracts import AutoExecutionPolicy, AutoExecutionRule

    return AutoExecutionPolicy(
        version=payload["version"],
        tenant_id=payload["tenant_id"],
        owner=payload["owner"],
        default_mode=payload.get("default_mode", "proposal_only"),
        rules=tuple(AutoExecutionRule(**rule) for rule in payload.get("rules", [])),
    )
