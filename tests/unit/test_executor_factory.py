"""Tests for ProviderContract-aware executor factory."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
for _p in (
    ROOT / "packages" / "contracts" / "src",
    ROOT / "packages" / "os_core" / "src",
    ROOT / "apps" / "api_server" / "src",
):
    sys.path.insert(0, str(_p))

from agent_os_contracts import ProviderConnection, ProviderContract, ProviderKind  # noqa: E402
from agent_os_api.executor_factory import ExecutorFactory  # noqa: E402


class ExecutorFactoryTest(unittest.TestCase):
    def _provider(self, connection: ProviderConnection | None = None) -> ProviderContract:
        return ProviderContract(
            provider_id="test",
            kind=ProviderKind.WAREHOUSE,
            name="test",
            owner="test",
            connection=connection,
        )

    def test_no_connection_returns_static_executor(self) -> None:
        executor = ExecutorFactory.from_provider_contract(self._provider())
        self.assertEqual(executor.__class__.__name__, "StaticQueryExecutor")

    def test_csv_connection_requires_path(self) -> None:
        provider = self._provider(ProviderConnection(connection_type="csv"))
        with self.assertRaises(ValueError):
            ExecutorFactory.from_provider_contract(provider)

    def test_csv_connection_returns_csv_executor(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
            tmp.write("a\n1\n")
            path = Path(tmp.name)
        try:
            provider = self._provider(ProviderConnection(connection_type="csv", path=str(path)))
            executor = ExecutorFactory.from_provider_contract(provider)
            self.assertEqual(executor.__class__.__name__, "CsvQueryExecutor")
        finally:
            path.unlink(missing_ok=True)

    def test_sqlite_connection_returns_sqlite_executor(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            provider = self._provider(ProviderConnection(connection_type="sqlite", path=str(path)))
            executor = ExecutorFactory.from_provider_contract(provider)
            self.assertEqual(executor.__class__.__name__, "SQLiteQueryExecutor")
        finally:
            path.unlink(missing_ok=True)

    def test_postgres_connection_builds_url(self) -> None:
        with patch("agent_os_api.executor_factory.PostgresQueryExecutor") as mock_cls:
            instance = MagicMock()
            mock_cls.return_value = instance
            provider = self._provider(
                ProviderConnection(
                    connection_type="postgresql",
                    host="db.example.com",
                    port=5432,
                    database="analytics",
                    username="user",
                    password="pass",
                )
            )
            ExecutorFactory.from_provider_contract(provider)
            mock_cls.assert_called_once()
            call_kwargs = mock_cls.call_args.kwargs
            self.assertIn(
                "postgresql://user:pass@db.example.com:5432/analytics", call_kwargs["database_url"]
            )

    def test_mysql_connection_builds_url(self) -> None:
        with patch("agent_os_api.executor_factory.MySqlQueryExecutor") as mock_cls:
            instance = MagicMock()
            mock_cls.return_value = instance
            provider = self._provider(
                ProviderConnection(
                    connection_type="mysql",
                    host="db.example.com",
                    port=3306,
                    database="analytics",
                    username="user",
                    password="pass",
                )
            )
            ExecutorFactory.from_provider_contract(provider)
            mock_cls.assert_called_once()
            call_kwargs = mock_cls.call_args.kwargs
            self.assertIn(
                "mysql+pymysql://user:pass@db.example.com:3306/analytics",
                call_kwargs["database_url"],
            )

    def test_clickhouse_connection_returns_clickhouse_executor(self) -> None:
        with patch("agent_os_api.executor_factory.ClickHouseQueryExecutor") as mock_cls:
            instance = MagicMock()
            mock_cls.return_value = instance
            provider = self._provider(
                ProviderConnection(
                    connection_type="clickhouse",
                    host="ch.example.com",
                    port=8123,
                    database="default",
                    username="default",
                    password="",
                )
            )
            ExecutorFactory.from_provider_contract(provider)
            mock_cls.assert_called_once()
            call_kwargs = mock_cls.call_args.kwargs
            self.assertEqual(call_kwargs["host"], "ch.example.com")
            self.assertEqual(call_kwargs["port"], 8123)

    def test_feishu_connection_requires_tokens(self) -> None:
        provider = self._provider(ProviderConnection(connection_type="feishu", app_token="app"))
        with self.assertRaises(ValueError):
            ExecutorFactory.from_provider_contract(provider)

    def test_feishu_connection_returns_feishu_executor(self) -> None:
        with patch("agent_os_api.executor_factory.FeishuQueryExecutor") as mock_cls:
            instance = MagicMock()
            mock_cls.return_value = instance
            provider = self._provider(
                ProviderConnection(
                    connection_type="feishu",
                    app_token="app",
                    table_id="table",
                    api_token="token",
                )
            )
            ExecutorFactory.from_provider_contract(provider)
            mock_cls.assert_called_once_with(
                app_token="app",
                table_id="table",
                api_token="token",
            )

    def test_unsupported_connection_type_raises(self) -> None:
        provider = self._provider(ProviderConnection(connection_type="mongodb"))
        with self.assertRaises(ValueError):
            ExecutorFactory.from_provider_contract(provider)


if __name__ == "__main__":
    unittest.main()
