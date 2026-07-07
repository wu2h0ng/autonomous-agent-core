"""Unit tests for the tenant-scoped QuotaGate."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from agent_os_contracts import QuotaExceeded, UsageEvent
from agent_os_core import InMemoryUsageStore, QuotaGate


class QuotaGateTest(unittest.TestCase):
    def test_missing_operation_is_ungated(self) -> None:
        gate = QuotaGate(InMemoryUsageStore(), limits={"run": (1, 3600)})
        gate.record_and_check("tenant-a", "unlisted", "trace-1")
        gate.record_and_check("tenant-a", "unlisted", "trace-2")

    def test_record_and_check_allows_under_limit(self) -> None:
        gate = QuotaGate(InMemoryUsageStore(), limits={"run": (2, 3600)})
        gate.record_and_check("tenant-a", "run", "trace-1")
        gate.record_and_check("tenant-a", "run", "trace-2")

    def test_record_and_check_rejects_over_limit(self) -> None:
        gate = QuotaGate(InMemoryUsageStore(), limits={"run": (1, 3600)})
        gate.record_and_check("tenant-a", "run", "trace-1")
        with self.assertRaises(QuotaExceeded) as ctx:
            gate.record_and_check("tenant-a", "run", "trace-2")
        self.assertEqual(ctx.exception.operation, "run")
        self.assertEqual(ctx.exception.limit, 1)
        self.assertGreaterEqual(ctx.exception.current_count, 2)

    def test_tenants_are_isolated(self) -> None:
        gate = QuotaGate(InMemoryUsageStore(), limits={"run": (1, 3600)})
        gate.record_and_check("tenant-a", "run", "trace-a")
        gate.record_and_check("tenant-b", "run", "trace-b")

    def test_check_without_record_fails_when_count_exceeds(self) -> None:
        store = InMemoryUsageStore()
        gate = QuotaGate(store, limits={"run": (1, 3600)})
        store.record(UsageEvent(tenant_id="tenant-a", operation="run", trace_id="trace-1"))
        store.record(UsageEvent(tenant_id="tenant-a", operation="run", trace_id="trace-2"))
        with self.assertRaises(QuotaExceeded):
            gate.check("tenant-a", "run")

    def test_units_can_exceed_limit_in_single_event(self) -> None:
        gate = QuotaGate(InMemoryUsageStore(), limits={"run": (1, 3600)})
        with self.assertRaises(QuotaExceeded) as ctx:
            gate.record_and_check("tenant-a", "run", "trace-1", units=5)
        self.assertEqual(ctx.exception.operation, "run")
        self.assertGreaterEqual(ctx.exception.current_count, 5)

    def test_window_excludes_old_events(self) -> None:
        store = InMemoryUsageStore()
        gate = QuotaGate(store, limits={"run": (1, 60)})
        old = datetime.now(timezone.utc) - timedelta(seconds=120)
        store.record(
            UsageEvent(tenant_id="tenant-a", operation="run", trace_id="old", recorded_at=old)
        )
        gate.record_and_check("tenant-a", "run", "new")


if __name__ == "__main__":
    unittest.main()
