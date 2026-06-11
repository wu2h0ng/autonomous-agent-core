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

    def test_hybrid_retrieval_round_trip_on_postgres(self) -> None:
        # The full retrieval write path + hybrid search on the production dialect:
        # register indexes (JSONB payload + JSON embedding), the uow re-embed folds the
        # outcome in, and the retriever surfaces it with an explainable outcome_boost.
        from agent_os_contracts import KnowledgeAsset, KnowledgeQuery, LifecycleState
        from agent_os_core import HashingEmbedder, HybridScorer
        from agent_os_persistence import (
            EmbeddingKnowledgeStore,
            SqlKnowledgeRetriever,
            SqlKnowledgeStore,
            SqlUnitOfWork,
        )

        embedder = HashingEmbedder(64)
        store = EmbeddingKnowledgeStore(SqlKnowledgeStore(self.engine), embedder, self.engine)

        def _asset(
            aid: str, title: str, *, trace: str | None = None, outcome: str | None = None
        ) -> KnowledgeAsset:
            return KnowledgeAsset(
                asset_id=aid,
                title=title,
                asset_type="decision_loop",
                source_trace_id=trace or f"trace-{aid}",
                owner="revenue_ops",
                state=LifecycleState.DRAFT,
                outcome=outcome,
            )

        store.register(_asset("gmv", "[gmv] gross merchandise value daily"))
        store.register(_asset("spend", "[spend] ad spend marketing budget"))

        # Outcome folds in through the transactional uow re-embed path (the same
        # version-bump-on-the-same-trace shape record_outcome produces).
        uow = SqlUnitOfWork(
            self.engine,
            knowledge_store_factory=lambda conn: EmbeddingKnowledgeStore(
                SqlKnowledgeStore(conn), embedder, conn
            ),
        )
        with uow() as (_fb, kn):
            kn.register_version(
                _asset(
                    "spend2",
                    "[spend] ad spend marketing budget",
                    trace="trace-spend",
                    outcome="adopted",
                )
            )

        retriever = SqlKnowledgeRetriever(self.engine, HybridScorer(HashingEmbedder(64)))
        res = retriever.search(KnowledgeQuery(text="ad spend marketing budget", k=5))
        self.assertEqual(res[0].asset.asset_id, "spend2")
        self.assertEqual(res[0].asset.outcome, "adopted")
        self.assertGreater(res[0].score_breakdown["outcome_boost"], 0.0)

        by_metric = retriever.search(KnowledgeQuery(text="anything", metric_name="gmv"))
        self.assertEqual({r.asset.asset_id for r in by_metric}, {"gmv"})


if __name__ == "__main__":
    unittest.main()
