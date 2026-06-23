"""Explicit (de)serialization between frozen contracts and JSON payloads.

Explicit mappers (not reflective magic) so schema evolution is visible and
round-trip-tested. Tuples/dicts on the frozen dataclasses round-trip through JSON
arrays/objects; enums are stored by value and reconstructed.
"""

from __future__ import annotations

from typing import Any

from agent_os_contracts import (
    CausalAttributionMethod,
    CausalOutcomeAttribution,
    FeedbackEvent,
    KnowledgeAsset,
    LifecycleState,
    RunTrace,
    StateSnapshot,
    TelemetryDimension,
    TelemetryEvent,
    TraceEvent,
)
from agent_os_core import ApprovalRecord


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
