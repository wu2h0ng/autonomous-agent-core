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
