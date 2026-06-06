"""Integration tests against a REAL PostgreSQL.

These run only when ``AGENT_OS_DATABASE_URL`` points at a reachable PostgreSQL
(e.g. ``postgresql+psycopg://user:pass@localhost/agent_os_test``); otherwise they
skip, so the default unit suite and bare-env CI stay green. They verify the same
repository semantics as the SQLite tests, but on the production dialect (JSONB,
psycopg driver).
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "persistence" / "src"))

_SQLALCHEMY = importlib.util.find_spec("sqlalchemy") is not None
_PG_URL = os.environ.get("AGENT_OS_DATABASE_URL")
_ENABLED = _SQLALCHEMY and bool(_PG_URL)


@unittest.skipUnless(
    _ENABLED, "set AGENT_OS_DATABASE_URL to a PostgreSQL DSN (and install .[postgres]) to run"
)
class PostgresIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        from sqlalchemy import create_engine

        from agent_os_persistence import create_all, metadata

        self.engine = create_engine(_PG_URL)
        # Isolate each run: drop + recreate the persistence tables.
        metadata.drop_all(self.engine)
        create_all(self.engine)

    def tearDown(self) -> None:
        from agent_os_persistence import metadata

        metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_feedback_knowledge_round_trip_on_postgres(self) -> None:
        from agent_os_contracts import FeedbackEvent, KnowledgeAsset, LifecycleState
        from agent_os_persistence import SqlFeedbackStore, SqlKnowledgeStore

        fb = SqlFeedbackStore(self.engine)
        event = FeedbackEvent(
            feedback_id="feedback-pg",
            trace_id="trace-pg",
            outcome="adopted",
            metrics={"gmv": 1200.0},
            reviewer="ops@example.com",
        )
        fb.record(event)
        self.assertEqual(fb.get_by_trace("trace-pg"), (event,))

        kn = SqlKnowledgeStore(self.engine)
        asset = KnowledgeAsset(
            asset_id="knowledge-pg",
            title="[gmv] pg",
            asset_type="decision_loop",
            source_trace_id="trace-pg",
            owner="revenue_ops",
            state=LifecycleState.DRAFT,
        )
        kn.register(asset)
        self.assertEqual(kn.version_of("trace-pg"), 1)
        kn.register_version(asset)
        self.assertEqual(kn.version_of("trace-pg"), 2)

    def test_unit_of_work_atomic_on_postgres(self) -> None:
        from agent_os_contracts import FeedbackEvent
        from agent_os_persistence import SqlFeedbackStore, SqlUnitOfWork

        with self.assertRaises(RuntimeError):
            with SqlUnitOfWork(self.engine)() as (fb, _kn):
                fb.record(FeedbackEvent(feedback_id="f-rb", trace_id="t-rb", outcome="adopted"))
                raise RuntimeError("boom")
        self.assertEqual(SqlFeedbackStore(self.engine).get_by_trace("t-rb"), ())


if __name__ == "__main__":
    unittest.main()
