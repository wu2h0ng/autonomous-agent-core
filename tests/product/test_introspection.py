"""Tests for read-only warehouse introspection (composition layer).

Verifies that introspection maps MySqlDataQueryCapability results into a
typed SchemaInventory, fails loudly on empty schemas, and never reads data
rows.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from apps.api_server.introspection import introspect_mysql


class _FakeEffect:
    def __init__(self, status: str, output: dict[str, Any] | None = None, error_code: str | None = None, detail_ref: str | None = None) -> None:
        self.status = MagicMock()
        self.status.value = status
        self.output = output or {}
        self.error_code = error_code
        self.detail_ref = detail_ref


class _FakeCapability:
    def __init__(self, rows_by_schema: dict[str, list[dict[str, Any]]]) -> None:
        self._rows_by_schema = rows_by_schema
        self.calls: list[str] = []

    def execute(self, action: Any) -> _FakeEffect:
        payload = json.loads(action.arguments_json)
        schema = payload["parameters"]["schema_name"]
        self.calls.append(schema)
        rows = self._rows_by_schema.get(schema, [])
        if not rows:
            return _FakeEffect(
                "FAILED",
                error_code="QUERY_EXECUTION_FAILED",
                detail_ref="detail:data-query:empty",
            )
        return _FakeEffect(
            "SUCCEEDED",
            output={"rows_json": json.dumps(rows)},
        )


class TestIntrospectMysql:
    def test_maps_columns_to_inventory(self) -> None:
        rows = [
            {"table_schema": "adstable", "table_name": "ads_profit_order", "column_name": "日期", "data_type": "date"},
            {"table_schema": "adstable", "table_name": "ads_profit_order", "column_name": "GMV", "data_type": "decimal"},
            {"table_schema": "adstable", "table_name": "ads_profit_order", "column_name": "订单数", "data_type": "bigint"},
        ]
        capability = _FakeCapability({"adstable": rows})
        inventory = introspect_mysql(capability, ("adstable",))
        assert len(inventory.tables) == 1
        table = inventory.tables[0]
        assert table.schema == "adstable"
        assert table.table == "ads_profit_order"
        assert len(table.columns) == 3
        names = [c.name for c in table.columns]
        assert "日期" in names
        assert "GMV" in names
        assert "订单数" in names

    def test_multiple_schemas(self) -> None:
        rows_a = [
            {"table_schema": "adstable", "table_name": "t1", "column_name": "dt", "data_type": "date"},
        ]
        rows_b = [
            {"table_schema": "dwdtable", "table_name": "t2", "column_name": "amount", "data_type": "float"},
        ]
        capability = _FakeCapability({"adstable": rows_a, "dwdtable": rows_b})
        inventory = introspect_mysql(capability, ("adstable", "dwdtable"))
        assert len(inventory.tables) == 2
        assert capability.calls == ["adstable", "dwdtable"]

    def test_empty_schema_fails_loudly(self) -> None:
        capability = _FakeCapability({"adstable": []})
        with pytest.raises(ValueError, match="introspection failed for schema"):
            introspect_mysql(capability, ("adstable",))

    def test_no_schemas_fails_closed(self) -> None:
        capability = _FakeCapability({})
        with pytest.raises(ValueError, match="at least one schema"):
            introspect_mysql(capability, ())

    def test_capability_failure_propagates(self) -> None:
        capability = _FakeCapability({"adstable": []})
        with pytest.raises(ValueError, match="introspection failed"):
            introspect_mysql(capability, ("adstable",))
