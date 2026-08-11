"""SQLAlchemy-Core implementation of ``UsageStorePort``."""

from __future__ import annotations

from datetime import datetime, timezone

from agent_os_contracts import UsageEvent
from sqlalchemy import select

from . import schema
from .repositories import _SqlStoreBase


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SqlUsageStore(_SqlStoreBase):
    """Durable usage-event store backed by SQLAlchemy Core."""

    def record(self, event: UsageEvent) -> UsageEvent:
        recorded_at = event.recorded_at or _utc_now()
        payload = dict(event.payload)
        with self._write() as conn:
            conn.execute(
                schema.usage_events.insert().values(
                    tenant_id=event.tenant_id,
                    operation=event.operation,
                    trace_id=event.trace_id,
                    units=event.units,
                    recorded_at=recorded_at,
                    payload=payload,
                )
            )
        return UsageEvent(
            operation=event.operation,
            trace_id=event.trace_id,
            tenant_id=event.tenant_id,
            units=event.units,
            recorded_at=recorded_at,
            payload=payload,
        )

    def count(self, tenant_id: str, operation: str, window_seconds: int) -> int:
        cutoff = _utc_now().timestamp() - window_seconds
        table = schema.usage_events
        stmt = (
            select(table.c.units, table.c.recorded_at)
            .where(table.c.tenant_id == tenant_id)
            .where(table.c.operation == operation)
        )
        with self._read() as conn:
            rows = conn.execute(stmt).fetchall()

        def _to_utc_timestamp(dt: datetime) -> float:
            # SQLite returns naive datetimes for DateTime columns; treat them as UTC
            # so the window comparison matches the UTC recording time.
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()

        return sum(
            int(row.units)
            for row in rows
            if row.recorded_at is not None and _to_utc_timestamp(row.recorded_at) >= cutoff
        )

    def list_events(
        self, tenant_id: str, operation: str | None = None, limit: int = 100
    ) -> tuple[UsageEvent, ...]:
        table = schema.usage_events
        stmt = select(table).where(table.c.tenant_id == tenant_id)
        if operation is not None:
            stmt = stmt.where(table.c.operation == operation)
        stmt = stmt.order_by(table.c.id.desc()).limit(limit)
        with self._read() as conn:
            rows = conn.execute(stmt).fetchall()
        return tuple(
            UsageEvent(
                operation=row.operation,
                trace_id=row.trace_id,
                tenant_id=row.tenant_id,
                units=int(row.units),
                recorded_at=row.recorded_at,
                payload=dict(row.payload or {}),
            )
            for row in rows
        )
