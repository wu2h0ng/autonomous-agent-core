"""Feishu Bitable (多维表格) query executor for the composition layer.

This executor lives in ``apps/api_server/`` (NOT in OS Core) because OS Core
must never import HTTP clients.  It reads records from a Feishu Bitable table
via the public API and returns them as a :class:`QueryResult`, exposing the same
``execute(query_plan) -> QueryResult`` interface as the other executors.

The bound parameters in ``query_plan.parameters`` are used as exact-match
filters on record fields.  Only ``SELECT``-style reads are supported; any SQL
plan that looks like a mutation is rejected.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_os_contracts import QueryPlan, QueryResult

from .postgres_executor import _MUTATION_PATTERN, _SELECT_PATTERN

logger = logging.getLogger(__name__)


try:
    import httpx
except ImportError as _import_error:  # pragma: no cover - optional dependency
    httpx = None  # type: ignore[assignment]


class FeishuQueryExecutor:
    """Execute a :class:`QueryPlan` against a Feishu Bitable table.

    Parameters
    ----------
    app_token:
        Feishu Bitable ``app_token`` (the spreadsheet identifier).
    table_id:
        Feishu Bitable ``table_id``.
    api_token:
        Feishu tenant/personal access token.
    base_url:
        Feishu API base URL (default ``https://open.feishu.cn/open-apis``).
    """

    _DEFAULT_BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(
        self,
        app_token: str,
        table_id: str,
        api_token: str,
        base_url: str | None = None,
    ) -> None:
        if httpx is None:
            raise ImportError("FeishuQueryExecutor requires the 'httpx' package.")
        self._app_token = app_token
        self._table_id = table_id
        self._api_token = api_token
        self._base_url = (base_url or self._DEFAULT_BASE_URL).rstrip("/")

    def execute(self, query_plan: QueryPlan) -> QueryResult:
        sql = query_plan.sql

        if _MUTATION_PATTERN.match(sql):
            first_word = sql.strip().split()[0].upper()
            raise ValueError(
                f"FeishuQueryExecutor is read-only; rejected {first_word} statement: {sql[:120]!r}"
            )
        if not _SELECT_PATTERN.match(sql):
            raise ValueError(
                f"FeishuQueryExecutor requires a SELECT-style read; got: {sql[:120]!r}"
            )

        url = f"{self._base_url}/bitable/v1/apps/{self._app_token}/tables/{self._table_id}/records"
        try:
            response = httpx.get(
                url,
                headers={"Authorization": f"Bearer {self._api_token}"},
                timeout=30.0,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:  # pragma: no cover - network failures
            logger.exception(
                "FeishuQueryExecutor request failed for metric %r",
                query_plan.metric_name,
            )
            return QueryResult(rows=(), row_count=0)

        items = payload.get("data", {}).get("items", [])
        parameters = dict(query_plan.parameters)
        rows: list[dict[str, Any]] = []
        for item in items:
            fields = item.get("fields", {})
            flat: dict[str, Any] = {"record_id": item.get("record_id")}
            for key, value in fields.items():
                # Feishu fields are often {"text": "..."} or primitive; flatten lightly.
                if isinstance(value, dict):
                    flat[key] = value.get("text", value.get("value", value))
                else:
                    flat[key] = value
            # Apply exact-match filters from bound parameters.
            if all(
                key not in flat or str(flat[key]) == str(value) for key, value in parameters.items()
            ):
                rows.append(flat)

        return QueryResult(rows=tuple(rows), row_count=len(rows))
