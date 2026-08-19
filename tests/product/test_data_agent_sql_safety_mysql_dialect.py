"""MySQL dialect gate for the Data Agent AST SQL safety checker.

Real MySQL warehouses (Customer-0 Minhe Alibaba RDS) use backtick-quoted
non-ASCII identifiers.  The checker must parse templates in the dialect of
the target engine instead of the hard-coded postgres dialect while keeping
every policy rule intact, and must fail closed on unknown dialects.
"""

from __future__ import annotations

import pytest

from domain_packs.data_agent.runtime import DataSQLSafetyChecker


MYSQL_SQL = (
    "select `日期`, `店铺名称`, sum(`GMV`) as gmv "
    "from `adstable`.`ads_profit_order` "
    "where `日期` >= :start_date and `日期` < :end_date "
    "group by `日期`, `店铺名称` limit :limit"
)

PARAMS = {"start_date": "2026-08-01", "end_date": "2026-08-19", "limit": 100}


@pytest.fixture
def mysql_checker() -> DataSQLSafetyChecker:
    return DataSQLSafetyChecker(("adstable",), dialect="mysql")


def test_mysql_dialect_allows_backtick_non_ascii_columns(
    mysql_checker: DataSQLSafetyChecker,
) -> None:
    result = mysql_checker.check(
        MYSQL_SQL,
        ("start_date", "end_date", "limit"),
        PARAMS,
    )

    assert result.allowed, result.reasons
    assert result.checked_tables == ("adstable.ads_profit_order",)
    assert result.bound_parameters == ("end_date", "limit", "start_date")
    assert result.limit_value == 100


def test_mysql_dialect_still_blocks_write(mysql_checker: DataSQLSafetyChecker) -> None:
    result = mysql_checker.check(
        "update `adstable`.`ads_profit_order` set `GMV` = 0 where `日期` >= :start_date",
        ("start_date",),
        {"start_date": "2026-08-01"},
    )

    assert not result.allowed
    assert "NO_WRITE_OR_DDL" in {issue.code for issue in result.issues}


def test_mysql_dialect_enforces_schema_allowlist() -> None:
    checker = DataSQLSafetyChecker(("dwdtable",), dialect="mysql")
    result = checker.check(MYSQL_SQL, ("start_date", "end_date", "limit"), PARAMS)

    assert not result.allowed
    assert "SCHEMA_ALLOWLIST" in {issue.code for issue in result.issues}


def test_default_postgres_dialect_rejects_backtick_sql() -> None:
    """The dialect parameter is load-bearing: the historical default cannot
    parse real MySQL templates, which is exactly what blocks MySQL providers
    today (fail closed)."""
    checker = DataSQLSafetyChecker(("adstable",))
    result = checker.check(MYSQL_SQL, ("start_date", "end_date", "limit"), PARAMS)

    assert not result.allowed
    assert "PARSE_ERROR" in {issue.code for issue in result.issues}


def test_unknown_dialect_fails_closed() -> None:
    with pytest.raises(ValueError, match="dialect"):
        DataSQLSafetyChecker(("adstable",), dialect="bigquery")


def test_mysql_dialect_enforces_limit(mysql_checker: DataSQLSafetyChecker) -> None:
    result = mysql_checker.check(
        MYSQL_SQL.replace(" limit :limit", ""),
        ("start_date", "end_date"),
        {"start_date": "2026-08-01", "end_date": "2026-08-19"},
    )

    assert not result.allowed
    assert "MISSING_LIMIT" in {issue.code for issue in result.issues}
