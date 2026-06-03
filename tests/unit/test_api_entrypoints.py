from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api_server" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_api import ContentCommerceRuntimeFactory, RuntimeFactoryConfig  # noqa: E402
from agent_os_api.cli import run_cli  # noqa: E402


DOMAIN_PACK = ROOT / "domain_packs" / "content_commerce"


class ApiEntrypointTest(unittest.TestCase):
    def test_runtime_factory_builds_real_trusted_loop_from_domain_pack(self) -> None:
        runtime = ContentCommerceRuntimeFactory(
            RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK)
        ).build()

        result = runtime.run(
            "What was the GMV in the last 7 days?",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        self.assertEqual(result.intent.metric_name, "gmv")
        self.assertEqual(result.query_plan.metric_name, "gmv")
        self.assertTrue(result.evidence_chain.is_complete())
        self.assertIsNotNone(result.provider_contract)
        self.assertEqual(
            result.provider_contract.provider_id,
            "provider-content-commerce-sales",
        )
        self.assertIsNotNone(result.data_product_candidate)
        self.assertIn("semantic_resolution", [event.step for event in result.trace_events])
        self.assertIn("sql_safety", [event.step for event in result.trace_events])

    def test_cli_invokes_runtime_and_returns_traceable_json(self) -> None:
        stdout = io.StringIO()
        exit_code = run_cli(
            [
                "--question",
                "GMV",
                "--start-date",
                "2026-05-25",
                "--end-date",
                "2026-06-01",
                "--limit",
                "100",
                "--domain-pack",
                str(DOMAIN_PACK),
            ],
            stdout=stdout,
        )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["intent"], "gmv")
        self.assertEqual(payload["provider_id"], "provider-content-commerce-sales")
        self.assertIn("evidence_chain", payload["trace_steps"])
        self.assertIn("action_proposal", payload["trace_steps"])

    def test_runtime_factory_fails_on_missing_domain_pack_file(self) -> None:
        runtime_factory = ContentCommerceRuntimeFactory(
            RuntimeFactoryConfig(domain_pack_path=ROOT / "missing-pack")
        )

        with self.assertRaises(FileNotFoundError):
            runtime_factory.build()


if __name__ == "__main__":
    unittest.main()
