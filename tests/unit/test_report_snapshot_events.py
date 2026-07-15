from __future__ import annotations

import importlib.util
import unittest

_SQLALCHEMY = importlib.util.find_spec("sqlalchemy") is not None


class InMemoryReportSnapshotEventTest(unittest.TestCase):
    def test_external_snapshot_revisions_are_append_only_and_tenant_scoped(self) -> None:
        from agent_os_api.outcome_service import InMemoryReportSnapshotStore

        store = InMemoryReportSnapshotStore()
        first = {"trace_id": "trace-a", "audience": "external", "value": 1}
        changed = {**first, "value": 2}

        store.save("trace-a", {"external": first}, tenant_id="tenant-a")
        store.save("trace-a", {"external": first}, tenant_id="tenant-a")
        store.save("trace-a", {"external": changed}, tenant_id="tenant-a")
        store.save("trace-b", {"external": first}, tenant_id="tenant-b")

        self.assertTrue(hasattr(store, "list_events"), "report event feed is not implemented")
        events, has_more = store.list_events(
            after_sequence=0,
            limit=10,
            tenant_id="tenant-a",
        )

        self.assertFalse(has_more)
        self.assertEqual([event["trace_id"] for event in events], ["trace-a", "trace-a"])
        self.assertEqual([event["revision"] for event in events], [1, 2])
        self.assertNotEqual(events[0]["report_digest"], events[1]["report_digest"])
        self.assertEqual(store.get("trace-a", "external", tenant_id="tenant-a"), changed)

    def test_event_pagination_uses_strictly_increasing_sequence(self) -> None:
        from agent_os_api.outcome_service import InMemoryReportSnapshotStore

        store = InMemoryReportSnapshotStore()
        for index in range(3):
            store.save(
                f"trace-{index}",
                {"external": {"trace_id": f"trace-{index}", "audience": "external"}},
                tenant_id="tenant-a",
            )

        self.assertTrue(hasattr(store, "list_events"), "report event feed is not implemented")
        first, first_has_more = store.list_events(
            after_sequence=0,
            limit=2,
            tenant_id="tenant-a",
        )
        second, second_has_more = store.list_events(
            after_sequence=int(first[-1]["sequence"]),
            limit=2,
            tenant_id="tenant-a",
        )

        self.assertTrue(first_has_more)
        self.assertFalse(second_has_more)
        self.assertEqual(
            [event["trace_id"] for event in first + second],
            [
                "trace-0",
                "trace-1",
                "trace-2",
            ],
        )


@unittest.skipUnless(_SQLALCHEMY, "sqlalchemy not installed")
class SqlReportSnapshotEventTest(unittest.TestCase):
    def test_events_survive_fresh_store_instance_and_deduplicate_exact_replay(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool

        from agent_os_persistence import SqlReportSnapshotStore, create_all

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        create_all(engine)
        first_store = SqlReportSnapshotStore(engine)
        payload = {"trace_id": "trace-a", "audience": "external", "value": 1}
        first_store.save("trace-a", {"external": payload}, tenant_id="tenant-a")
        first_store.save("trace-a", {"external": payload}, tenant_id="tenant-a")

        restarted_store = SqlReportSnapshotStore(engine)
        self.assertTrue(
            hasattr(restarted_store, "list_events"),
            "durable report event feed is not implemented",
        )
        events, has_more = restarted_store.list_events(
            after_sequence=0,
            limit=10,
            tenant_id="tenant-a",
        )

        self.assertFalse(has_more)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["trace_id"], "trace-a")
        self.assertEqual(events[0]["revision"], 1)


if __name__ == "__main__":
    unittest.main()
