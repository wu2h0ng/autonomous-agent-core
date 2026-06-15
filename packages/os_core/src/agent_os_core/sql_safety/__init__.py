from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from agent_os_contracts import SQLSafetyIssue, SQLSafetyResult


FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|truncate|drop|alter|create|merge|grant|revoke)\b",
    re.IGNORECASE,
)
TABLE_TOKEN = re.compile(
    r"\b(?:from|join)\s+([a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*)?)",
    re.IGNORECASE,
)
PARAM_REF = re.compile(r":([a-zA-Z_][\w]*)")
LIMIT_REF = re.compile(r"\blimit\s+(?::([a-zA-Z_][\w]*)|(-?\d+))\b", re.IGNORECASE)
COMMENT_REF = re.compile(r"(--|/\*)")
# Match a star used as a select-list expansion right after SELECT, including
# the DISTINCT/ALL quantifier and qualified-star forms (e.g. ``select t.*``).
# This deliberately does NOT match ``count(*)`` (a parenthesised aggregate) or
# arithmetic ``a * b`` (a star not in the leading select-list position).
SELECT_STAR = re.compile(
    r"\bselect\s+(?:distinct\s+|all\s+)?(?:[a-zA-Z_]\w*\s*\.\s*)?\*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SQLSafetyPolicy:
    allowed_schemas: tuple[str, ...]
    max_limit: int = 1000
    require_schema_qualified_tables: bool = True
    require_limit: bool = True
    require_bound_parameters: bool = True
    allow_select_star: bool = False


class SQLSafetyChecker:
    def __init__(self, allowed_schemas: tuple[str, ...], max_limit: int = 1000) -> None:
        self.policy = SQLSafetyPolicy(allowed_schemas=allowed_schemas, max_limit=max_limit)

    def check(
        self,
        sql: str,
        required_parameters: tuple[str, ...],
        parameters: Mapping[str, Any] | None = None,
        *,
        required_time_parameters: tuple[str, ...] = ("start_date", "end_date"),
        max_limit: int | None = None,
        allow_select_star: bool | None = None,
    ) -> SQLSafetyResult:
        issues: list[SQLSafetyIssue] = []
        normalized = sql.strip()
        masked = _mask_string_literals(normalized)
        effective_max_limit = max_limit if max_limit is not None else self.policy.max_limit
        effective_allow_select_star = (
            allow_select_star if allow_select_star is not None else self.policy.allow_select_star
        )

        if not normalized.lower().startswith("select"):
            issues.append(_issue("ONLY_SELECT", "Only SELECT statements are allowed."))

        if COMMENT_REF.search(masked):
            issues.append(_issue("NO_SQL_COMMENTS", "SQL comments are forbidden in templates."))

        if _has_multiple_statements(masked):
            issues.append(_issue("SINGLE_STATEMENT", "Only one SQL statement is allowed."))

        if FORBIDDEN_SQL.search(masked):
            issues.append(_issue("NO_WRITE_OR_DDL", "Write or DDL statements are forbidden."))

        if not effective_allow_select_star and SELECT_STAR.search(masked):
            issues.append(
                _issue("NO_SELECT_STAR", "SELECT * is forbidden in production templates.")
            )

        table_tokens = tuple(TABLE_TOKEN.findall(masked))
        checked_tables: list[str] = []
        checked_schemas: list[str] = []

        if not table_tokens:
            issues.append(
                _issue("SCHEMA_QUALIFIED_TABLE", "SQL must reference schema-qualified tables.")
            )

        for table_token in table_tokens:
            if "." not in table_token:
                issues.append(
                    _issue(
                        "SCHEMA_QUALIFIED_TABLE",
                        f"Table reference must be schema-qualified: {table_token}",
                    )
                )
                continue

            schema, table = table_token.split(".", 1)
            checked_schemas.append(schema)
            checked_tables.append(f"{schema}.{table}")
            if schema not in self.policy.allowed_schemas:
                issues.append(_issue("SCHEMA_ALLOWLIST", f"Schema is not allowlisted: {schema}"))

        params = set(PARAM_REF.findall(masked))
        for parameter in required_parameters:
            if parameter not in params:
                issues.append(
                    _issue("MISSING_SQL_PARAMETER", f"Missing bound parameter: {parameter}")
                )

        for parameter in required_time_parameters:
            if parameter not in params:
                issues.append(
                    _issue(
                        "MISSING_TIME_PARAMETER", f"Missing required time parameter: {parameter}"
                    )
                )

        if parameters is not None:
            for parameter in required_parameters:
                if parameter not in parameters:
                    issues.append(
                        _issue(
                            "MISSING_RUNTIME_PARAMETER",
                            f"Missing runtime parameter value: {parameter}",
                        )
                    )

            for parameter in parameters:
                if parameter not in params:
                    issues.append(
                        _issue(
                            "UNUSED_RUNTIME_PARAMETER", f"Runtime parameter is unused: {parameter}"
                        )
                    )

        limit_value = _extract_limit(masked, parameters)
        if self.policy.require_limit and limit_value is None:
            issues.append(_issue("MISSING_LIMIT", "SQL must include an explicit LIMIT."))
        elif limit_value is not None and limit_value < 1:
            issues.append(
                _issue(
                    "LIMIT_TOO_LOW",
                    f"LIMIT {limit_value} must be a positive integer.",
                )
            )
        elif limit_value is not None and limit_value > effective_max_limit:
            issues.append(
                _issue(
                    "LIMIT_TOO_HIGH",
                    f"LIMIT {limit_value} exceeds max allowed limit {effective_max_limit}.",
                )
            )

        reasons = tuple(issue.message for issue in issues)

        return SQLSafetyResult(
            allowed=not issues,
            reasons=reasons,
            checked_schemas=tuple(dict.fromkeys(checked_schemas)),
            checked_tables=tuple(dict.fromkeys(checked_tables)),
            bound_parameters=tuple(sorted(params)),
            limit_value=limit_value,
            issues=tuple(issues),
        )


def _issue(code: str, message: str) -> SQLSafetyIssue:
    return SQLSafetyIssue(code=code, message=message)


def _mask_string_literals(sql: str) -> str:
    chars: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(sql):
        char = sql[i]
        if quote is None and char in ("'", '"'):
            quote = char
            chars.append(" ")
        elif quote is not None:
            if char == quote:
                if i + 1 < len(sql) and sql[i + 1] == quote:
                    chars.append(" ")
                    i += 1
                else:
                    quote = None
                    chars.append(" ")
            else:
                chars.append(" ")
        else:
            chars.append(char)
        i += 1
    return "".join(chars)


def _has_multiple_statements(sql: str) -> bool:
    stripped = sql.strip()
    if ";" not in stripped:
        return False
    return stripped.rstrip().rstrip(";").find(";") != -1


def _extract_limit(sql: str, parameters: Mapping[str, Any] | None) -> int | None:
    matches = LIMIT_REF.findall(sql)
    if not matches:
        return None

    param_name, literal_value = matches[-1]
    if literal_value:
        return int(literal_value)

    if not parameters or param_name not in parameters:
        return None

    value = parameters[param_name]
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
