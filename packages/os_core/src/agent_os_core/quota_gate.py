"""Tenant-scoped quota gate over a ``UsageStorePort``.

The gate is deliberately simple: it records an event and then counts events in
a fixed look-back window. It is not a rate-limiter (no sliding log precision
required) and is not a billing ledger (units are integers, not dollars).
"""

from __future__ import annotations

from agent_os_contracts import QuotaExceeded, UsageEvent

from .usage import UsageStorePort

__all__ = ["QuotaGate"]

# Generous defaults suitable for an enterprise MVP; production deployments are
# expected to override these via configuration.
DEFAULT_QUOTA_LIMITS: dict[str, tuple[int, int]] = {
    "run": (1000, 3600),
    "approval_execute": (100, 3600),
    "outcome_record": (500, 3600),
    "adoption_record": (200, 3600),
}


class QuotaGate:
    """Enforce per-tenant, per-operation usage limits.

    ``limits`` maps an operation name to ``(limit, window_seconds)``. A limit of
    ``None`` or a missing operation disables gating for that operation.
    """

    def __init__(
        self,
        store: UsageStorePort,
        limits: dict[str, tuple[int, int]] | None = None,
    ) -> None:
        self.store = store
        self.limits = limits if limits is not None else dict(DEFAULT_QUOTA_LIMITS)

    def check(self, tenant_id: str, operation: str) -> None:
        """Raise ``QuotaExceeded`` if the tenant has exceeded the operation limit."""
        config = self.limits.get(operation)
        if config is None:
            return
        limit, window_seconds = config
        count = self.store.count(tenant_id, operation, window_seconds)
        if count > limit:
            raise QuotaExceeded(
                operation=operation,
                limit=limit,
                window_seconds=window_seconds,
                current_count=count,
            )

    def record_and_check(
        self,
        tenant_id: str,
        operation: str,
        trace_id: str,
        units: int = 1,
    ) -> None:
        """Record a usage event then enforce the operation limit."""
        self.store.record(
            UsageEvent(
                tenant_id=tenant_id,
                operation=operation,
                trace_id=trace_id,
                units=units,
            )
        )
        self.check(tenant_id, operation)
