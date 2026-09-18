"""SPINE-1: Data Agent query runtime — TemplateRegistry + generic executors (domain pack)."""

from __future__ import annotations

import sqlite3

import pytest

from domain_packs.data_agent.metric_contracts import QueryPlan, SQLTemplate
from domain_packs.data_agent.query_runtime import (
    CsvQueryExecutor,
    SQLiteQueryExecutor,
    StaticQueryExecutor,
    TemplateRegistry,
)


def _template(metric: str, template_id: str = "t") -> SQLTemplate:
    return SQLTemplate(template_id=template_id, metric_name=metric, sql="SELECT 1")


# --- TemplateRegistry ----------------------------------------------------------------


def test_registry_resolves_metric_keyed_template() -> None:
    registry = TemplateRegistry((_template("gmv", "t-gmv"), _template("roi", "t-roi")))

    assert registry.resolve("gmv").template_id == "t-gmv"
    assert registry.resolve("roi").template_id == "t-roi"
    assert set(registry.metrics()) == {"gmv", "roi"}


def test_registry_unregistered_metric_raises_without_default() -> None:
    registry = TemplateRegistry((_template("gmv"),))

    with pytest.raises(ValueError, match="No SQL template"):
        registry.resolve("unknown")


def test_registry_rejects_duplicate_metric() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        TemplateRegistry((_template("gmv", "a"), _template("gmv", "b")))


def test_registry_from_single_falls_back() -> None:
    registry = TemplateRegistry.from_single(_template("gmv", "only"))

    assert registry.resolve("anything").template_id == "only"


def test_registry_requires_a_template() -> None:
    with pytest.raises(ValueError, match="at least one template"):
        TemplateRegistry(())


# --- executors -----------------------------------------------------------------------


def test_static_executor_returns_rows_and_freshness() -> None:
    executor = StaticQueryExecutor(({"v": 1}, {"v": 2}), source_age_seconds=42.0)

    result = executor.execute(QueryPlan("gmv", "SELECT 1", {}))

    assert result.row_count == 2
    assert result.source_age_seconds == 42.0


def test_sqlite_executor_binds_named_parameters() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE orders(amount INTEGER)")
    connection.executemany("INSERT INTO orders(amount) VALUES (?)", [(10,), (20,), (30,)])
    executor = SQLiteQueryExecutor(connection)

    result = executor.execute(
        QueryPlan(
            "gmv",
            "SELECT SUM(amount) AS total FROM orders WHERE amount >= :min_amount",
            {"min_amount": 20},
        )
    )

    assert result.row_count == 1
    assert result.rows[0]["total"] == 50


def test_sqlite_executor_requires_exactly_one_source() -> None:
    with pytest.raises(ValueError):
        SQLiteQueryExecutor()
    with pytest.raises(ValueError):
        SQLiteQueryExecutor(sqlite3.connect(":memory:"), database="x.db")


def test_csv_executor_filters_by_bound_parameters(tmp_path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("channel,amount\nweb,10\napp,20\nweb,30\n", encoding="utf-8")
    executor = CsvQueryExecutor(csv_path)

    result = executor.execute(QueryPlan("gmv", "irrelevant", {"channel": "web"}))

    assert result.row_count == 2
    assert {row["amount"] for row in result.rows} == {"10", "30"}


def test_csv_executor_ignores_unmatched_parameters_and_supports_many(tmp_path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("channel,amount\nweb,10\napp,20\n", encoding="utf-8")
    executor = CsvQueryExecutor(csv_path)

    results = executor.execute_many(
        (QueryPlan("gmv", "x", {"time_window": "2026"}), QueryPlan("gmv", "x", {"channel": "app"}))
    )

    assert results[0].row_count == 2  # unmatched key ignored
    assert results[1].row_count == 1


def test_csv_executor_missing_file_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        CsvQueryExecutor(tmp_path / "nope.csv")
