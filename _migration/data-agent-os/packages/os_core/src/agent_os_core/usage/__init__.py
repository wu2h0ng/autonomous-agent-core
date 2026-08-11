"""Usage-event storage port and in-memory reference implementation.

OS Core depends on ``UsageStorePort``; concrete adapters (in-memory for tests,
SQLAlchemy-Core for production) live outside OS Core.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from agent_os_contracts import UsageEvent

__all__ = ["InMemoryUsageStore", "UsageStorePort"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UsageStorePort(ABC):
    """Persistence port for tenant-scoped usage events."""

    @abstractmethod
    def record(self, event: UsageEvent) -> UsageEvent:
        """Persist ``event`` and return it with ``recorded_at`` populated."""
        ...

    @abstractmethod
    def count(self, tenant_id: str, operation: str, window_seconds: int) -> int:
        """Count units recorded for ``tenant_id``/``operation`` in the last window."""
        ...

    @abstractmethod
    def list_events(
        self, tenant_id: str, operation: str | None = None, limit: int = 100
    ) -> tuple[UsageEvent, ...]:
        """Return recent usage events for a tenant, optionally filtered by operation."""
        ...


class InMemoryUsageStore(UsageStorePort):
    """Thread-unsafe in-memory usage store for tests and single-process demos."""

    def __init__(self) -> None:
        self._events: list[UsageEvent] = []

    def record(self, event: UsageEvent) -> UsageEvent:
        recorded = UsageEvent(
            operation=event.operation,
            trace_id=event.trace_id,
            tenant_id=event.tenant_id,
            units=event.units,
            recorded_at=event.recorded_at or _utc_now(),
            payload=dict(event.payload),
        )
        self._events.append(recorded)
        return recorded

    def count(self, tenant_id: str, operation: str, window_seconds: int) -> int:
        now = _utc_now()
        cutoff = now.timestamp() - window_seconds
        return sum(
            event.units
            for event in self._events
            if event.tenant_id == tenant_id
            and event.operation == operation
            and event.recorded_at is not None
            and event.recorded_at.timestamp() >= cutoff
        )

    def list_events(
        self, tenant_id: str, operation: str | None = None, limit: int = 100
    ) -> tuple[UsageEvent, ...]:
        matched = [
            event
            for event in reversed(self._events)
            if event.tenant_id == tenant_id and (operation is None or event.operation == operation)
        ]
        return tuple(matched[:limit])
