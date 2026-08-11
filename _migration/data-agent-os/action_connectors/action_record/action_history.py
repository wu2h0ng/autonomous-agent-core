"""ActionRecordHistoryAdapter: reads the action_record ledger for the consequence preview (ADR-0016).

This adapter is the ONLY place that knows the action_record connector's durable record shape. It
implements OS Core's generic :class:`ActionHistoryPort`, so OS Core stays unaware of the ledger and
only ever counts generic outcome strings. Mapping (the ledger's own signals, no business semantics):

- a record maps to ``INTENDED_EXECUTION_OUTCOME`` (a clean, ACK-observed execution) UNLESS
- its write ACK was lost (``uncertain_execution_count > 0``), in which case it maps to
  ``UNCERTAIN_EXECUTION_OUTCOME`` — executed, but did NOT cleanly resolve to the intended outcome.

Counts are read live from the ledger every time; there is no parallel counter to drift. Tenant
scoping is delegated to the store: durable ``SqlActionRecordStore`` and the in-memory dev store
both expose ``records(*, tenant_id)``; the adapter always calls with the run tenant.
"""

from __future__ import annotations

from typing import Any, Protocol

from agent_os_core.consequence_preview import INTENDED_EXECUTION_OUTCOME, ActionHistoryPort

# Generic outcome for a record whose write ACK was lost after the ledger write (executed, but not
# cleanly resolved to the intended outcome). Distinct token so ``resolved_other`` is a real signal.
UNCERTAIN_EXECUTION_OUTCOME = "execution_uncertain"


class _RecordsStore(Protocol):
    """The read surface the adapter needs (satisfied by both the in-memory and SQL ledgers)."""

    def records(self, *, tenant_id: str = "default") -> tuple[dict[str, Any], ...]: ...


class ActionRecordHistoryAdapter(ActionHistoryPort):
    """Read-only ``ActionHistoryPort`` over the action_record connector's durable ledger."""

    def __init__(self, store: _RecordsStore) -> None:
        self._store = store

    def outcomes_for(self, *, action_type: str, tenant_id: str = "default") -> tuple[str, ...]:
        records = self._store.records(tenant_id=tenant_id)
        outcomes: list[str] = []
        for record in records:
            if record.get("action_type") != action_type:
                continue
            if int(record.get("uncertain_execution_count", 0) or 0) > 0:
                outcomes.append(UNCERTAIN_EXECUTION_OUTCOME)
            else:
                outcomes.append(INTENDED_EXECUTION_OUTCOME)
        return tuple(outcomes)
