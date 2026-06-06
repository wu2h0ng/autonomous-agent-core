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
    }


def record_outcome_service(
    runtime: Any,
    *,
    trace_id: str,
    outcome: str,
    reviewer: str | None = None,
    metric_deltas: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record an observed outcome for ``trace_id`` and report the result.

    Delegates to ``runtime.record_outcome`` (which builds+stores a
    ``FeedbackEvent`` and, when a candidate exists for the trace, supersedes it
    with a version bump), then reads back the knowledge store so the caller sees
    the resulting asset id and version.

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
