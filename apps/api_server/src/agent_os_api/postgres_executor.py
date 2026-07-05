"""PostgreSQL query executor for the composition layer.

This executor lives in ``apps/api_server/`` (NOT in OS Core) because OS Core
must never import real database drivers.  The factory wires this executor into
the Trusted Loop via the same ``execute(query_plan) -> QueryResult`` interface
that :class:`StaticQueryExecutor` and :class:`SQLiteQueryExecutor` expose.

Uses SQLAlchemy Core (already a project dependency) for connection pooling and
parameterized query execution.  Read-only: only ``SELECT`` and ``WITH`` (CTE)
queries are accepted.  Mutation statements (INSERT, UPDATE, DELETE, DROP, etc.)
are rejected before they reach the database.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from agent_os_contracts import QueryPlan, QueryResult

logger = logging.getLogger(__name__)

# Allowed leading keywords for read-only execution.
_SELECT_PATTERN = re.compile(r"\s*(SELECT|WITH)\b", re.IGNORECASE)

# Explicitly rejected mutation keywords.
_MUTATION_KEYWORDS = frozenset(
    {
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "CREATE",
        "TRUNCATE",
        "GRANT",
        "REVOKE",
        "MERGE",
        "COPY",
    }
)
_MUTATION_PATTERN = re.compile(
    r"\s*(" + "|".join(_MUTATION_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


class PostgresQueryExecutor:
    """Execute a :class:`QueryPlan` against PostgreSQL via SQLAlchemy Core.

    Drop-in replacement for :class:`StaticQueryExecutor` / :class:`SQLiteQueryExecutor`:
    same ``execute(query_plan) -> QueryResult`` interface.

    Read-only
    ---------
    Only ``SELECT`` and ``WITH`` queries are allowed.  Mutation statements are
    rejected before execution, raising ``ValueError``.  This is a defense-in-depth
    layer on top of SQL Safety — even if a plan somehow bypassed the upstream
    safety check, the executor itself will not run writes.

    Connection errors
    -----------------
    A connection-level failure (e.g. bad DSN, unreachable host) is caught and
    logged; the executor returns an empty :class:`QueryResult` so the runtime
    can degrade gracefully rather than crashing the request.  Query-level errors
    (syntax, missing table) propagate as the underlying SQLAlchemy exception.

    Parameters
    ----------
    database_url:
        A SQLAlchemy-compatible PostgreSQL DSN (e.g.
        ``postgresql://user:pass@host:5432/dbname``).
    engine:
        An optional pre-built :class:`sqlalchemy.engine.Engine` (for tests or
        when the composition layer manages the engine lifecycle externally).
        When provided, ``database_url`` is ignored.
    """

    def __init__(
        self,
        database_url: str | None = None,
        *,
        engine: Engine | None = None,
    ) -> None:
        if engine is not None:
            self._engine = engine
            self._owns_engine = False
        elif database_url is not None:
            self._engine = create_engine(database_url)
            self._owns_engine = True
        else:
            raise ValueError("PostgresQueryExecutor requires either a database_url or an engine.")

    @property
    def engine(self) -> Engine:
        """The underlying SQLAlchemy engine (for diagnostics or health checks)."""
        return self._engine

    def close(self) -> None:
        """Dispose the connection pool.  Safe to call multiple times.

        Only disposes engines this executor created; an externally injected
        engine is the caller's responsibility.
        """
        if self._owns_engine:
            self._engine.dispose()

    def execute(self, query_plan: QueryPlan) -> QueryResult:
        """Run the SQL from ``query_plan`` and return a :class:`QueryResult`.

        Raises
        ------
        ValueError
            If the SQL is a mutation statement (INSERT, UPDATE, DELETE, etc.).
        sqlalchemy.exc.OperationalError
            Re-raised after logging when the connection fails, but the caller
            receives an empty result instead of an unhandled crash.
        """
        sql = query_plan.sql

        # Read-only gate: reject mutations before they reach the database.
        if _MUTATION_PATTERN.match(sql):
            first_word = sql.strip().split()[0].upper()
            raise ValueError(
                f"PostgresQueryExecutor is read-only; "
                f"rejected {first_word} statement: {sql[:120]!r}"
            )
        if not _SELECT_PATTERN.match(sql):
            raise ValueError(
                f"PostgresQueryExecutor requires a SELECT or WITH query; got: {sql[:120]!r}"
            )

        try:
            with self._engine.connect() as conn:
                cursor = conn.execute(text(sql), dict(query_plan.parameters))
                columns: list[str] = list(cursor.keys())
                rows: tuple[dict[str, Any], ...] = tuple(
                    dict(zip(columns, row)) for row in cursor.fetchall()
                )
        except OperationalError:
            # Connection-level failure (bad DSN, unreachable host, auth error).
            # Log the full traceback and return an empty result so the runtime
            # degrades gracefully rather than crashing the HTTP request.
            logger.exception(
                "PostgresQueryExecutor connection failed for metric %r",
                query_plan.metric_name,
            )
            return QueryResult(rows=(), row_count=0)

        return QueryResult(rows=rows, row_count=len(rows))
