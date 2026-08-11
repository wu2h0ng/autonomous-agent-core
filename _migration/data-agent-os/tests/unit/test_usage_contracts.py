"""Unit tests for usage-event contracts."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from agent_os_contracts import QuotaExceeded, QuotaLimit, UsageEvent


class UsageEventContractTest(unittest.TestCase):
    def test_defaults_populate(self) -> None:
        event = UsageEvent(operation="run", trace_id="trace-1")
        self.assertEqual(event.tenant_id, "default")
        self.assertEqual(event.units, 1)
        self.assertIsNone(event.recorded_at)
        self.assertEqual(event.payload, {})

    def test_custom_fields_preserved(self) -> None:
        now = datetime.now(timezone.utc)
        event = UsageEvent(
            operation="approval_execute",
            trace_id="trace-2",
            tenant_id="tenant-a",
            units=3,
            recorded_at=now,
            payload={"route": "POST /approvals/x/execute"},
        )
        self.assertEqual(event.tenant_id, "tenant-a")
        self.assertEqual(event.units, 3)
        self.assertEqual(event.recorded_at, now)
        self.assertEqual(event.payload["route"], "POST /approvals/x/execute")


class QuotaLimitContractTest(unittest.TestCase):
    def test_limit_fields(self) -> None:
        limit = QuotaLimit(operation="run", limit=1000, window_seconds=3600)
        self.assertEqual(limit.operation, "run")
        self.assertEqual(limit.limit, 1000)
        self.assertEqual(limit.window_seconds, 3600)


class QuotaExceededContractTest(unittest.TestCase):
    def test_exception_attributes(self) -> None:
        exc = QuotaExceeded(
            operation="run",
            limit=10,
            window_seconds=3600,
            current_count=11,
        )
        self.assertEqual(exc.operation, "run")
        self.assertEqual(exc.limit, 10)
        self.assertEqual(exc.window_seconds, 3600)
        self.assertEqual(exc.current_count, 11)
        self.assertIn("run", str(exc))
        self.assertIn("11/10", str(exc))


if __name__ == "__main__":
    unittest.main()
