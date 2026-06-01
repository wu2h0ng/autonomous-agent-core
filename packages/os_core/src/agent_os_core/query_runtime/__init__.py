from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agent_os_contracts import QueryPlan, QueryResult


class StaticQueryExecutor:
    """Deterministic test executor. Real providers must live outside OS Core."""

    def __init__(self, rows: Iterable[dict[str, Any]]) -> None:
        self._rows = tuple(rows)

    def execute(self, _plan: QueryPlan) -> QueryResult:
        return QueryResult(rows=self._rows, row_count=len(self._rows))
