"""Adoption value channel — the independent ingest for realized external value
(P5.1a, ADR-0001; prerequisite from RR-0002).

The leak this closes: ``TrustedLoopRuntime.record_outcome`` let the runtime
self-write adoption signals into the same feedback store a learning/credit path
reads. A future self-evolving mechanism could fabricate "adopted" to feed itself.

The split mirrors the prototype's operator-exclusive ValueChannel (op_credit):

- ``AdoptionLedger`` is a SEPARATE store (distinct write path) from the runtime's
  self-report ``FeedbackStore``. Realized external value lives only here.
- ``AdoptionIngest`` is the ONLY writer. It holds its own builder fixed to
  ``EXTERNAL_ADOPTION``; an operator constructs and holds it. OS Core runtime
  code never holds one, so it cannot mint realized value.
- ``AdoptionLedgerView`` is a read-only capability handed to the runtime: it can
  READ realized value (to weight knowledge/recall) but exposes no write surface.

Self-report and external adoption are schema-separated (different stores, and a
``source`` tag on every event) and must never be co-aggregated.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter

from agent_os_contracts import FeedbackEvent, FeedbackSource

from ..feedback import FeedbackEventBuilder

__all__ = [
    "AdoptionLedgerPort",
    "AdoptionLedger",
    "AdoptionLedgerView",
    "AdoptionIngest",
]


class AdoptionLedgerPort(ABC):
    """Persistence port for realized external-value (adoption) events."""

    @abstractmethod
    def record(self, event: FeedbackEvent) -> FeedbackEvent: ...

    @abstractmethod
    def get_by_trace(self, trace_id: str) -> tuple[FeedbackEvent, ...]: ...

    @abstractmethod
    def all_events(self) -> tuple[FeedbackEvent, ...]: ...

    @abstractmethod
    def adoption_counts(self) -> dict[str, int]: ...


class AdoptionLedger(AdoptionLedgerPort):
    """In-memory adoption ledger. Only ``EXTERNAL_ADOPTION`` events belong here.

    ``record`` refuses any event that is not provenance ``EXTERNAL_ADOPTION`` —
    a self-report can never be smuggled into the value channel even with a
    direct ledger handle.
    """

    def __init__(self) -> None:
        self._by_trace: dict[str, list[FeedbackEvent]] = {}

    def record(self, event: FeedbackEvent) -> FeedbackEvent:
        if event.source != FeedbackSource.EXTERNAL_ADOPTION:
            raise ValueError(
                "AdoptionLedger only accepts EXTERNAL_ADOPTION events; "
                f"refusing source={event.source!r}"
            )
        self._by_trace.setdefault(event.trace_id, []).append(event)
        return event

    def get_by_trace(self, trace_id: str) -> tuple[FeedbackEvent, ...]:
        return tuple(self._by_trace.get(trace_id, ()))

    def all_events(self) -> tuple[FeedbackEvent, ...]:
        return tuple(e for events in self._by_trace.values() for e in events)

    def adoption_counts(self) -> dict[str, int]:
        counter: Counter[str] = Counter(e.outcome for e in self.all_events())
        return dict(counter)

    def view(self) -> AdoptionLedgerView:
        """Derive the read-only view the runtime should hold."""
        return AdoptionLedgerView(self)


class AdoptionLedgerView:
    """Read-only capability over an ``AdoptionLedgerPort``.

    The runtime holds this, not the ledger: there is no ``record`` here, so a
    runtime code path cannot write realized value through it.
    """

    def __init__(self, ledger: AdoptionLedgerPort) -> None:
        self._ledger = ledger

    def get_by_trace(self, trace_id: str) -> tuple[FeedbackEvent, ...]:
        return self._ledger.get_by_trace(trace_id)

    def adoption_counts(self) -> dict[str, int]:
        return self._ledger.adoption_counts()


class AdoptionIngest:
    """Operator-exclusive writer for realized external value (the value channel).

    Holds a builder fixed to ``EXTERNAL_ADOPTION`` and a write handle to the
    ledger. This is the only sanctioned path to attest adoption; whoever holds an
    ``AdoptionIngest`` is the operator. The runtime is never given one.
    """

    def __init__(self, ledger: AdoptionLedgerPort) -> None:
        self._ledger = ledger
        # Fixed-source builder: this component can ONLY emit external adoption.
        self._builder = FeedbackEventBuilder(source=FeedbackSource.EXTERNAL_ADOPTION)

    def submit(
        self,
        *,
        trace_id: str,
        outcome: str,
        reviewer: str | None = None,
        metric_deltas: dict[str, object] | None = None,
    ) -> FeedbackEvent:
        """Attest realized external value for ``trace_id`` and record it."""
        event = self._builder.build(
            trace_id=trace_id,
            outcome=outcome,
            reviewer=reviewer,
            metric_deltas=metric_deltas,
        )
        return self._ledger.record(event)

    def view(self) -> AdoptionLedgerView:
        """Derive the read-only view the runtime should hold."""
        return AdoptionLedgerView(self._ledger)
