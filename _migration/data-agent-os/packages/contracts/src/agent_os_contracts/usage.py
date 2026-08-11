"""Usage-event contracts for tenant-scoped quota accounting.

These dataclasses are intentionally plain so they can be produced/consumed by
both the HTTP API (quota gating) and future billing/observability surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class UsageEvent:
    """A single countable operation occurrence attributed to a tenant.

    ``recorded_at`` is normally set by the store at insert time; callers may
    leave it ``None``.
    """

    operation: str
    trace_id: str
    tenant_id: str = "default"
    units: int = 1
    recorded_at: datetime | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class QuotaLimit:
    """A tenant-agnostic limit definition consumed by ``QuotaGate``."""

    operation: str
    limit: int
    window_seconds: int


class QuotaExceeded(Exception):
    """Raised by ``QuotaGate`` when an operation would exceed its limit."""

    def __init__(
        self,
        *,
        operation: str,
        limit: int,
        window_seconds: int,
        current_count: int,
    ) -> None:
        self.operation = operation
        self.limit = limit
        self.window_seconds = window_seconds
        self.current_count = current_count
        super().__init__(
            f"Quota exceeded for operation '{operation}': "
            f"{current_count}/{limit} in the last {window_seconds}s."
        )
