from __future__ import annotations

import importlib.util
import unittest

_SQLALCHEMY = importlib.util.find_spec("sqlalchemy") is not None


@unittest.skipUnless(_SQLALCHEMY, "sqlalchemy not installed (install .[postgres])")
class SqlRetrievalTenantIsolationTest(unittest.TestCase):
    """EmbeddingKnowledgeStore + SqlKnowledgeRetriever scope writes/reads by tenant."""

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

    def _asset(self, aid: str, title: str, trace: str):
        from agent_os_contracts import KnowledgeAsset, LifecycleState

        return KnowledgeAsset(
            asset_id=aid,
            title=title,
            asset_type="decision_loop",
            source_trace_id=trace,
            owner="revenue_ops",
            state=LifecycleState.ACTIVE,
        )

    def test_store_and_retriever_filter_by_tenant(self) -> None:
        from agent_os_contracts import KnowledgeQuery

        self.store.register(
            self._asset("a", "[gmv] gross merchandise value", "trace-a"),
            tenant_id="tenant-1",
        )
        self.store.register(
            self._asset("b", "[gmv] gross merchandise value", "trace-b"),
            tenant_id="tenant-2",
        )

        tenant1_hits = self.retriever.search(
            KnowledgeQuery(text="gross merchandise value", k=10),
            tenant_id="tenant-1",
        )
        tenant2_hits = self.retriever.search(
            KnowledgeQuery(text="gross merchandise value", k=10),
            tenant_id="tenant-2",
        )

        self.assertEqual({h.asset.asset_id for h in tenant1_hits}, {"a"})
        self.assertEqual({h.asset.asset_id for h in tenant2_hits}, {"b"})

    def test_store_defaults_to_default_tenant(self) -> None:
        from agent_os_contracts import KnowledgeQuery

        self.store.register(self._asset("c", "[gmv] gross merchandise value", "trace-c"))

        hits = self.retriever.search(KnowledgeQuery(text="gross merchandise value", k=10))
        self.assertEqual({h.asset.asset_id for h in hits}, {"c"})


if __name__ == "__main__":
    unittest.main()
