"""MySQL query executor for the composition layer.

This executor lives in ``apps/api_server/`` (NOT in OS Core) because OS Core
must never import real database drivers.  It uses SQLAlchemy Core for
connection pooling and parameterized query execution, matching the interface of
:class:`PostgresQueryExecutor`.

Read-only: only ``SELECT`` and ``WITH`` (CTE) queries are accepted.  Mutation
statements are rejected before they reach the database.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_os_contracts import QueryPlan, QueryResult

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import Engine
    from sqlalchemy.exc import OperationalError
except ImportError as _import_error:  # pragma: no cover - optional dependency
    create_engine = None  # type: ignore[assignment]
    text = None  # type: ignore[assignment]
    Engine = None  # type: ignore[assignment, misc]
    OperationalError = Exception  # type: ignore[assignment, misc]

from .postgres_executor import _MUTATION_PATTERN, _SELECT_PATTERN

logger = logging.getLogger(__name__)


class MySqlQueryExecutor:
    """Execute a :class:`QueryPlan` against MySQL via SQLAlchemy Core.

    Drop-in replacement for :class:`PostgresQueryExecutor`.

    Parameters
    ----------
    database_url:
        A SQLAlchemy-compatible MySQL DSN (e.g.
        ``mysql+pymysql://user:pass@host:3306/dbname``).  The ``pymysql`` driver
        must be installed separately.
    engine:
        An optional pre-built :class:`sqlalchemy.engine.Engine`.
    """

    def __init__(
        self,
        database_url: str | None = None,
        *,
        engine: Any | None = None,
    ) -> None:
        if create_engine is None:
            raise ImportError(
                "MySqlQueryExecutor requires 'sqlalchemy' and a MySQL driver such as pymysql."
            )
        if engine is not None:
            self._engine = engine
            self._owns_engine = False
        elif database_url is not None:
            self._engine = create_engine(database_url)
            self._owns_engine = True
        else:
            raise ValueError("MySqlQueryExecutor requires either a database_url or an engine.")

    @property
    def engine(self) -> Any:
        return self._engine

    def close(self) -> None:
        if self._owns_engine:
            self._engine.dispose()

    def execute(self, query_plan: QueryPlan) -> QueryResult:
        sql = query_plan.sql

        if _MUTATION_PATTERN.match(sql):
            first_word = sql.strip().split()[0].upper()
            raise ValueError(
                f"MySqlQueryExecutor is read-only; rejected {first_word} statement: {sql[:120]!r}"
            )
        if not _SELECT_PATTERN.match(sql):
            raise ValueError(
                f"MySqlQueryExecutor requires a SELECT or WITH query; got: {sql[:120]!r}"
            )

        try:
            with self._engine.connect() as conn:
                cursor = conn.execute(text(sql), dict(query_plan.parameters))
                columns = list(cursor.keys())
                rows: tuple[dict[str, Any], ...] = tuple(
                    dict(zip(columns, row)) for row in cursor.fetchall()
                )
        except OperationalError:
            logger.exception(
                "MySqlQueryExecutor connection failed for metric %r",
                query_plan.metric_name,
            )
            return QueryResult(rows=(), row_count=0)

        return QueryResult(rows=rows, row_count=len(rows))
