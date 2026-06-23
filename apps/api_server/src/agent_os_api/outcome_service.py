"""Framework-agnostic service layer for the Trusted Loop trigger surfaces.

This module is the single source of truth for the two post-/pre-outcome
behaviors that both the CLI and the FastAPI app expose. It deliberately does
NOT import any web framework so the core guarantees (run -> trace, outcome ->
knowledge version bump) are testable without HTTP.

The runtime is injected (``TrustedLoopRuntime`` from OS Core). These functions
only orchestrate calls into the runtime and read back its in-memory stores;
they contain no domain- or transport-specific logic.
"""

from __future__ import annotations

from typing import Any

from agent_os_contracts import CausalOutcomeAttribution, KnowledgeQuery


def _preview_rows(rows: tuple[dict[str, Any], ...], *, limit: int = 20) -> list[dict[str, Any]]:
    return [dict(row) for row in rows[:limit]]


def _columns(rows: tuple[dict[str, Any], ...]) -> list[str]:
    columns: list[str] = []
    for row in rows:
        for name in row:
            if name not in columns:
                columns.append(name)
    return columns


def _primary_metric_value(rows: tuple[dict[str, Any], ...], metric_name: str) -> Any | None:
    if not rows:
        return None
    first = rows[0]
    if metric_name in first:
        return first[metric_name]
    if (
        "value" in first
        and isinstance(first["value"], (int, float))
        and not isinstance(first["value"], bool)
    ):
        return first["value"]
    for value in first.values():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    return None


def _chart_fields(
    rows: tuple[dict[str, Any], ...],
    columns: list[str],
    dimensions: tuple[str, ...],
    metric_name: str,
) -> tuple[str, str] | None:
    if not rows:
        return None
    sample = rows[0]
    x_field = next((dimension for dimension in dimensions if dimension in columns), None)
    if x_field is None:
        x_field = next(
            (
                column
                for column in columns
                if not isinstance(sample.get(column), (int, float))
                or isinstance(sample.get(column), bool)
            ),
            None,
        )
    numeric_fields = [
        column
        for column in columns
        if isinstance(sample.get(column), (int, float)) and not isinstance(sample.get(column), bool)
    ]
    if not x_field or not numeric_fields:
        return None
    if metric_name in numeric_fields:
        y_field = metric_name
    elif "value" in numeric_fields:
        y_field = "value"
    else:
        y_field = numeric_fields[0]
    return x_field, y_field


def _business_action_status(proposal: Any, action_result: dict[str, Any]) -> str:
    status = action_result.get("status")
    if not proposal.approval_required and status in {"pending_approval", "awaiting_approval", None}:
        return "proposed"
    return status or "proposed"


def _build_user_result_artifact(result: Any) -> dict[str, Any]:
    """Build the user-facing data-agent result bundle from grounded runtime output.

    This is deliberately a read-side projection over ``TrustedLoopResult``: it
    does not query data, choose actions, or execute connectors. The data path and
    governance decisions remain owned by the Trusted Loop; this layer only
    packages them into analysis/report/dashboard/action surfaces a client can
    render directly.
    """
    evidence = result.evidence_chain
    proposal = result.action_proposal
    action_result = result.action_result or {}
    rows = evidence.query_result.rows
    trace_id = evidence.trace_id
    metric = evidence.metric_contract
    preview = _preview_rows(rows)
    columns = _columns(rows)
    metric_value = _primary_metric_value(rows, metric.metric_name)
    chart_fields = _chart_fields(rows, columns, metric.dimensions, metric.metric_name)
    widgets = [
        {
            "widget_id": "primary_metric",
            "type": "kpi",
            "title": metric.display_name,
            "value": metric_value,
            "unit": metric.unit,
            "evidence_chain_id": evidence.evidence_chain_id,
        },
    ]
    if chart_fields is not None:
        x_field, y_field = chart_fields
        widgets.append(
            {
                "widget_id": "metric_trend",
                "type": "line_chart",
                "title": f"{metric.display_name} trend",
                "row_count": evidence.query_result.row_count,
                "columns": columns,
                "preview_rows": preview,
                "x_field": x_field,
                "y_field": y_field,
                "evidence_chain_id": evidence.evidence_chain_id,
            }
        )
    widgets.append(
        {
            "widget_id": "result_rows",
            "type": "table",
            "title": "Result rows",
            "row_count": evidence.query_result.row_count,
            "columns": columns,
            "preview_rows": preview,
            "evidence_chain_id": evidence.evidence_chain_id,
        }
    )

    return {
        "artifact_id": f"artifact-{trace_id}",
        "kind": "data_agent_result",
        "title": f"{metric.display_name} analysis result",
        "trace_id": trace_id,
        "evidence_chain_id": evidence.evidence_chain_id,
        "action_proposal_id": proposal.proposal_id,
        "question": evidence.intent.question,
        "metric_name": metric.metric_name,
        "analysis": {
            "summary": evidence.conclusion,
            "confidence": evidence.confidence,
            "limitations": list(evidence.limitations),
            "row_count": evidence.query_result.row_count,
            "evidence_chain_id": evidence.evidence_chain_id,
        },
        "report": {
            "title": f"{metric.display_name} evidence-backed report",
            "sections": [
                {
                    "heading": "Finding",
                    "body": evidence.conclusion,
                    "items": [],
                },
                {
                    "heading": "Evidence",
                    "body": (
                        f"Metric contract {metric.metric_name} "
                        f"({metric.version}) produced {evidence.query_result.row_count} row(s)."
                    ),
                    "items": [
                        f"trace_id={trace_id}",
                        f"evidence_chain_id={evidence.evidence_chain_id}",
                        f"provider_sql_safety_allowed={evidence.sql_safety.allowed}",
                    ],
                },
                {
                    "heading": "Limitations",
                    "body": None,
                    "items": list(evidence.limitations),
                },
            ],
        },
        "dashboard": {
            "title": f"{metric.display_name} dashboard",
            "widgets": widgets,
        },
        "decision": {
            "recommendation": proposal.recommended_action,
            "reason": proposal.reason,
            "expected_impact": proposal.expected_impact,
            "risk_level": proposal.risk_level.value,
            "approval_required": proposal.approval_required,
            "approver_role": proposal.approver_role,
            "action_proposal_id": proposal.proposal_id,
            "confidence": evidence.confidence,
        },
        "business_action": {
            "connector_name": proposal.connector_name,
            "action_type": proposal.action_type,
            "risk_level": proposal.risk_level.value,
            "approval_required": proposal.approval_required,
            "approver_role": proposal.approver_role,
            "status": _business_action_status(proposal, action_result),
            "operation_id": action_result.get("operation_id"),
            "approval_id": action_result.get("approval_id"),
            "evidence_chain_id": evidence.evidence_chain_id,
            "trace_id": trace_id,
            "row_count": evidence.query_result.row_count,
        },
    }


def search_service(
    retriever: Any,
    *,
    text: str,
    metric_name: str | None = None,
    owner: str | None = None,
    k: int = 5,
) -> dict[str, Any]:
    """Search the knowledge memory and return JSON-able, explainable results.

    The real entry point for the KnowledgeRetriever capability (used by the CLI
    ``search`` subcommand). Each result carries its score breakdown (the "why").
    """
    results = retriever.search(KnowledgeQuery(text=text, metric_name=metric_name, owner=owner, k=k))
    return {
        "results": [
            {
                "asset_id": r.asset.asset_id,
                "title": r.asset.title,
                "score": r.score,
                "score_breakdown": r.score_breakdown,
            }
            for r in results
        ]
    }


def run_service(
    runtime: Any,
    *,
    question: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """Run the Trusted Loop for ``question`` and return a JSON-able summary.

    The ``trace_id`` is taken from ``result.evidence_chain.trace_id`` so callers
    can later attach an outcome to the same trace via :func:`record_outcome_service`.

    Returns ``{"status": "ok", ...}`` on success, or ``{"status": "blocked",
    "block": {...}}`` for an expected business block (unsafe SQL, unknown metric,
    no template, no provider) — a unified, JSON-able failure contract.
    """
    outcome = runtime.evaluate(question, parameters)
    if outcome.blocked:
        block = outcome.block
        return {
            "status": "blocked",
            "block": {
                "code": block.code.value,
                "message": block.message,
                "stage": block.stage,
                "details": list(block.details),
                # Refusals are auditable too (AR-20260611): the persisted RunTrace id.
                "trace_id": block.trace_id,
            },
        }

    result = outcome.result
    trace_id = result.evidence_chain.trace_id
    asset = runtime.knowledge_store.get_by_trace(trace_id)

    return {
        "status": "ok",
        "trace_id": trace_id,
        "intent": result.intent.metric_name,
        "provider_id": (result.provider_contract.provider_id if result.provider_contract else None),
        "evidence_chain_id": result.evidence_chain.evidence_chain_id,
        "action_proposal_id": result.action_proposal.proposal_id,
        "row_count": result.evidence_chain.query_result.row_count,
        "trace_steps": [event.step for event in result.trace_events],
        "knowledge_asset_id": asset.asset_id if asset is not None else None,
        "knowledge_version": runtime.knowledge_store.version_of(trace_id),
        # Read-side of the learning loop (AR-20260611): prior knowledge recalled
        # for this question, surfaced as advisory, explainable context.
        "related_knowledge": [
            {"asset_id": r.asset.asset_id, "title": r.asset.title, "score": r.score}
            for r in result.related_knowledge
        ],
        "user_result": _build_user_result_artifact(result),
    }


def trace_service(trace_store: Any, *, trace_id: str) -> dict[str, Any] | None:
    """Fetch the persisted RunTrace for ``trace_id`` (observability v1, AR-20260611).

    Takes the ``TraceStorePort`` directly (HTTP passes ``runtime.trace_store``;
    the CLI builds a standalone store) and returns a JSON-able dict, or ``None``
    when no run with that trace_id was persisted — the caller decides the
    transport-level not-found shape.
    """
    run_trace = trace_store.get(trace_id)
    if run_trace is None:
        return None
    return {
        "trace_id": run_trace.trace_id,
        "status": run_trace.status,
        "events": [{"step": e.step, "payload": e.payload} for e in run_trace.events],
        "telemetry": [
            {
                "dimension": t.dimension.value,
                "name": t.name,
                "value": t.value,
                "unit": t.unit,
                "attributes": t.attributes,
            }
            for t in run_trace.telemetry_events
        ],
    }


def approve_and_execute_service(
    runtime: Any,
    *,
    approval_id: str,
    reason: str | None = None,
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Approve and execute an approval-bound operation by approval id.

    This is the user-facing action execution surface for same-process runtimes:
    the caller supplies only the approval id and an optional reason. The runtime
    owns the pending operation context and still enforces approval status,
    operation fingerprint, SQL Safety, and EvidenceChain completeness before any
    connector write.
    """
    approval, operation_trace = runtime.approve_and_execute_pending_operation(
        approval_id=approval_id,
        reason=reason,
        approved_by=approved_by,
    )
    final_event = operation_trace.events[-1] if operation_trace.events else {}
    return {
        "approval_id": approval.approval_id,
        "approval_status": approval.status,
        "approved_by": approval.approved_by,
        "proposal_id": operation_trace.proposal_id,
        "operation_trace_id": operation_trace.trace_id,
        "operation_id": operation_trace.operation_id,
        "state": operation_trace.state.value,
        "evidence_chain_id": operation_trace.evidence_chain_id,
        "connector_name": final_event.get("connector_name"),
        "action_type": final_event.get("action_type"),
        "action_result_status": final_event.get("status"),
        "idempotency_key": final_event.get("idempotency_key"),
        "events": [dict(event) for event in operation_trace.events],
    }


def record_outcome_service(
    runtime: Any,
    *,
    trace_id: str,
    outcome: str,
    reviewer: str | None = None,
    metric_deltas: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a runtime SELF-REPORT for ``trace_id`` (observation only).

    Delegates to ``runtime.record_outcome`` (which builds+stores a self-report
    ``FeedbackEvent``). P5.1b (ADR-0001 / AR-20260614): a self-report does NOT
    promote knowledge — ``knowledge_version`` is reported unchanged. Value-driven
    promotion requires realized external value via :func:`attest_adoption_service`.

    For an unknown trace the feedback is still recorded, but no knowledge asset
    is fabricated: ``knowledge_asset_id`` is ``None`` and ``knowledge_version``
    is ``0``.
    """
    feedback = runtime.record_outcome(
        trace_id=trace_id,
        outcome=outcome,
        reviewer=reviewer,
        metric_deltas=metric_deltas,
    )
    asset = runtime.knowledge_store.get_by_trace(trace_id)

    return {
        "feedback_id": feedback.feedback_id,
        "trace_id": trace_id,
        "outcome": outcome,
        "reviewer": reviewer,
        "knowledge_asset_id": asset.asset_id if asset is not None else None,
        "knowledge_version": runtime.knowledge_store.version_of(trace_id),
    }


def attest_adoption_service(
    runtime: Any,
    adoption_ingest: Any,
    *,
    trace_id: str,
    outcome: str,
    reviewer: str | None = None,
    metric_deltas: dict[str, Any] | None = None,
    causal_attribution: CausalOutcomeAttribution | None = None,
) -> dict[str, Any]:
    """Attest REALIZED external value and promote the trace's knowledge (P5.1b).

    The operator-facing value channel and the single source of truth for both the
    CLI and HTTP adoption surfaces. ``adoption_ingest.submit`` records realized
    external adoption (the only path that can mint realized value, P5.1a); then
    ``runtime.promote_from_adoption`` folds it into the trace's KnowledgeAsset
    (version bump). Unlike a self-report, this is what drives knowledge promotion.

    For an unknown trace the adoption is still recorded, but no knowledge asset is
    fabricated: ``knowledge_asset_id`` is ``None`` and ``knowledge_version`` is ``0``.
    """
    adoption = adoption_ingest.submit(
        trace_id=trace_id,
        outcome=outcome,
        reviewer=reviewer,
        metric_deltas=metric_deltas,
        causal_attribution=causal_attribution,
    )
    revised = runtime.promote_from_adoption(trace_id)
    asset = runtime.knowledge_store.get_by_trace(trace_id)

    return {
        "adoption_id": adoption.feedback_id,
        "trace_id": trace_id,
        "outcome": outcome,
        "reviewer": reviewer,
        "knowledge_asset_id": asset.asset_id if asset is not None else None,
        "knowledge_version": runtime.knowledge_store.version_of(trace_id),
        "result_weight": revised.result_weight if revised is not None else None,
    }
