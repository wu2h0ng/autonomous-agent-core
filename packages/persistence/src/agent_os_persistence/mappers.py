"""Explicit (de)serialization between frozen contracts and JSON payloads.

Explicit mappers (not reflective magic) so schema evolution is visible and
round-trip-tested. Tuples/dicts on the frozen dataclasses round-trip through JSON
arrays/objects; enums are stored by value and reconstructed.
"""

from __future__ import annotations

from typing import Any

from agent_os_contracts import (
    FeedbackEvent,
    KnowledgeAsset,
    LifecycleState,
    StateSnapshot,
)
from agent_os_core import ApprovalRecord


def feedback_to_payload(event: FeedbackEvent) -> dict[str, Any]:
    return {
        "feedback_id": event.feedback_id,
        "trace_id": event.trace_id,
        "outcome": event.outcome,
        "metrics": dict(event.metrics),
        "reviewer": event.reviewer,
    }


def feedback_from_payload(payload: dict[str, Any]) -> FeedbackEvent:
    return FeedbackEvent(
        feedback_id=payload["feedback_id"],
        trace_id=payload["trace_id"],
        outcome=payload["outcome"],
        metrics=dict(payload.get("metrics") or {}),
        reviewer=payload.get("reviewer"),
    )


def knowledge_to_payload(asset: KnowledgeAsset) -> dict[str, Any]:
    return {
        "asset_id": asset.asset_id,
        "title": asset.title,
        "asset_type": asset.asset_type,
        "source_trace_id": asset.source_trace_id,
        "owner": asset.owner,
        "state": asset.state.value,
    }


def knowledge_from_payload(payload: dict[str, Any]) -> KnowledgeAsset:
    return KnowledgeAsset(
        asset_id=payload["asset_id"],
        title=payload["title"],
        asset_type=payload["asset_type"],
        source_trace_id=payload.get("source_trace_id"),
        owner=payload["owner"],
        state=LifecycleState(payload["state"]),
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
    }


def approval_from_payload(payload: dict[str, Any]) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id=payload["approval_id"],
        proposal_id=payload["proposal_id"],
        status=payload["status"],
        approver_role=payload.get("approver_role"),
        reason=payload.get("reason"),
    )
