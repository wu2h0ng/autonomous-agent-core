from __future__ import annotations

import hashlib
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest

_SQLALCHEMY = importlib.util.find_spec("sqlalchemy") is not None


def _digest(report: dict[str, object]) -> str:
    canonical = json.dumps(
        report,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


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
        self.assertEqual([event["report"] for event in events], [first, changed])
        self.assertEqual(
            [event["report_digest"] for event in events],
            [_digest(first), _digest(changed)],
        )
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
    def test_non_ascii_event_identity_matches_in_memory_store(self) -> None:
        from sqlalchemy import create_engine

        from agent_os_api.outcome_service import InMemoryReportSnapshotStore
        from agent_os_persistence import SqlReportSnapshotStore, create_all

        payload = {
            "trace_id": "追踪-一",
            "audience": "external",
            "title": "营收分析",
        }
        memory_store = InMemoryReportSnapshotStore()
        memory_store.save("追踪-一", {"external": payload}, tenant_id="租户-甲")
        memory_events, _ = memory_store.list_events(
            after_sequence=0,
            limit=10,
            tenant_id="租户-甲",
        )

        engine = create_engine("sqlite://")
        create_all(engine)
        sql_store = SqlReportSnapshotStore(engine)
        sql_store.save("追踪-一", {"external": payload}, tenant_id="租户-甲")
        sql_events, _ = sql_store.list_events(
            after_sequence=0,
            limit=10,
            tenant_id="租户-甲",
        )

        self.assertEqual(memory_events[0]["event_id"], sql_events[0]["event_id"])

    def test_concurrent_same_trace_saves_allocate_unique_contiguous_revisions(self) -> None:
        from sqlalchemy import create_engine

        from agent_os_persistence import SqlReportSnapshotStore, create_all

        worker_count = 8
        barrier = Barrier(worker_count)
        with TemporaryDirectory() as tmpdir:
            database = Path(tmpdir) / "report-events.sqlite3"
            engine = create_engine(
                f"sqlite:///{database}",
                connect_args={"check_same_thread": False, "timeout": 30},
            )
            create_all(engine)
            store = SqlReportSnapshotStore(engine)

            def save_revision(value: int) -> None:
                barrier.wait()
                store.save(
                    "trace-race",
                    {
                        "external": {
                            "trace_id": "trace-race",
                            "audience": "external",
                            "value": value,
                        }
                    },
                    tenant_id="tenant-a",
                )

            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                list(executor.map(save_revision, range(worker_count)))

            events, has_more = store.list_events(
                after_sequence=0,
                limit=worker_count + 1,
                tenant_id="tenant-a",
            )

        self.assertFalse(has_more)
        self.assertEqual([event["revision"] for event in events], list(range(1, 9)))
        self.assertEqual(
            {event["report"]["value"] for event in events},
            set(range(worker_count)),
        )

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
        first = {"trace_id": "trace-a", "audience": "external", "value": 1}
        changed = {**first, "value": 2}
        first_store.save("trace-a", {"external": first}, tenant_id="tenant-a")
        first_store.save("trace-a", {"external": first}, tenant_id="tenant-a")
        first_store.save("trace-a", {"external": changed}, tenant_id="tenant-a")

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
        self.assertEqual(len(events), 2)
        self.assertEqual([event["trace_id"] for event in events], ["trace-a", "trace-a"])
        self.assertEqual([event["revision"] for event in events], [1, 2])
        self.assertEqual([event["report"] for event in events], [first, changed])
        self.assertEqual(
            [event["report_digest"] for event in events],
            [_digest(first), _digest(changed)],
        )


if __name__ == "__main__":
    unittest.main()
