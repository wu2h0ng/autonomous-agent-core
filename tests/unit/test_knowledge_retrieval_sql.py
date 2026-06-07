from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "persistence" / "src"))

_SQLALCHEMY = importlib.util.find_spec("sqlalchemy") is not None


def _asset(aid: str, title: str, *, owner: str = "revenue_ops"):
    from agent_os_contracts import KnowledgeAsset, LifecycleState

    return KnowledgeAsset(
        asset_id=aid,
        title=title,
        asset_type="decision_loop",
        source_trace_id=f"trace-{aid}",
        owner=owner,
        state=LifecycleState.DRAFT,
    )


@unittest.skipUnless(_SQLALCHEMY, "sqlalchemy not installed (install .[postgres])")
class SqlKnowledgeRetrievalTest(unittest.TestCase):
    """Decorator + SQL retriever on in-memory SQLite.

    Same hybrid scorer as the in-memory retriever; structured filters resolve to
    indexed columns. pgvector `<=>`/HNSW is a later perf optimization, not a
    semantics change — embeddings persist as JSON lists here.
    """

    def setUp(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool

        from agent_os_core import HashingEmbedder, HybridScorer
        from agent_os_persistence import (
            EmbeddingKnowledgeStore,
            SqlKnowledgeRetriever,
            SqlKnowledgeStore,
            create_all,
        )

        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        create_all(self.engine)
        embedder = HashingEmbedder(dimensions=64)
        self.store = EmbeddingKnowledgeStore(SqlKnowledgeStore(self.engine), embedder, self.engine)
        self.retriever = SqlKnowledgeRetriever(self.engine, HybridScorer(HashingEmbedder(64)))

    def test_decorator_indexes_on_write(self) -> None:
        from sqlalchemy import select

        from agent_os_persistence import knowledge_index

        self.store.register(_asset("a", "[gmv] gmv gross merchandise value"))
        with self.engine.connect() as conn:
            row = conn.execute(
                select(knowledge_index.c.metric_name, knowledge_index.c.embedding).where(
                    knowledge_index.c.asset_id == "a"
                )
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row.metric_name, "gmv")  # parsed from "[gmv] ..." title
        self.assertEqual(len(row.embedding), 64)  # embedding persisted as a JSON list
        # storage delegation intact:
        self.assertEqual(self.store.version_of("trace-a"), 1)

    def test_retriever_ranks_and_filters(self) -> None:
        from agent_os_contracts import KnowledgeQuery

        self.store.register(_asset("gmv", "[gmv] gross merchandise value daily"))
        self.store.register(_asset("spend", "[spend] ad spend marketing budget"))
        self.store.register(_asset("conv", "[conversion_rate] conversion rate funnel"))

        res = self.retriever.search(KnowledgeQuery(text="ad spend marketing budget", k=3))
        self.assertEqual(res[0].asset.asset_id, "spend")
        self.assertEqual(
            set(res[0].score_breakdown),
            {
                "vector",
                "lexical",
                "rrf",
                "rrf_normalized",
                "outcome_boost",
                "recency_boost",
                "total",
            },
        )

        by_metric = self.retriever.search(KnowledgeQuery(text="anything", metric_name="gmv"))
        self.assertEqual({r.asset.asset_id for r in by_metric}, {"gmv"})

    def _revised(self, asset_id: str, title: str, trace: str):
        from agent_os_contracts import KnowledgeAsset, LifecycleState

        return KnowledgeAsset(
            asset_id=asset_id,
            title=title,
            asset_type="decision_loop",
            source_trace_id=trace,
            owner="revenue_ops",
            state=LifecycleState.DRAFT,
        )

    def _index_asset_ids(self, trace: str) -> list[str]:
        from sqlalchemy import select

        from agent_os_persistence import knowledge_index

        with self.engine.connect() as conn:
            rows = conn.execute(
                select(knowledge_index.c.asset_id).where(knowledge_index.c.source_trace_id == trace)
            ).fetchall()
        return [r.asset_id for r in rows]

    def test_version_bump_replaces_index_row_per_trace(self) -> None:
        # Same trace, new version -> ONE index row (replaced), not accumulated.
        self.store.register(_asset("a", "[gmv] old title alpha"))
        self.store.register_version(self._revised("a2", "[gmv] new title beta", "trace-a"))
        self.assertEqual(self._index_asset_ids("trace-a"), ["a2"])

    def test_uow_reembeds_index_atomically(self) -> None:
        from agent_os_core import HashingEmbedder
        from agent_os_persistence import (
            EmbeddingKnowledgeStore,
            SqlKnowledgeStore,
            SqlUnitOfWork,
        )

        self.store.register(_asset("v1", "[gmv] original"))  # trace-v1 indexed as v1
        embedder = HashingEmbedder(64)
        uow = SqlUnitOfWork(
            self.engine,
            knowledge_store_factory=lambda conn: EmbeddingKnowledgeStore(
                SqlKnowledgeStore(conn), embedder, conn
            ),
        )

        # Commit path: version bump inside the uow re-embeds the index row.
        with uow() as (_fb, kn):
            kn.register_version(self._revised("v2", "[gmv] revised content", "trace-v1"))
        self.assertEqual(self._index_asset_ids("trace-v1"), ["v2"])

        # Rollback path: a failure leaves BOTH the store and the index untouched.
        with self.assertRaises(RuntimeError):
            with uow() as (_fb, kn):
                kn.register_version(self._revised("v3", "[gmv] never committed", "trace-v1"))
                raise RuntimeError("boom")
        self.assertEqual(self._index_asset_ids("trace-v1"), ["v2"])  # unchanged


if __name__ == "__main__":
    unittest.main()
