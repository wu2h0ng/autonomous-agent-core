"""Query runtime for the Data Agent: metric-keyed template resolution + generic executors.

Ported from the donor ``query_runtime`` package (``TemplateRegistry``, ``StaticQueryExecutor``,
``SQLiteQueryExecutor``, ``CsvQueryExecutor``). Imports the pack-native query contracts. The
executors are generic data-plane plumbing; the metric-keyed template registry carries the domain
semantics.
"""

from __future__ import annotations

import csv
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .metric_contracts import QueryPlan, QueryResult, SQLTemplate


class TemplateRegistry:
    """Resolve the ``SQLTemplate`` to use for a given metric.

    Strict mode (default) resolves a metric to its registered template and fails loudly for an
    unsupported metric. ``from_single`` returns one template that also acts as a fallback.
    """

    def __init__(
        self,
        templates: Iterable[SQLTemplate],
        *,
        default: SQLTemplate | None = None,
    ) -> None:
        by_metric: dict[str, SQLTemplate] = {}
        for template in templates:
            if template.metric_name in by_metric:
                raise ValueError(f"Duplicate SQL template for metric '{template.metric_name}'.")
            by_metric[template.metric_name] = template
        if not by_metric and default is None:
            raise ValueError("TemplateRegistry requires at least one template.")
        self._by_metric = by_metric
        self._default = default

    @classmethod
    def from_single(cls, template: SQLTemplate) -> TemplateRegistry:
        return cls((template,), default=template)

    def resolve(self, metric_name: str) -> SQLTemplate:
        template = self._by_metric.get(metric_name)
        if template is not None:
            return template
        if self._default is not None:
            return self._default
        raise ValueError(f"No SQL template registered for metric '{metric_name}'.")

    def metrics(self) -> tuple[str, ...]:
        return tuple(self._by_metric.keys())


class StaticQueryExecutor:
    """Deterministic executor returning a fixed set of rows."""

    def __init__(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        source_age_seconds: float | None = None,
    ) -> None:
        self._rows = tuple(rows)
        self._source_age_seconds = source_age_seconds

    def execute(self, _plan: QueryPlan) -> QueryResult:
        return QueryResult(
            rows=self._rows,
            row_count=len(self._rows),
            source_age_seconds=self._source_age_seconds,
        )


class SQLiteQueryExecutor:
    """Execute a ``QueryPlan`` against SQLite via stdlib ``sqlite3`` with named binding."""

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
            raise ValueError("Provide exactly one of 'connection' or 'database', not both.")
        if connection is None:
            connection = sqlite3.connect(database)  # type: ignore[arg-type]
        connection.row_factory = sqlite3.Row
        self._connection = connection

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def close(self) -> None:
        self._connection.close()

    def execute(self, query_plan: QueryPlan) -> QueryResult:
        cursor = self._connection.execute(query_plan.sql, dict(query_plan.parameters))
        try:
            rows: tuple[dict[str, Any], ...] = tuple(dict(row) for row in cursor.fetchall())
        finally:
            cursor.close()
        return QueryResult(rows=rows, row_count=len(rows))


class CsvQueryExecutor:
    """Execute a ``QueryPlan`` against a local CSV file (stdlib only).

    Parameters are bound as column-name -> exact-value filters; rows where every bound parameter
    matches are returned. Unmatched parameters are ignored (e.g. time-window hints).
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        if not self._path.exists():
            raise FileNotFoundError(f"CSV data file not found: {self._path}")

    @property
    def path(self) -> Path:
        return self._path

    def _read_rows(self) -> list[dict[str, Any]]:
        with self._path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            return [dict(row) for row in reader]

    def _matches(self, row: dict[str, Any], parameters: dict[str, Any]) -> bool:
        for key, value in parameters.items():
            if key in row and str(row[key]) != str(value):
                return False
        return True

    def execute(self, query_plan: QueryPlan) -> QueryResult:
        all_rows = self._read_rows()
        filtered = [row for row in all_rows if self._matches(row, dict(query_plan.parameters))]
        return QueryResult(rows=tuple(filtered), row_count=len(filtered))

    def execute_many(self, query_plans: Iterable[QueryPlan]) -> list[QueryResult]:
        all_rows = self._read_rows()
        results: list[QueryResult] = []
        for plan in query_plans:
            filtered = [row for row in all_rows if self._matches(row, dict(plan.parameters))]
            results.append(QueryResult(rows=tuple(filtered), row_count=len(filtered)))
        return results
