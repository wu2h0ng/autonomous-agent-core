from __future__ import annotations

import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from agent_os_api.cli import run_cli
from agent_os_api.runtime_factory import EXECUTOR_SQLITE, STORE_POSTGRES, RuntimeFactoryConfig


class CliQueryStillWorksTest(unittest.TestCase):
    def test_default_query_subcommand_emits_evidence(self) -> None:
        out = io.StringIO()
        rc = run_cli(
            [
                "query",
                "--question",
                "GMV",
                "--start-date",
                "2026-05-25",
                "--end-date",
                "2026-06-01",
                "--limit",
                "100",
            ],
            stdout=out,
        )
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertIn("evidence_chain_id", payload)
        self.assertIn("trace_id", payload)
        self.assertEqual(payload["row_count"], 1)


class CliRecordOutcomeTest(unittest.TestCase):
    def test_record_outcome_subcommand_emits_json(self) -> None:
        out = io.StringIO()
        rc = run_cli(
            [
                "record-outcome",
                "--trace-id",
                "trace-unknown-cli",
                "--outcome",
                "adopted",
                "--reviewer",
                "ops@example.com",
                "--metric",
                "gmv=1000.0",
                "--metric",
                "orders=12",
            ],
            stdout=out,
        )
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["trace_id"], "trace-unknown-cli")
        self.assertEqual(payload["outcome"], "adopted")
        self.assertEqual(payload["reviewer"], "ops@example.com")
        self.assertTrue(payload["feedback_id"].startswith("feedback-"))
        # Fresh process: the in-memory store has no prior run for this trace.
        self.assertIsNone(payload["knowledge_asset_id"])
        self.assertEqual(payload["knowledge_version"], 0)

    def test_record_outcome_rejects_bad_metric_format(self) -> None:
        out = io.StringIO()
        with self.assertRaises(SystemExit):
            run_cli(
                [
                    "record-outcome",
                    "--trace-id",
                    "trace-x",
                    "--outcome",
                    "adopted",
                    "--metric",
                    "no_equals_sign",
                ],
                stdout=out,
            )


class CliEnvWiringTest(unittest.TestCase):
    def test_query_uses_store_backend_from_env_when_flag_omitted(self) -> None:
        captured: list[RuntimeFactoryConfig] = []

        def fake_factory(config: RuntimeFactoryConfig) -> MagicMock:
            captured.append(config)
            factory = MagicMock()
            factory.build.return_value = MagicMock()
            return factory

        env = {
            "AGENT_OS_STORE_BACKEND": STORE_POSTGRES,
            "AGENT_OS_DATABASE_URL": "postgresql+psycopg://example/db",
            "AGENT_OS_EXECUTOR": EXECUTOR_SQLITE,
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("agent_os_api.cli.ContentCommerceRuntimeFactory", side_effect=fake_factory):
                with patch("agent_os_api.cli.run_service", return_value={"status": "ok"}):
                    rc = run_cli(
                        [
                            "query",
                            "--question",
                            "GMV",
                            "--start-date",
                            "2026-05-25",
                            "--end-date",
                            "2026-06-01",
                        ],
                        stdout=io.StringIO(),
                    )

        self.assertEqual(rc, 0)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].store_backend, STORE_POSTGRES)
        self.assertEqual(captured[0].database_url, "postgresql+psycopg://example/db")
        self.assertEqual(captured[0].executor, EXECUTOR_SQLITE)

    def test_record_outcome_cli_flag_overrides_env_store_backend(self) -> None:
        captured: list[RuntimeFactoryConfig] = []

        def fake_factory(config: RuntimeFactoryConfig) -> MagicMock:
            captured.append(config)
            factory = MagicMock()
            factory.build.return_value = MagicMock()
            return factory

        env = {
            "AGENT_OS_STORE_BACKEND": STORE_POSTGRES,
            "AGENT_OS_DATABASE_URL": "postgresql+psycopg://example/db",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("agent_os_api.cli.ContentCommerceRuntimeFactory", side_effect=fake_factory):
                with patch(
                    "agent_os_api.cli.record_outcome_service",
                    return_value={
                        "feedback_id": "feedback-x",
                        "trace_id": "trace-x",
                        "outcome": "adopted",
                        "reviewer": None,
                        "knowledge_asset_id": None,
                        "knowledge_version": 0,
                    },
                ):
                    rc = run_cli(
                        [
                            "record-outcome",
                            "--trace-id",
                            "trace-x",
                            "--outcome",
                            "adopted",
                            "--store-backend",
                            "memory",
                        ],
                        stdout=io.StringIO(),
                    )

        self.assertEqual(rc, 0)
        self.assertEqual(captured[0].store_backend, "memory")

    def test_cli_database_url_flag_satisfies_postgres_env_backend(self) -> None:
        captured: list[RuntimeFactoryConfig] = []

        def fake_factory(config: RuntimeFactoryConfig) -> MagicMock:
            captured.append(config)
            factory = MagicMock()
            factory.build.return_value = MagicMock()
            return factory

        env = {"AGENT_OS_STORE_BACKEND": STORE_POSTGRES}
        with patch.dict(os.environ, env, clear=True):
            with patch("agent_os_api.cli.ContentCommerceRuntimeFactory", side_effect=fake_factory):
                with patch("agent_os_api.cli.run_service", return_value={"status": "ok"}):
                    rc = run_cli(
                        [
                            "query",
                            "--question",
                            "GMV",
                            "--start-date",
                            "2026-05-25",
                            "--end-date",
                            "2026-06-01",
                            "--database-url",
                            "postgresql+psycopg://flag/db",
                        ],
                        stdout=io.StringIO(),
                    )

        self.assertEqual(rc, 0)
        self.assertEqual(captured[0].store_backend, STORE_POSTGRES)
        self.assertEqual(captured[0].database_url, "postgresql+psycopg://flag/db")


if __name__ == "__main__":
    unittest.main()
