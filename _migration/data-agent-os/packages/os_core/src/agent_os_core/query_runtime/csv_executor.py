"""CSV query executor for the Trusted Loop.

Executes a :class:`QueryPlan` against a local CSV file using only the stdlib
``csv`` module.  The SQL in the plan is intentionally *not* parsed; instead, the
executor filters rows by exact equality on the bound parameters and returns the
matching rows.  This keeps OS Core dependency-free while giving a real,
reviewable data plane for demos and Customer-0 local data.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from agent_os_contracts import QueryPlan, QueryResult


class CsvQueryExecutor:
    """Execute a ``QueryPlan`` against a local CSV file.

    Parameters are bound as column-name -> exact-value filters.  Only rows where
    every bound parameter equals the corresponding column value are returned.
    Unmatched parameters are ignored (they may be time-window hints that the
    caller resolves elsewhere).  The entire result set is materialized in memory,
    so this executor is suitable for small-to-medium local files only.
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
        """Execute multiple plans against the same CSV file efficiently."""
        all_rows = self._read_rows()
        results: list[QueryResult] = []
        for plan in query_plans:
            filtered = [row for row in all_rows if self._matches(row, dict(plan.parameters))]
            results.append(QueryResult(rows=tuple(filtered), row_count=len(filtered)))
        return results
