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
from collections import Counter

from agent_os_contracts import FeedbackEvent

__all__ = ["FeedbackEventBuilder", "FeedbackStore"]


class FeedbackEventBuilder:
    """Build deterministic ``FeedbackEvent`` records from loop outcome signals."""

    def build(
        self,
        *,
        trace_id: str,
        outcome: str,
        reviewer: str | None = None,
        metric_deltas: dict[str, object] | None = None,
    ) -> FeedbackEvent:
        """Produce a typed ``FeedbackEvent``.

        Args:
            trace_id: The trace this feedback is about. Required.
            outcome: The outcome signal (e.g. ``"adopted"``, ``"rejected"``).
                Required.
            reviewer: Optional human/agent reviewer attribution.
            metric_deltas: Optional metric deltas observed after the action.

        The ``feedback_id`` is derived deterministically from the trace id and the
        full content (outcome, reviewer, metric deltas), so identical inputs yield
        identical ids and any change in content yields a different id.
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
        )
        return FeedbackEvent(
            feedback_id=feedback_id,
            trace_id=trace_id,
            outcome=outcome,
            metrics=metrics,
            reviewer=reviewer,
        )

    @staticmethod
    def _derive_id(
        *,
        trace_id: str,
        outcome: str,
        reviewer: str | None,
        metrics: dict[str, object],
    ) -> str:
        payload = json.dumps(
            {
                "trace_id": trace_id,
                "outcome": outcome,
                "reviewer": reviewer,
                "metrics": metrics,
            },
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"feedback-{digest}"


class FeedbackStore:
    """In-memory store of ``FeedbackEvent`` records, indexed by ``trace_id``."""

    def __init__(self) -> None:
        self._by_trace: dict[str, list[FeedbackEvent]] = {}

    def record(self, event: FeedbackEvent) -> FeedbackEvent:
        """Record a feedback event and return it."""
        self._by_trace.setdefault(event.trace_id, []).append(event)
        return event

    def get_by_trace(self, trace_id: str) -> tuple[FeedbackEvent, ...]:
        """Return all events recorded for ``trace_id`` in insertion order."""
        return tuple(self._by_trace.get(trace_id, ()))

    def all_events(self) -> tuple[FeedbackEvent, ...]:
        """Return every recorded event across all traces."""
        return tuple(
            event for events in self._by_trace.values() for event in events
        )

    def outcome_counts(self) -> dict[str, int]:
        """Aggregate event counts by outcome across all traces."""
        counter: Counter[str] = Counter(
            event.outcome for event in self.all_events()
        )
        return dict(counter)
