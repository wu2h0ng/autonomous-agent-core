from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from typing import Any

from agent_os_contracts import QueryPlan, QueryResult


class StaticQueryExecutor:
    """Deterministic test executor. Real providers must live outside OS Core."""

    def __init__(self, rows: Iterable[dict[str, Any]]) -> None:
        self._rows = tuple(rows)

    def execute(self, _plan: QueryPlan) -> QueryResult:
        return QueryResult(rows=self._rows, row_count=len(self._rows))


class SQLiteQueryExecutor:
    """Execute a ``QueryPlan`` against a real SQLite engine via stdlib ``sqlite3``.

    This is a drop-in replacement for :class:`StaticQueryExecutor`: it exposes the
    same ``execute(query_plan) -> QueryResult`` interface, so the runtime can inject
    either via dependency injection without any change to control flow.

    OS Core stays domain-independent: this is a *generic* SQL executor. It contains
    no customer-specific data, schema, or metric logic. The caller owns the data
    source — pass an already-open ``sqlite3.Connection`` (the "ride the data plane
    behind ProviderContract" boundary) or a database path/URI that this executor
    opens itself. No new third-party dependencies are introduced.

    Parameter binding uses sqlite3 named-parameter binding, so a plan whose SQL
    references ``:start_date``, ``:end_date``, ``:limit`` etc. is bound from
    ``query_plan.parameters`` rather than string-formatted (no SQL injection, and
    the parameters provably affect the computed result).
    """

    def __init__(
        self,
        connection: sqlite3.Connection | None = None,
        *,
        database: str | None = None,
    ) -> None:
        if connection is None and database is None:
            raise ValueError(
                "SQLiteQueryExecutor requires either a sqlite3 connection or a database path."
            )
        if connection is not None and database is not None:
            raise ValueError(
                "Provide exactly one of 'connection' or 'database', not both."
            )
        if connection is None:
            connection = sqlite3.connect(database)  # type: ignore[arg-type]
        # row_factory=sqlite3.Row preserves real column names for QueryResult mapping.
        connection.row_factory = sqlite3.Row
        self._connection = connection

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def close(self) -> None:
        """Close the underlying connection. Safe to call multiple times."""
        self._connection.close()

    def execute(self, query_plan: QueryPlan) -> QueryResult:
        cursor = self._connection.execute(query_plan.sql, dict(query_plan.parameters))
        try:
            fetched = cursor.fetchall()
            rows: tuple[dict[str, Any], ...] = tuple(dict(row) for row in fetched)
        finally:
            cursor.close()
        return QueryResult(rows=rows, row_count=len(rows))
