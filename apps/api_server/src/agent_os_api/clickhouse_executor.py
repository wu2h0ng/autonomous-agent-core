"""ClickHouse query executor for the composition layer.

This executor lives in ``apps/api_server/`` (NOT in OS Core) because OS Core
must never import real database drivers.  It uses ``clickhouse-connect`` for
native ClickHouse query execution, exposing the same
``execute(query_plan) -> QueryResult`` interface as the other executors.

Read-only: only ``SELECT`` and ``WITH`` queries are accepted.  Mutation
statements are rejected before they reach the database.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_os_contracts import QueryPlan, QueryResult

from .postgres_executor import _MUTATION_PATTERN, _SELECT_PATTERN

logger = logging.getLogger(__name__)


try:
    from clickhouse_connect import get_client
    from clickhouse_connect.driver.client import Client
except ImportError as _import_error:  # pragma: no cover - optional dependency
    get_client = None  # type: ignore[assignment]
    Client = None  # type: ignore[assignment, misc]


class ClickHouseQueryExecutor:
    """Execute a :class:`QueryPlan` against ClickHouse via ``clickhouse-connect``.

    Parameters
    ----------
    host:
        ClickHouse server host.
    port:
        ClickHouse server HTTP port (default 8123).
    database:
        Default database/schema.
    username:
        ClickHouse username.
    password:
        ClickHouse password.
    client:
        An optional pre-built ``clickhouse_connect`` client (for tests or when
        the composition layer manages the client lifecycle externally).
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        database: str | None = None,
        username: str | None = None,
        password: str | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        if client is not None:
            self._client = client
            self._owns_client = False
            return
        if get_client is None:
            raise ImportError("ClickHouseQueryExecutor requires the 'clickhouse-connect' package.")
        self._client = get_client(
            host=host or "localhost",
            port=port or 8123,
            database=database,
            username=username,
            password=password,
        )
        self._owns_client = True

    @property
    def client(self) -> Any:
        return self._client

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def execute(self, query_plan: QueryPlan) -> QueryResult:
        sql = query_plan.sql

        if _MUTATION_PATTERN.match(sql):
            first_word = sql.strip().split()[0].upper()
            raise ValueError(
                "ClickHouseQueryExecutor is read-only; "
                f"rejected {first_word} statement: {sql[:120]!r}"
            )
        if not _SELECT_PATTERN.match(sql):
            raise ValueError(
                f"ClickHouseQueryExecutor requires a SELECT or WITH query; got: {sql[:120]!r}"
            )

        try:
            result = self._client.query(sql, parameters=dict(query_plan.parameters))
            columns = list(result.column_names)
            rows: tuple[dict[str, Any], ...] = tuple(
                dict(zip(columns, row)) for row in result.result_rows
            )
        except Exception:  # pragma: no cover - network failures
            logger.exception(
                "ClickHouseQueryExecutor query failed for metric %r",
                query_plan.metric_name,
            )
            return QueryResult(rows=(), row_count=0)

        return QueryResult(rows=rows, row_count=len(rows))
