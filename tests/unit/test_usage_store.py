"""Unit tests for UsageStorePort implementations."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from agent_os_contracts import UsageEvent
from agent_os_core import InMemoryUsageStore
from agent_os_persistence import SqlUsageStore, create_all
from sqlalchemy import create_engine


class InMemoryUsageStoreTest(unittest.TestCase):
    def test_record_returns_populated_event(self) -> None:
        store = InMemoryUsageStore()
        event = UsageEvent(tenant_id="t1", operation="run", trace_id="trace-1")
        recorded = store.record(event)
        self.assertEqual(recorded.tenant_id, "t1")
        self.assertEqual(recorded.operation, "run")
        self.assertIsNotNone(recorded.recorded_at)

    def test_count_filters_by_tenant_and_window(self) -> None:
        store = InMemoryUsageStore()
        now = datetime.now(timezone.utc)
        store.record(UsageEvent(tenant_id="t1", operation="run", trace_id="a", recorded_at=now))
        store.record(UsageEvent(tenant_id="t1", operation="run", trace_id="b", recorded_at=now))
        store.record(UsageEvent(tenant_id="t2", operation="run", trace_id="c", recorded_at=now))
        store.record(
            UsageEvent(
                tenant_id="t1",
                operation="run",
                trace_id="old",
                recorded_at=now - timedelta(seconds=7200),
            )
        )
        self.assertEqual(store.count("t1", "run", 3600), 2)
        self.assertEqual(store.count("t2", "run", 3600), 1)
        self.assertEqual(store.count("t1", "run", 10800), 3)

    def test_list_events_returns_recent_first(self) -> None:
        store = InMemoryUsageStore()
        now = datetime.now(timezone.utc)
        store.record(UsageEvent(tenant_id="t1", operation="run", trace_id="first", recorded_at=now))
        store.record(
            UsageEvent(
                tenant_id="t1",
                operation="run",
                trace_id="second",
                recorded_at=now + timedelta(seconds=1),
            )
        )
        events = store.list_events("t1", "run", limit=10)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].trace_id, "second")
        self.assertEqual(events[1].trace_id, "first")


class SqlUsageStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        create_all(self.engine)
        self.store = SqlUsageStore(self.engine)

    def test_record_and_count_round_trip(self) -> None:
        now = datetime.now(timezone.utc)
        self.store.record(
            UsageEvent(tenant_id="t1", operation="run", trace_id="a", recorded_at=now)
        )
        self.store.record(
            UsageEvent(tenant_id="t1", operation="run", trace_id="b", recorded_at=now)
        )
        self.store.record(
            UsageEvent(tenant_id="t2", operation="run", trace_id="c", recorded_at=now)
        )
        self.assertEqual(self.store.count("t1", "run", 3600), 2)
        self.assertEqual(self.store.count("t2", "run", 3600), 1)

    def test_list_events_filters_by_operation(self) -> None:
        now = datetime.now(timezone.utc)
        self.store.record(
            UsageEvent(tenant_id="t1", operation="run", trace_id="r", recorded_at=now)
        )
        self.store.record(
            UsageEvent(tenant_id="t1", operation="approval_execute", trace_id="a", recorded_at=now)
        )
        runs = self.store.list_events("t1", "run")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].trace_id, "r")


if __name__ == "__main__":
    unittest.main()
