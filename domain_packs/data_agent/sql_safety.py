from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import sqlglot
from sqlglot import exp

from .contracts import DataSQLSafetyIssue, DataSQLSafetyResult
from .errors import DataAgentDenied


@dataclass(frozen=True)
class DataSQLSafetyPolicy:
    allowed_schemas: tuple[str, ...]
    max_limit: int = 1_000
    require_schema_qualified_tables: bool = True
    require_limit: bool = True
    allow_select_star: bool = False
    dialect: str = "postgres"


# sqlglot parse dialects the gate is validated for.  The dialect is owned by
# the composed provider (SQLite keeps the historical postgres parsing; MySQL
# warehouses need mysql parsing for backtick/non-ASCII identifiers).  Unknown
# dialects fail closed at construction.
SUPPORTED_SQL_DIALECTS: frozenset[str] = frozenset({"postgres", "mysql"})


_FORBIDDEN_STATEMENT_TYPES: tuple[type[sqlglot.Expr], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.Grant,
    exp.Revoke,
    exp.TruncateTable,
)


def _issue(code: str, message: str) -> DataSQLSafetyIssue:
    return DataSQLSafetyIssue(code=code, message=message)


def _has_comments(node: sqlglot.Expr | None) -> bool:
    if node is None:
        return False
    if getattr(node, "comments", None):
        return True
    return any(_has_comments(child) for child in node.iter_expressions())


def _max_subquery_depth(node: sqlglot.Expr) -> int:
    max_depth = 0

    def walk(current: sqlglot.Expr, depth: int) -> None:
        nonlocal max_depth
        if isinstance(current, exp.Subquery):
            depth += 1
            max_depth = max(max_depth, depth)
        for child in current.iter_expressions():
            walk(child, depth)

    walk(node, 0)
    return max_depth


def _is_select_list_star(star: exp.Star) -> bool:
    parent = star.parent
    return isinstance(parent, exp.Select) or (
        isinstance(parent, exp.Column) and isinstance(parent.parent, exp.Select)
    )


def _extract_limit_value(
    limit_node: exp.Limit,
    parameters: Mapping[str, Any] | None,
) -> int | None:
    expression = limit_node.expression
    if isinstance(expression, exp.Literal):
        try:
            return int(expression.name)
        except ValueError:
            return None
    if isinstance(expression, exp.Neg) and isinstance(expression.this, exp.Literal):
        try:
            return -int(expression.this.name)
        except ValueError:
            return None
    if isinstance(expression, exp.Placeholder):
        name = expression.name
        if not parameters or name not in parameters:
            return None
        value = parameters[name]
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


class DataSQLSafetyChecker:
    """Data-domain AST gate; execution authority remains in CapabilityBroker."""

    def __init__(
        self,
        allowed_schemas: tuple[str, ...] = ("main",),
        *,
        max_limit: int = 1_000,
        dialect: str = "postgres",
    ) -> None:
        if dialect not in SUPPORTED_SQL_DIALECTS:
            raise ValueError(
                f"Unsupported SQL safety dialect: {dialect!r}. "
                f"Supported: {sorted(SUPPORTED_SQL_DIALECTS)}"
            )
        self.policy = DataSQLSafetyPolicy(
            allowed_schemas=allowed_schemas,
            max_limit=max_limit,
            dialect=dialect,
        )

    def check(
        self,
        sql: str,
        required_parameters: tuple[str, ...] = (),
        parameters: Mapping[str, Any] | None = None,
        *,
        required_time_parameters: tuple[str, ...] = (),
        max_limit: int | None = None,
        allow_select_star: bool | None = None,
    ) -> DataSQLSafetyResult:
        issues: list[DataSQLSafetyIssue] = []
        normalized = sql.strip()
        effective_max_limit = max_limit or self.policy.max_limit
        effective_allow_select_star = (
            allow_select_star
            if allow_select_star is not None
            else self.policy.allow_select_star
        )
        try:
            tree = sqlglot.parse_one(normalized, read=self.policy.dialect)
        except sqlglot.ParseError as exc:
            return self._build_result(
                [_issue("PARSE_ERROR", f"SQL parse error: {exc}")],
                parameters,
                None,
            )

        if not isinstance(tree, exp.Select):
            issues.append(_issue("ONLY_SELECT", "Only SELECT statements are allowed."))
        if any(tree.find(forbidden) for forbidden in _FORBIDDEN_STATEMENT_TYPES):
            issues.append(
                _issue("NO_WRITE_OR_DDL", "Write or DDL statements are forbidden.")
            )
        if tree.find(exp.Union):
            issues.append(_issue("NO_UNION", "UNION is forbidden."))
        if _has_comments(tree):
            issues.append(_issue("NO_SQL_COMMENTS", "SQL comments are forbidden."))
        if ";" in normalized.rstrip().rstrip(";"):
            issues.append(
                _issue("SINGLE_STATEMENT", "Only one SQL statement is allowed.")
            )
        depth = _max_subquery_depth(tree)
        if depth > 2:
            issues.append(
                _issue(
                    "SUBQUERY_TOO_DEEP",
                    f"Subquery nesting depth {depth} exceeds the maximum of 2.",
                )
            )

        checked_schemas: list[str] = []
        checked_tables: list[str] = []
        tables = list(tree.find_all(exp.Table))
        if not tables and isinstance(tree, exp.Select):
            issues.append(
                _issue(
                    "SCHEMA_QUALIFIED_TABLE",
                    "SQL must reference schema-qualified tables.",
                )
            )
        for table in tables:
            if table.db:
                checked_schemas.append(table.db)
                checked_tables.append(f"{table.db}.{table.name}")
                if table.db not in self.policy.allowed_schemas:
                    issues.append(
                        _issue(
                            "SCHEMA_ALLOWLIST",
                            f"Schema is not allowlisted: {table.db}",
                        )
                    )
            else:
                checked_tables.append(table.name)
                issues.append(
                    _issue(
                        "SCHEMA_QUALIFIED_TABLE",
                        f"Table reference must be schema-qualified: {table.name}",
                    )
                )

        if (
            any(_is_select_list_star(star) for star in tree.find_all(exp.Star))
            and not effective_allow_select_star
        ):
            issues.append(_issue("NO_SELECT_STAR", "SELECT * is forbidden."))

        bound_parameters = {
            placeholder.name for placeholder in tree.find_all(exp.Placeholder)
        }
        required = set(required_parameters).union(required_time_parameters)
        for parameter in sorted(required - bound_parameters):
            issues.append(
                _issue(
                    "MISSING_SQL_PARAMETER",
                    f"Missing bound parameter: {parameter}",
                )
            )
        if parameters is not None:
            runtime_parameters = set(parameters)
            for parameter in sorted(bound_parameters - runtime_parameters):
                issues.append(
                    _issue(
                        "MISSING_RUNTIME_PARAMETER",
                        f"Missing runtime parameter value: {parameter}",
                    )
                )
            for parameter in sorted(runtime_parameters - bound_parameters):
                issues.append(
                    _issue(
                        "UNUSED_RUNTIME_PARAMETER",
                        f"Runtime parameter is unused: {parameter}",
                    )
                )

        limit_nodes = list(tree.find_all(exp.Limit))
        limit_value: int | None = None
        if self.policy.require_limit and isinstance(tree, exp.Select):
            if not limit_nodes:
                issues.append(_issue("MISSING_LIMIT", "SQL must include a LIMIT."))
            else:
                limit_value = _extract_limit_value(limit_nodes[-1], parameters)
                if limit_value is None:
                    issues.append(_issue("MISSING_LIMIT", "SQL must include a LIMIT."))
                elif limit_value < 1:
                    issues.append(
                        _issue("LIMIT_TOO_LOW", "LIMIT must be a positive integer.")
                    )
                elif limit_value > effective_max_limit:
                    issues.append(
                        _issue(
                            "LIMIT_TOO_HIGH",
                            f"LIMIT exceeds max allowed limit {effective_max_limit}.",
                        )
                    )

        return self._build_result(
            issues,
            parameters,
            limit_value,
            checked_schemas=checked_schemas,
            checked_tables=checked_tables,
            bound_parameters=bound_parameters,
        )

    def assert_safe(
        self,
        sql: str,
        parameters: Mapping[str, Any],
    ) -> DataSQLSafetyResult:
        result = self.check(sql, parameters=parameters)
        if not result.allowed:
            codes = ",".join(issue.code for issue in result.issues)
            raise DataAgentDenied(f"SQL_SAFETY_DENIED:{codes}")
        return result

    @staticmethod
    def _build_result(
        issues: list[DataSQLSafetyIssue],
        parameters: Mapping[str, Any] | None,
        limit_value: int | None,
        *,
        checked_schemas: list[str] | None = None,
        checked_tables: list[str] | None = None,
        bound_parameters: set[str] | None = None,
    ) -> DataSQLSafetyResult:
        del parameters
        return DataSQLSafetyResult(
            allowed=not issues,
            reasons=tuple(issue.message for issue in issues),
            checked_schemas=tuple(dict.fromkeys(checked_schemas or ())),
            checked_tables=tuple(dict.fromkeys(checked_tables or ())),
            bound_parameters=tuple(sorted(bound_parameters or ())),
            limit_value=limit_value,
            issues=tuple(issues),
        )
