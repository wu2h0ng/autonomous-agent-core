"""Ledger consequence preview: the domain-independent derivation + its read-only port (ADR-0016).

Before an approver decides, Agent Core surfaces the action's OWN governed history as an
evidence-bound SYMBOLIC preview — "this ``action_type`` has N prior executions, M of which resolved
to the intended outcome". This module owns the GENERIC half:

- ``ActionHistoryPort`` — a read-only seam onto a durable, tenant-scoped action-execution ledger.
  Agent Core stays unaware of any concrete ledger; a caller injects a concrete adapter that speaks
  the generic outcome vocabulary below.
- ``build_consequence_preview`` — a PURE projection over that ledger. Honest counts, never a
  prediction, learned model or probability: the disposer/human still decides.

There is deliberately no parallel cached counter: the preview is derived live from the ledger.
This carries no Metric/SQL/DataProduct/business-action semantics; it counts generic outcome strings.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from agent_os_contracts import ConsequencePreview

# The generic execution outcome that counts as "resolved to the intended outcome". A port
# implementation emits this SAME token so the derivation stays a pure string count, unaware of any
# concrete record shape.
INTENDED_EXECUTION_OUTCOME = "executed"

# How many of the most-recent outcomes the preview surfaces: a bounded recency window the human
# reads, not a model over the history.
DEFAULT_LAST_OUTCOMES = 5


class ActionHistoryPort(ABC):
    """Read-only port onto a durable, tenant-scoped action-execution ledger, keyed by action_type.

    Agent Core injects nothing and imports no concrete ledger: the caller supplies an adapter. The
    port speaks a GENERIC execution-outcome vocabulary so :func:`build_consequence_preview` only
    ever counts strings. Implementations MUST:

    - return the outcomes oldest -> newest (so "most recent K" is a real recency slice);
    - scope strictly to ``tenant_id`` (one tenant's history must never leak into another's preview);
    - RAISE on a read failure — the derivation turns that into ``available=False`` rather than
      fabricating counts.
    """

    @abstractmethod
    def outcomes_for(self, *, action_type: str, tenant_id: str = "default") -> tuple[str, ...]:
        """Return the ordered (oldest -> newest) execution outcomes recorded for ``action_type``."""
        ...


def build_consequence_preview(
    *,
    action_type: str,
    history_port: ActionHistoryPort | None,
    tenant_id: str = "default",
    intended_outcome: str = INTENDED_EXECUTION_OUTCOME,
    last_k: int = DEFAULT_LAST_OUTCOMES,
) -> ConsequencePreview:
    """Derive an evidence-bound SYMBOLIC consequence preview from the durable ledger (ADR-0016).

    A pure projection over the ledger's OWN records — honest counts only. ``available`` is False
    (with zero counts) when there is no history port wired, no prior history for ``action_type`` in
    this tenant, OR the ledger read failed: a novel or unreadable action is reported HONESTLY, never
    as a fabricated ``0/0`` dressed as real data.
    """
    if history_port is None:
        return ConsequencePreview(action_type=action_type, available=False)
    try:
        outcomes = tuple(history_port.outcomes_for(action_type=action_type, tenant_id=tenant_id))
    except Exception:  # noqa: BLE001 - a ledger read failure degrades to unavailable, never crashes
        return ConsequencePreview(action_type=action_type, available=False)
    if not outcomes:
        # No prior history: available=False so the surface renders "no prior history" HONESTLY,
        # distinct from "0 of N resolved" — a fabricated zero would masquerade as real data.
        return ConsequencePreview(action_type=action_type, available=False)
    resolved_intended = sum(1 for outcome in outcomes if outcome == intended_outcome)
    resolved_other = len(outcomes) - resolved_intended
    last_outcomes = outcomes[-last_k:] if last_k > 0 else ()
    return ConsequencePreview(
        action_type=action_type,
        prior_executions=len(outcomes),
        resolved_intended=resolved_intended,
        resolved_other=resolved_other,
        last_outcomes=last_outcomes,
        available=True,
    )
