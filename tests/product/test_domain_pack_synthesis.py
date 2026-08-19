"""Tests for deterministic domain pack candidate synthesis (OS Core).

Verifies the synthesis rules: numeric-column candidates, date-column
requirement, PII exclusion, SQL safety self-check, and dialect handling.
No I/O, no drivers, no network.
"""

from __future__ import annotations

import pytest

from agent_os_contracts.domain_pack_synthesis import (
    ColumnInventory,
    SchemaInventory,
    TableInventory,
)
from agent_os_core.domain_pack_synthesis import synthesize_pack_candidates


def _table(
    schema: str = "adstable",
    table: str = "ads_profit_order",
    columns: tuple[ColumnInventory, ...] = (),
) -> TableInventory:
    return TableInventory(schema=schema, table=table, columns=columns)


def _col(name: str, data_type: str) -> ColumnInventory:
    return ColumnInventory(name=name, data_type=data_type)


class TestSynthesizePackCandidates:
    def test_numeric_column_with_date_produces_candidate(self) -> None:
        inventory = SchemaInventory(
            tables=(
                _table(
                    columns=(
                        _col("日期", "date"),
                        _col("GMV", "decimal"),
                        _col("订单数", "bigint"),
                    )
                ),
            )
        )
        candidates = synthesize_pack_candidates(inventory, dialect="mysql")
        assert len(candidates) == 2
        names = {c.metric_name for c in candidates}
        assert "adstable_ads_profit_order_gmv_sum" in names  # GMV is ASCII
        assert "adstable_ads_profit_order_col_e56cb275_sum" in names  # 订单数 slug

    def test_table_without_date_column_is_skipped(self) -> None:
        inventory = SchemaInventory(
            tables=(
                _table(
                    columns=(
                        _col("GMV", "decimal"),
                        _col("订单数", "bigint"),
                    )
                ),
            )
        )
        candidates = synthesize_pack_candidates(inventory, dialect="mysql")
        assert candidates == ()

    def test_pii_columns_are_excluded(self) -> None:
        inventory = SchemaInventory(
            tables=(
                _table(
                    columns=(
                        _col("日期", "date"),
                        _col("GMV", "decimal"),
                        _col("收货人", "varchar"),
                        _col("手机", "varchar"),
                        _col("密码", "varchar"),
                    )
                ),
            )
        )
        candidates = synthesize_pack_candidates(inventory, dialect="mysql")
        assert len(candidates) == 1
        assert "GMV" in candidates[0].aggregation_column

    def test_id_columns_are_excluded(self) -> None:
        inventory = SchemaInventory(
            tables=(
                _table(
                    columns=(
                        _col("日期", "date"),
                        _col("id", "bigint"),
                        _col("订单编号", "varchar"),
                        _col("GMV", "decimal"),
                    )
                ),
            )
        )
        candidates = synthesize_pack_candidates(inventory, dialect="mysql")
        assert len(candidates) == 1
        assert candidates[0].aggregation_column == "GMV"

    def test_non_numeric_columns_are_excluded(self) -> None:
        inventory = SchemaInventory(
            tables=(
                _table(
                    columns=(
                        _col("日期", "date"),
                        _col("平台", "varchar"),
                        _col("GMV", "decimal"),
                    )
                ),
            )
        )
        candidates = synthesize_pack_candidates(inventory, dialect="mysql")
        assert len(candidates) == 1
        assert candidates[0].aggregation_column == "GMV"

    def test_sql_passes_safety_gate(self) -> None:
        inventory = SchemaInventory(
            tables=(
                _table(
                    columns=(
                        _col("日期", "date"),
                        _col("GMV", "decimal"),
                    )
                ),
            )
        )
        candidates = synthesize_pack_candidates(inventory, dialect="mysql")
        assert len(candidates) == 1
        sql = candidates[0].sql
        assert "select" in sql.lower()
        assert "limit :limit" in sql
        assert "`adstable`.`ads_profit_order`" in sql
        assert ":start_date" in sql
        assert ":end_date" in sql

    def test_postgres_dialect_uses_double_quotes(self) -> None:
        inventory = SchemaInventory(
            tables=(
                _table(
                    columns=(
                        _col("date", "date"),
                        _col("revenue", "numeric"),
                    )
                ),
            )
        )
        candidates = synthesize_pack_candidates(inventory, dialect="postgres")
        assert len(candidates) == 1
        assert '"adstable"."ads_profit_order"' in candidates[0].sql

    def test_unknown_dialect_fails_closed(self) -> None:
        inventory = SchemaInventory(tables=())
        with pytest.raises(ValueError, match="Unsupported synthesis dialect"):
            synthesize_pack_candidates(inventory, dialect="oracle")

    def test_empty_inventory_produces_no_candidates(self) -> None:
        inventory = SchemaInventory(tables=())
        candidates = synthesize_pack_candidates(inventory, dialect="mysql")
        assert candidates == ()

    def test_multiple_tables_produce_multiple_candidates(self) -> None:
        inventory = SchemaInventory(
            tables=(
                _table(
                    schema="adstable",
                    table="ads_profit_order",
                    columns=(
                        _col("日期", "date"),
                        _col("GMV", "decimal"),
                    ),
                ),
                _table(
                    schema="dwdtable",
                    table="dwd_order_detail",
                    columns=(
                        _col("dt", "date"),
                        _col("amount", "float"),
                    ),
                ),
            )
        )
        candidates = synthesize_pack_candidates(inventory, dialect="mysql")
        assert len(candidates) == 2
        schemas = {c.source_schema for c in candidates}
        assert schemas == {"adstable", "dwdtable"}
