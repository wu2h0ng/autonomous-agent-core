"""Factory wiring for knowledge recall + 12-factor env config (AR-20260611).

The factory must build ONE retriever per backend and share it between the runtime
(recall inside run()) and build_knowledge_retriever() (search surfaces), so the
default app's /knowledge/search reflects runtime writes instead of being a
permanently-empty fresh index.
"""

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
    ROOT / "action_connectors",
    ROOT / "apps" / "api_server" / "src",
):
    sys.path.insert(0, str(_p))

from agent_os_contracts import KnowledgeQuery  # noqa: E402

from agent_os_api.runtime_factory import (  # noqa: E402
    EXECUTOR_SQLITE,
    STORE_MEMORY,
    STORE_POSTGRES,
    ContentCommerceRuntimeFactory,
    RuntimeFactoryConfig,
)

_SQLALCHEMY = importlib.util.find_spec("sqlalchemy") is not None

DOMAIN_PACK = ROOT / "domain_packs" / "content_commerce"
RUN_PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}


class MemoryBackendRecallWiringTest(unittest.TestCase):
    def test_action_record_connector_declares_ledger_execution_semantics(self) -> None:
        factory = ContentCommerceRuntimeFactory(RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK))
        runtime = factory.build()

        contract = runtime.connector_registry.get_contract("action_record")

        self.assertEqual(contract.execution_semantics.durability_scope, "connector_local_ledger")
        self.assertEqual(contract.execution_semantics.external_ack_status, "not_applicable")
        self.assertEqual(contract.execution_semantics.ledger_status, "recorded")
        self.assertTrue(contract.execution_semantics.supports_idempotency)
        self.assertTrue(contract.execution_semantics.supports_reconciliation)

    def test_runtime_and_search_share_one_retriever(self) -> None:
        factory = ContentCommerceRuntimeFactory(RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK))
        runtime = factory.build()
        retriever = factory.build_knowledge_retriever()

        result = runtime.run("GMV", dict(RUN_PARAMS))
        self.assertIsNotNone(result.knowledge_asset_candidate)

        # The SAME retriever instance sees the runtime's write.
        hits = retriever.search(KnowledgeQuery(text="GMV", k=10))
        self.assertIn(result.knowledge_asset_candidate.asset_id, [h.asset.asset_id for h in hits])

    def test_second_run_recalls_via_factory_wiring(self) -> None:
        factory = ContentCommerceRuntimeFactory(RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK))
        runtime = factory.build()
        first = runtime.run("GMV", dict(RUN_PARAMS))
        second = runtime.run("GMV", dict(RUN_PARAMS))
        self.assertIn(
            first.knowledge_asset_candidate.asset_id,
            [r.asset.asset_id for r in second.related_knowledge],
        )


@unittest.skipUnless(_SQLALCHEMY, "sqlalchemy not installed (install .[postgres])")
class PostgresBackendRecallWiringTest(unittest.TestCase):
    def test_second_run_recalls_on_postgres_backend(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool

        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        factory = ContentCommerceRuntimeFactory(
            RuntimeFactoryConfig(
                domain_pack_path=DOMAIN_PACK,
                store_backend=STORE_POSTGRES,
                store_engine=engine,
            )
        )
        runtime = factory.build()
        first = runtime.run("GMV", dict(RUN_PARAMS))
        second = runtime.run("GMV", dict(RUN_PARAMS))
        self.assertIn(
            first.knowledge_asset_candidate.asset_id,
            [r.asset.asset_id for r in second.related_knowledge],
        )


class FromEnvConfigTest(unittest.TestCase):
    def test_defaults_preserve_current_behavior(self) -> None:
        config = RuntimeFactoryConfig.from_env(env={})
        self.assertEqual(config.domain_pack_path, Path("domain_packs/content_commerce"))
        self.assertEqual(config.executor, "static")
        self.assertEqual(config.store_backend, STORE_MEMORY)
        self.assertIsNone(config.database_url)

    def test_env_selects_real_backends(self) -> None:
        config = RuntimeFactoryConfig.from_env(
            env={
                "AGENT_OS_DOMAIN_PACK": "domain_packs/content_commerce",
                "AGENT_OS_EXECUTOR": EXECUTOR_SQLITE,
                "AGENT_OS_STORE_BACKEND": STORE_POSTGRES,
                "AGENT_OS_DATABASE_URL": "postgresql+psycopg://example/db",
            }
        )
        self.assertEqual(config.executor, EXECUTOR_SQLITE)
        self.assertEqual(config.store_backend, STORE_POSTGRES)
        self.assertEqual(config.database_url, "postgresql+psycopg://example/db")

    def test_postgres_without_dsn_is_an_explicit_error(self) -> None:
        with self.assertRaises(ValueError):
            RuntimeFactoryConfig.from_env(env={"AGENT_OS_STORE_BACKEND": STORE_POSTGRES})

    def test_unknown_executor_is_an_explicit_error(self) -> None:
        with self.assertRaises(ValueError):
            RuntimeFactoryConfig.from_env(env={"AGENT_OS_EXECUTOR": "duckdb"})


if __name__ == "__main__":
    unittest.main()
