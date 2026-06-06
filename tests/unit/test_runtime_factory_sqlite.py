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
sys.path.insert(0, str(ROOT / "action_connectors"))

from agent_os_api import ContentCommerceRuntimeFactory, RuntimeFactoryConfig  # noqa: E402
from agent_os_api.cli import run_cli  # noqa: E402
from agent_os_core.query_runtime import SQLiteQueryExecutor  # noqa: E402

DOMAIN_PACK = ROOT / "domain_packs" / "content_commerce"


class RuntimeFactorySQLiteTest(unittest.TestCase):
    def test_factory_with_sqlite_executor_computes_real_gmv(self) -> None:
        """When the sqlite executor is selected, the loop must run against the
        seeded Customer-0 data and COMPUTE the GMV (128800.0) — a value the static
        executor would have to be hand-fed. Proof the real data path is wired."""
        factory = ContentCommerceRuntimeFactory(
            RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK, executor="sqlite")
        )
        runtime = factory.build()

        # The injected executor is the real SQL one, not the static fake.
        self.assertIsInstance(runtime.query_executor, SQLiteQueryExecutor)

        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        self.assertEqual(result.evidence_chain.query_result.row_count, 1)
        row = result.evidence_chain.query_result.rows[0]
        self.assertEqual(row["value"], 128800.0)
        self.assertEqual(row["order_date"], "2026-05-31")

    def test_factory_defaults_to_static_executor(self) -> None:
        """Default behavior is unchanged: the static executor stays in place."""
        from agent_os_core.query_runtime import StaticQueryExecutor

        runtime = ContentCommerceRuntimeFactory(
            RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK)
        ).build()
        self.assertIsInstance(runtime.query_executor, StaticQueryExecutor)

    def test_cli_selects_sqlite_executor(self) -> None:
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
                "--executor",
                "sqlite",
            ],
            stdout=stdout,
        )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["intent"], "gmv")
        self.assertEqual(payload["row_count"], 1)


if __name__ == "__main__":
    unittest.main()
