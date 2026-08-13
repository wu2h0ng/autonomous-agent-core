from __future__ import annotations

import pytest

from domain_packs.data_agent.runtime import DataAgentDenied, DataSQLSafetyChecker


@pytest.fixture
def checker() -> DataSQLSafetyChecker:
    return DataSQLSafetyChecker(("sales",), max_limit=1_000)


def test_ast_gate_allows_allowlisted_parameterized_read(
    checker: DataSQLSafetyChecker,
) -> None:
    result = checker.check(
        "select order_date, sum(paid_amount) as gmv from sales.orders "
        "where order_date >= :start_date and order_date < :end_date limit :limit",
        ("start_date", "end_date", "limit"),
        {"start_date": "2026-01-01", "end_date": "2026-02-01", "limit": 100},
    )

    assert result.allowed
    assert result.checked_schemas == ("sales",)
    assert result.checked_tables == ("sales.orders",)
    assert result.limit_value == 100


@pytest.mark.parametrize(
    ("sql", "expected_code"),
    [
        ("delete from sales.orders where id = :id", "NO_WRITE_OR_DDL"),
        (
            "select amount from sales.orders where id = :id limit 10; "
            "delete from sales.orders",
            "SINGLE_STATEMENT",
        ),
        (
            "select amount from sales.orders -- hidden\nwhere id = :id limit 10",
            "NO_SQL_COMMENTS",
        ),
        (
            "select amount from sales.orders where id = :id union "
            "select password from sales.users limit 10",
            "NO_UNION",
        ),
        ("select distinct * from sales.orders limit 10", "NO_SELECT_STAR"),
        ("select o.* from sales.orders o limit 10", "NO_SELECT_STAR"),
        ("select amount from finance.payments limit 10", "SCHEMA_ALLOWLIST"),
        ("select amount from orders limit 10", "SCHEMA_QUALIFIED_TABLE"),
        ("select amount from sales.orders", "MISSING_LIMIT"),
        ("select amount from sales.orders limit -1", "LIMIT_TOO_LOW"),
        ("select amount from sales.orders limit 1001", "LIMIT_TOO_HIGH"),
        (
            "select a from (select b from (select c from (select d from sales.orders) "
            "t3) t2) t1 limit 10",
            "SUBQUERY_TOO_DEEP",
        ),
    ],
)
def test_ast_gate_blocks_frozen_bypass_classes(
    checker: DataSQLSafetyChecker,
    sql: str,
    expected_code: str,
) -> None:
    result = checker.check(
        sql,
        tuple(),
        {"id": "x"} if ":id" in sql else {},
        required_time_parameters=tuple(),
    )

    assert not result.allowed
    assert expected_code in {issue.code for issue in result.issues}


@pytest.mark.parametrize(
    ("sql", "expected_code"),
    [
        ("PRAGMA table_info('orders')", "ONLY_SELECT"),
        ("ATTACH DATABASE 'other.db' AS other", "PARSE_ERROR"),
        ("DETACH DATABASE other", "PARSE_ERROR"),
        (
            "CREATE VIRTUAL TABLE sales.search USING fts5(content)",
            "ONLY_SELECT",
        ),
        ("VACUUM", "ONLY_SELECT"),
        ("REINDEX sales.orders", "ONLY_SELECT"),
        ("CREATE INDEX idx_amount ON sales.orders(amount)", "ONLY_SELECT"),
        ("DROP INDEX idx_amount", "ONLY_SELECT"),
        ("CREATE VIEW sales.order_view AS SELECT 1", "ONLY_SELECT"),
        ("DROP VIEW sales.order_view", "ONLY_SELECT"),
        (
            "SELECT amount /* hidden */ FROM sales.orders LIMIT 10",
            "NO_SQL_COMMENTS",
        ),
    ],
)
def test_ast_gate_blocks_sqlite_specific_ddl_and_block_comments(
    checker: DataSQLSafetyChecker,
    sql: str,
    expected_code: str,
) -> None:
    result = checker.check(
        sql,
        tuple(),
        {},
        required_time_parameters=tuple(),
    )

    assert not result.allowed
    assert expected_code in {issue.code for issue in result.issues}


def test_ast_gate_rejects_missing_and_unused_runtime_parameters(
    checker: DataSQLSafetyChecker,
) -> None:
    missing = checker.check(
        "select amount from sales.orders where id = :id limit :limit",
        ("id", "limit"),
        {"id": "x"},
        required_time_parameters=tuple(),
    )
    unused = checker.check(
        "select amount from sales.orders where id = :id limit 10",
        ("id",),
        {"id": "x", "attacker": "ignored"},
        required_time_parameters=tuple(),
    )

    assert "MISSING_RUNTIME_PARAMETER" in {issue.code for issue in missing.issues}
    assert "UNUSED_RUNTIME_PARAMETER" in {issue.code for issue in unused.issues}


def test_assert_safe_projects_typed_denial(checker: DataSQLSafetyChecker) -> None:
    with pytest.raises(DataAgentDenied, match=r"SQL_SAFETY_DENIED:.*NO_UNION"):
        checker.assert_safe(
            "select amount from sales.orders union select secret from sales.users limit 10",
            {},
        )
