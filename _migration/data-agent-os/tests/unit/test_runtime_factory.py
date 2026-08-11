"""Tests for runtime factory "provider" executor selection."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api_server" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))

from agent_os_api import ContentCommerceRuntimeFactory, RuntimeFactoryConfig  # noqa: E402
from agent_os_api.executor_factory import ExecutorFactory  # noqa: E402

DOMAIN_PACK = ROOT / "domain_packs" / "content_commerce"


class RuntimeFactoryProviderTest(unittest.TestCase):
    def test_factory_with_provider_executor_defers_to_factory(self) -> None:
        runtime = ContentCommerceRuntimeFactory(
            RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK, executor="provider")
        ).build()

        self.assertIsNone(runtime.query_executor)
        self.assertIsNotNone(runtime.executor_factory)
        self.assertEqual(runtime.executor_factory, ExecutorFactory.from_provider_contract)

    def test_factory_uses_data_product_compiler_path(self) -> None:
        runtime = ContentCommerceRuntimeFactory(
            RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK)
        ).build()

        self.assertIsNone(runtime.template_registry)
        self.assertIsNotNone(runtime.data_product_compiler)
        result = runtime.run(
            "What was the GMV in the last 7 days?",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )
        self.assertEqual(result.intent.metric_name, "gmv")
        self.assertIsNotNone(result.query_plan.source_template)
        self.assertTrue(result.evidence_chain.is_typed_complete())


if __name__ == "__main__":
    unittest.main()
