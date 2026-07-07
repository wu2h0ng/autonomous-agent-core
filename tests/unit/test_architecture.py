"""Tests for architecture contracts."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))

from agent_os_contracts import (  # noqa: E402
    ProviderConnection,
    ProviderContract,
    ProviderKind,
)


class ProviderConnectionTest(unittest.TestCase):
    def test_connection_round_trip(self) -> None:
        connection = ProviderConnection(
            connection_type="csv",
            path="/data/orders.csv",
        )
        provider = ProviderContract(
            provider_id="csv-sales",
            kind=ProviderKind.FILE,
            name="local sales csv",
            owner="data",
            allowed_schemas=("sales",),
            connection=connection,
        )
        self.assertEqual(provider.connection.connection_type, "csv")
        self.assertEqual(provider.connection.path, "/data/orders.csv")

    def test_optional_secret_fields_default_to_none(self) -> None:
        connection = ProviderConnection(connection_type="postgresql", database="db")
        self.assertIsNone(connection.password)
        self.assertIsNone(connection.api_token)


if __name__ == "__main__":
    unittest.main()
