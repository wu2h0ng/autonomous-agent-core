"""Bridge C/D staged-out events into persisted RunTrace lineage (ADR-0013 hardening)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from agent_os_contracts import TraceEvent
from agent_os_core.trace import TraceStorePort


def build_staged_out_trace_sink(
    trace_store: TraceStorePort | None,
    *,
    tenant_id: str = "default",
) -> Callable[[str, dict[str, Any]], None]:
    """Return a trace_sink for WorkflowRuntime / McpToolRouter.

    When ``trace_id`` or ``proposal_id`` is present in the payload and a matching
    RunTrace exists in ``trace_store``, append a ``TraceEvent``. Otherwise no-op
    (fail-soft for management-plane ops without a run context).
    """

    def sink(step: str, payload: dict[str, Any]) -> None:
        if trace_store is None:
            return
        trace_id = payload.get("trace_id") or payload.get("proposal_id")
        if not trace_id:
            return
        existing = trace_store.get(str(trace_id), tenant_id=tenant_id)
        if existing is None:
            return
        event = TraceEvent(trace_id=str(trace_id), step=step, payload=dict(payload))
        trace_store.save(
            replace(existing, events=existing.events + (event,)),
            tenant_id=tenant_id,
        )

    return sink


__all__ = ["build_staged_out_trace_sink"]
