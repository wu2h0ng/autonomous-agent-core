from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (
    ROOT / "packages" / "contracts" / "src",
    ROOT / "packages" / "os_core" / "src",
    ROOT / "packages" / "persistence" / "src",
    ROOT / "packages" / "sdk" / "src",
    ROOT / "action_connectors",
    ROOT / "apps" / "api_server" / "src",
):
    sys.path.insert(0, str(_p))

_SQLALCHEMY = importlib.util.find_spec("sqlalchemy") is not None
RUN_PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}


@unittest.skipUnless(_SQLALCHEMY, "sqlalchemy not installed (install .[postgres])")
class FactoryPostgresStoreTest(unittest.TestCase):
    """Wire the persistence adapters through the factory and prove durability.

    Uses an injected in-memory SQLite engine as a stand-in for PostgreSQL. The
    key property: a knowledge candidate written by one runtime instance is
    visible to a SEPARATE runtime instance built on the same engine — i.e. it
    survives a simulated process restart, which the in-memory backend cannot do.
    """

    def _engine(self):
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool

        return create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    def _config(self, engine):
        from agent_os_api.runtime_factory import STORE_POSTGRES, RuntimeFactoryConfig

        return RuntimeFactoryConfig(
            domain_pack_path=ROOT / "domain_packs" / "content_commerce",
            store_backend=STORE_POSTGRES,
            store_engine=engine,
        )

    def test_postgres_backend_persists_across_runtime_instances(self) -> None:
        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory
        from agent_os_persistence import EmbeddingKnowledgeStore

        engine = self._engine()
        config = self._config(engine)

        # Instance 1 runs the loop -> writes a knowledge candidate to the DB.
        runtime1 = ContentCommerceRuntimeFactory(config).build()
        # The postgres knowledge store is the embedding decorator (write-side cascade).
        self.assertIsInstance(runtime1.knowledge_store, EmbeddingKnowledgeStore)
        result = runtime1.run("GMV", dict(RUN_PARAMS))
        trace_id = result.evidence_chain.trace_id

        # Instance 2 (fresh build, same engine = simulated restart) sees it.
        runtime2 = ContentCommerceRuntimeFactory(config).build()
        asset = runtime2.knowledge_store.get_by_trace(trace_id)
        self.assertIsNotNone(asset, "knowledge candidate did not persist across instances")
        self.assertEqual(runtime2.knowledge_store.version_of(trace_id), 1)

        # An outcome recorded on instance 2 is durable and visible to instance 3.
        runtime2.record_outcome(trace_id=trace_id, outcome="adopted")
        runtime3 = ContentCommerceRuntimeFactory(config).build()
        self.assertEqual(runtime3.knowledge_store.version_of(trace_id), 2)

    def test_unknown_store_backend_raises(self) -> None:
        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

        config = RuntimeFactoryConfig(
            domain_pack_path=ROOT / "domain_packs" / "content_commerce",
            store_backend="redis",
        )
        with self.assertRaises(ValueError):
            ContentCommerceRuntimeFactory(config).build()


if __name__ == "__main__":
    unittest.main()
