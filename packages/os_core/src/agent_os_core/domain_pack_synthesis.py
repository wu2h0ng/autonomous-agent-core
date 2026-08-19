"""Deterministic domain pack candidate synthesis (OS Core, driver-free).

Turns a read-only :class:`SchemaInventory` into typed pack candidates using
fixed heuristics — no LLM, no I/O, no drivers.  Every emitted candidate's
SQL is self-checked through the real DataSQLSafetyChecker with the proposed
schemas before it is returned: a candidate that cannot pass the gate is
never proposed.

Trust boundary: this module only *proposes*.  Schema allowlisting and pack
activation happen exclusively through the operator's explicit approval in
the composition layer.
"""

from __future__ import annotations

import hashlib
import re

from agent_os_contracts.domain_pack_synthesis import (
    PackCandidateMetric,
    SchemaInventory,
)

# Numeric column types eligible for SUM aggregation.
_NUMERIC_TYPES = frozenset(
    {
        "int",
        "integer",
        "tinyint",
        "smallint",
        "mediumint",
        "bigint",
        "float",
        "double",
        "real",
        "decimal",
        "numeric",
    }
)
_DATE_TYPES = frozenset({"date", "datetime", "timestamp"})

# Columns whose names match these patterns are never proposed as metric
# aggregations or dimensions (PII / credentials / opaque identifiers).
_EXCLUDED_COLUMN_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"收货人",
        r"收件人",
        r"手机",
        r"电话",
        r"详细地址",
        r"地址",
        r"身份证",
        r"密码",
        r"password",
        r"passwd",
        r"secret",
        r"token",
        r"cookie",
        r"email_code",
        r"图片",
        r"SN码",
        r"IMEI",
    )
)
_ID_COLUMN_PATTERN = re.compile(r"(?i)(^|_)(id|编号|单号|号码)$|^id$|ID$")


def _is_excluded(column_name: str) -> bool:
    if any(p.search(column_name) for p in _EXCLUDED_COLUMN_PATTERNS):
        return True
    return bool(_ID_COLUMN_PATTERN.search(column_name))


def _quote(name: str, dialect: str) -> str:
    q = "`" if dialect == "mysql" else '"'
    return f"{q}{name}{q}"


def _slug(text: str) -> str:
    if text.isascii():
        return re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_").lower()
    # Non-ASCII (e.g. Chinese) column names get a stable digest suffix so the
    # metric name stays ASCII-safe for downstream contracts.
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return f"col_{digest}"


def synthesize_pack_candidates(
    inventory: SchemaInventory,
    *,
    dialect: str = "mysql",
) -> tuple[PackCandidateMetric, ...]:
    """Propose SUM-per-numeric-column candidates from ``inventory``.

    Rules (deterministic):
      - one candidate per numeric, non-excluded column of each table;
      - the table must expose a date-like column to bound queries in time
        (otherwise the table is skipped — no unbounded candidates);
      - SQL is a fixed SELECT/GROUP-BY/LIMIT shape in the target dialect;
      - every SQL must pass DataSQLSafetyChecker(allowed_schemas=observed
        schemas, dialect=dialect) before being returned.
    """
    if dialect not in ("postgres", "mysql"):
        raise ValueError(f"Unsupported synthesis dialect: {dialect!r}")

    # Deferred import: DataSQLSafetyChecker lives in the data_agent domain
    # pack (not in os_core) to keep Agent Core domain-independent.
    from domain_packs.data_agent.sql_safety import DataSQLSafetyChecker

    candidates: list[PackCandidateMetric] = []
    for table in inventory.tables:
        date_col = next(
            (c.name for c in table.columns if c.data_type.lower() in _DATE_TYPES),
            None,
        )
        if date_col is None:
            continue
        agg_columns = [
            c.name
            for c in table.columns
            if c.data_type.lower() in _NUMERIC_TYPES and not _is_excluded(c.name)
        ]
        if not agg_columns:
            continue
        for agg in agg_columns:
            metric_name = f"{table.schema}_{table.table}_{_slug(agg)}_sum"
            template_id = f"{metric_name}_daily"
            sql = (
                f"select {_quote(date_col, dialect)}, "
                f"sum({_quote(agg, dialect)}) as value "
                f"from {_quote(table.schema, dialect)}.{_quote(table.table, dialect)} "
                f"where {_quote(date_col, dialect)} >= :start_date "
                f"and {_quote(date_col, dialect)} < :end_date "
                f"group by {_quote(date_col, dialect)} limit :limit"
            )
            checker = DataSQLSafetyChecker(
                allowed_schemas=(table.schema,),
                dialect=dialect,
            )
            safety = checker.check(
                sql,
                parameters={
                    "start_date": "2026-01-01",
                    "end_date": "2026-12-31",
                    "limit": 100,
                },
            )
            if not safety.allowed:
                # Fail closed: a candidate that cannot pass the safety gate is
                # never proposed for review.
                continue
            candidates.append(
                PackCandidateMetric(
                    metric_name=metric_name,
                    template_id=template_id,
                    display_name=f"SUM({agg}) daily",
                    definition=(
                        f"Daily sum of {agg} from {table.schema}.{table.table} "
                        f"within the selected time window "
                        f"(operator-reviewed candidate)."
                    ),
                    unit="unknown",
                    source_schema=table.schema,
                    source_table=table.table,
                    aggregation_column=agg,
                    time_column=date_col,
                    dimensions=(date_col,),
                    sql_dialect=dialect,
                    sql=sql,
                    rationale=(
                        f"numeric column ({agg}) on table with "
                        f"time column {date_col}"
                    ),
                )
            )
    return tuple(candidates)
