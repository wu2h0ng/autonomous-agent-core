"""Secret-free loading and validation of materialized domain packs.

A materialized pack (``providers.json`` / ``metrics.json`` /
``sql_templates.json`` / ``manifest.yaml``) is inert data until this module
turns one operator-approved metric into a validated :class:`PackQuery`.
Every consistency check fails closed: unknown metric, template drift,
inline secrets, missing parameters, unsafe SQL or unsupported dialects
raise ``ValueError`` with a stable ``CODE:`` prefix and nothing executes.

This module performs no I/O beyond reading the pack directory and never
touches a database driver, network or environment secret value.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_os_contracts.common import canonical_json

from .sql_safety import DataSQLSafetyChecker

_SECRET_FIELDS = ("password", "api_token")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class PackQuery:
    """One validated, execution-ready metric query from a pack."""

    metric_name: str
    metric_version: str
    metric_contract_digest: str
    template_id: str
    sql: str
    parameters: dict[str, Any]
    provider_id: str
    allowed_schemas: tuple[str, ...]
    connection: dict[str, Any]
    sql_dialect: str


def _fail(code: str, detail: str) -> ValueError:
    return ValueError(f"{code}: {detail}")


def _load_json(path: Path, code: str) -> Any:
    if not path.is_file():
        raise _fail(code, f"required pack file is missing: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _fail(code, f"{path.name} is not valid JSON: {exc}") from exc


def _manifest_metrics(manifest_path: Path) -> tuple[str, tuple[str, ...], str]:
    """Parse the generated manifest: state, metric_contracts, version."""
    if not manifest_path.is_file():
        raise _fail("PACK_MANIFEST_MISSING", "manifest.yaml is missing")
    lines = manifest_path.read_text(encoding="utf-8").splitlines()
    state = None
    version = None
    metrics: list[str] = []
    in_metrics = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("version:") and version is None:
            version = stripped.split(":", 1)[1].strip()
        if stripped == "metric_contracts:":
            in_metrics = True
            continue
        if in_metrics:
            if stripped.startswith("- "):
                metrics.append(stripped[2:].strip())
                continue
            in_metrics = False
        if stripped.startswith("state:"):
            state = stripped.split(":", 1)[1].strip()
    if state != "active":
        raise _fail("PACK_NOT_ACTIVE", f"manifest state is {state!r}, expected 'active'")
    if version is None:
        raise _fail("PACK_MANIFEST_INVALID", "manifest version is missing")
    return state, tuple(metrics), version


def load_pack_query(
    pack_dir: Path,
    metric_name: str,
    *,
    start_date: str,
    end_date: str,
    limit: int | None = None,
) -> PackQuery:
    """Load and fully validate one approved metric from ``pack_dir``.

    Fail-closed codes: PACK_DIR_MISSING, PACK_FILE_MISSING,
    PACK_MANIFEST_MISSING, PACK_NOT_ACTIVE, PACK_MANIFEST_INVALID,
    METRIC_NOT_APPROVED, METRIC_ROW_INVALID, VERIFIED_QUERY_AMBIGUOUS,
    TEMPLATE_MISSING, TEMPLATE_METRIC_MISMATCH, TEMPLATE_SQL_DRIFT,
    PARAMETER_INVALID, PROVIDER_AMBIGUOUS, PROVIDER_ROW_INVALID,
    CONNECTION_INLINE_SECRET, CONNECTION_FIELD_MISSING, DIALECT_UNSUPPORTED,
    SQL_SAFETY_DENIED.
    """
    pack_dir = Path(pack_dir)
    if not pack_dir.is_dir():
        raise _fail("PACK_DIR_MISSING", f"pack dir does not exist: {pack_dir}")

    _, manifest_metrics, manifest_version = _manifest_metrics(
        pack_dir / "manifest.yaml"
    )
    if metric_name not in manifest_metrics:
        raise _fail(
            "METRIC_NOT_APPROVED",
            f"{metric_name!r} is not listed in manifest metric_contracts",
        )

    metrics_rows = _load_json(pack_dir / "metrics.json", "PACK_FILE_MISSING")
    templates_rows = _load_json(pack_dir / "sql_templates.json", "PACK_FILE_MISSING")
    providers_rows = _load_json(pack_dir / "providers.json", "PACK_FILE_MISSING")
    if (
        not isinstance(metrics_rows, list)
        or not isinstance(templates_rows, list)
        or not isinstance(providers_rows, list)
    ):
        raise _fail("PACK_FILE_INVALID", "pack JSON files must encode arrays")

    metric = next((m for m in metrics_rows if m.get("metric_name") == metric_name), None)
    if metric is None:
        raise _fail(
            "METRIC_NOT_APPROVED",
            f"{metric_name!r} has no row in metrics.json",
        )
    verified = metric.get("verified_queries")
    if not isinstance(verified, list) or len(verified) != 1:
        raise _fail(
            "VERIFIED_QUERY_AMBIGUOUS",
            f"{metric_name!r} must carry exactly one verified query template",
        )
    template_id = verified[0].get("template_id")
    if not isinstance(template_id, str) or not template_id:
        raise _fail("METRIC_ROW_INVALID", "verified query is missing template_id")

    template = next(
        (t for t in templates_rows if t.get("template_id") == template_id), None
    )
    if template is None:
        raise _fail("TEMPLATE_MISSING", f"template {template_id!r} not in sql_templates.json")
    if template.get("metric_name") != metric_name:
        raise _fail(
            "TEMPLATE_METRIC_MISMATCH",
            f"template {template_id!r} belongs to {template.get('metric_name')!r}",
        )
    metric_sql = verified[0].get("sql")
    template_sql = template.get("sql")
    if (
        not isinstance(metric_sql, str)
        or not isinstance(template_sql, str)
        or hashlib.sha256(metric_sql.encode("utf-8")).hexdigest()
        != hashlib.sha256(template_sql.encode("utf-8")).hexdigest()
    ):
        raise _fail(
            "TEMPLATE_SQL_DRIFT",
            f"metrics.json and sql_templates.json disagree on {template_id!r}",
        )

    dialect = template.get("sql_dialect")
    if dialect != "mysql":
        raise _fail(
            "DIALECT_UNSUPPORTED",
            f"pack execution currently supports mysql only, got {dialect!r}",
        )

    if not _DATE_RE.match(start_date) or not _DATE_RE.match(end_date):
        raise _fail(
            "PARAMETER_INVALID",
            "start_date/end_date must be YYYY-MM-DD",
        )
    if start_date >= end_date:
        raise _fail(
            "PARAMETER_INVALID",
            "start_date must be earlier than end_date",
        )
    default_limit = template.get("default_limit", 100)
    max_limit = template.get("max_limit", 1000)
    effective_limit = default_limit if limit is None else limit
    if (
        not isinstance(effective_limit, int)
        or isinstance(effective_limit, bool)
        or not 1 <= effective_limit <= max_limit
    ):
        raise _fail(
            "PARAMETER_INVALID",
            f"limit must be an integer within [1, {max_limit}]",
        )
    required = template.get("required_parameters", [])
    parameters = {
        "start_date": start_date,
        "end_date": end_date,
        "limit": effective_limit,
    }
    missing = [p for p in required if p not in parameters]
    if missing:
        raise _fail("PARAMETER_INVALID", f"missing required parameters: {missing}")

    if len(providers_rows) != 1:
        raise _fail(
            "PROVIDER_AMBIGUOUS",
            f"pack must carry exactly one provider, found {len(providers_rows)}",
        )
    provider = providers_rows[0]
    provider_id = provider.get("provider_id")
    connection = provider.get("connection")
    allowed_schemas = provider.get("allowed_schemas")
    if (
        not isinstance(provider_id, str)
        or not provider_id
        or not isinstance(connection, dict)
        or not isinstance(allowed_schemas, list)
        or not all(isinstance(s, str) and s for s in allowed_schemas)
    ):
        raise _fail("PROVIDER_ROW_INVALID", "provider row is incomplete")
    for field in _SECRET_FIELDS:
        if field in connection:
            raise _fail(
                "CONNECTION_INLINE_SECRET",
                f"connection carries inline {field!r}; only *_env references are allowed",
            )
    if connection.get("connection_type") != "mysql":
        raise _fail(
            "DIALECT_UNSUPPORTED",
            f"connection_type must be 'mysql', got {connection.get('connection_type')!r}",
        )
    for field in ("host", "port", "database", "username", "password_env"):
        if field not in connection:
            raise _fail(
                "CONNECTION_FIELD_MISSING",
                f"connection is missing {field!r}",
            )

    # Defense in depth: re-check the exact SQL + parameters through the real
    # safety gate at load time; DataAgentRuntime checks again at execution.
    checker = DataSQLSafetyChecker(
        tuple(allowed_schemas),
        dialect="mysql",
    )
    try:
        checker.assert_safe(template_sql, parameters)
    except Exception as exc:
        raise _fail("SQL_SAFETY_DENIED", f"{template_id!r} failed the safety gate: {exc}") from exc

    return PackQuery(
        metric_name=metric_name,
        metric_version=manifest_version,
        metric_contract_digest=hashlib.sha256(
            canonical_json(metric).encode("utf-8")
        ).hexdigest(),
        template_id=template_id,
        sql=template_sql,
        parameters=parameters,
        provider_id=provider_id,
        allowed_schemas=tuple(allowed_schemas),
        connection=dict(connection),
        sql_dialect="mysql",
    )


__all__ = ["PackQuery", "load_pack_query"]
