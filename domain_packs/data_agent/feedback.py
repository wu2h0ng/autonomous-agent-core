"""Feedback building and storage for the trusted loop's back half.

This module turns raw outcome signals produced by the loop (``trace_id`` plus an
outcome and optional metric deltas) into typed, deterministic ``FeedbackEvent``
records, and provides an in-memory store that downstream learning can query.

OS Core stays domain-independent: nothing here references a specific business
domain, connector, or customer.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections import Counter

from .domain_contracts import CausalOutcomeAttribution, FeedbackEvent, FeedbackSource

__all__ = ["FeedbackEventBuilder", "FeedbackStore", "FeedbackStorePort"]


class FeedbackStorePort(ABC):
    """Persistence port for feedback events.

    OS Core depends on this abstraction; concrete backends (in-memory below, or a
    future PostgreSQL adapter outside OS Core) implement it. See
    docs/architecture_reviews/AR-20260606-persistent-store-design.md.
    """

    @abstractmethod
    def record(self, event: FeedbackEvent, *, tenant_id: str = "default") -> FeedbackEvent: ...

    @abstractmethod
    def get_by_trace(
        self, trace_id: str, *, tenant_id: str = "default"
    ) -> tuple[FeedbackEvent, ...]: ...

    @abstractmethod
    def all_events(self, *, tenant_id: str = "default") -> tuple[FeedbackEvent, ...]: ...

    @abstractmethod
    def outcome_counts(self, *, tenant_id: str = "default") -> dict[str, int]: ...


class FeedbackEventBuilder:
    """Build deterministic ``FeedbackEvent`` records from loop outcome signals.

    The ``source`` (provenance channel) is FIXED at construction and stamped on
    every event; ``build`` does not accept it as a parameter. This is the
    capability boundary (P5.1a, ADR-0001): whoever holds a builder can only emit
    that builder's source. The runtime's builder is ``RUNTIME_SELF_REPORT``, so
    the runtime is structurally unable to mint an ``EXTERNAL_ADOPTION`` event.
    """

    def __init__(self, source: str = FeedbackSource.RUNTIME_SELF_REPORT) -> None:
        self.source = source

    def build(
        self,
        *,
        trace_id: str,
        outcome: str,
        reviewer: str | None = None,
        metric_deltas: dict[str, object] | None = None,
        causal_attribution: CausalOutcomeAttribution | None = None,
    ) -> FeedbackEvent:
        """Produce a typed ``FeedbackEvent`` stamped with this builder's source.

        Args:
            trace_id: The trace this feedback is about. Required.
            outcome: The outcome signal (e.g. ``"adopted"``, ``"rejected"``).
                Required.
            reviewer: Optional human/agent reviewer attribution.
            metric_deltas: Optional metric deltas observed after the action.

        The ``feedback_id`` is derived deterministically from the trace id, the
        full content (outcome, reviewer, metric deltas), AND the source, so
        identical inputs yield identical ids and any change in content or
        provenance yields a different id.
        """
        if not trace_id:
            raise ValueError("trace_id is required to build a FeedbackEvent")
        if not outcome:
            raise ValueError("outcome is required to build a FeedbackEvent")

        metrics: dict[str, object] = dict(metric_deltas or {})
        feedback_id = self._derive_id(
            trace_id=trace_id,
            outcome=outcome,
            reviewer=reviewer,
            metrics=metrics,
            source=self.source,
        )
        return FeedbackEvent(
            feedback_id=feedback_id,
            trace_id=trace_id,
            outcome=outcome,
            metrics=metrics,
            reviewer=reviewer,
            source=self.source,
            causal_attribution=causal_attribution,
        )

    @staticmethod
    def _derive_id(
        *,
        trace_id: str,
        outcome: str,
        reviewer: str | None,
        metrics: dict[str, object],
        source: str,
    ) -> str:
        payload = json.dumps(
            {
                "trace_id": trace_id,
                "outcome": outcome,
                "reviewer": reviewer,
                "metrics": metrics,
                "source": source,
            },
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"feedback-{digest}"


class FeedbackStore(FeedbackStorePort):
    """In-memory store of ``FeedbackEvent`` records, indexed by ``trace_id``."""

    def __init__(self) -> None:
        self._by_trace: dict[str, dict[str, list[FeedbackEvent]]] = {}

    def record(self, event: FeedbackEvent, *, tenant_id: str = "default") -> FeedbackEvent:
        """Record a feedback event and return it."""
        self._by_trace.setdefault(tenant_id, {}).setdefault(event.trace_id, []).append(event)
        return event

    def get_by_trace(
        self, trace_id: str, *, tenant_id: str = "default"
    ) -> tuple[FeedbackEvent, ...]:
        """Return all events recorded for ``trace_id`` in insertion order."""
        return tuple(self._by_trace.get(tenant_id, {}).get(trace_id, ()))

    def all_events(self, *, tenant_id: str = "default") -> tuple[FeedbackEvent, ...]:
        """Return every recorded event across all traces for a tenant."""
        return tuple(
            event for events in self._by_trace.get(tenant_id, {}).values() for event in events
        )

    def outcome_counts(self, *, tenant_id: str = "default") -> dict[str, int]:
        """Aggregate event counts by outcome across all traces for a tenant."""
        counter: Counter[str] = Counter(
            event.outcome for event in self.all_events(tenant_id=tenant_id)
        )
        return dict(counter)
