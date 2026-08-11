from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import sqlglot
from sqlglot import exp

from agent_os_contracts import SQLSafetyIssue, SQLSafetyResult


@dataclass(frozen=True)
class SQLSafetyPolicy:
    allowed_schemas: tuple[str, ...]
    max_limit: int = 1000
    require_schema_qualified_tables: bool = True
    require_limit: bool = True
    require_bound_parameters: bool = True
    allow_select_star: bool = False


# Statement-level classes that the gate never permits.  Subqueries are allowed
# only when nested inside a SELECT; any other statement class is a hard block.
_FORBIDDEN_STATEMENT_TYPES: tuple[type[exp.Expression], ...] = (
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


def _issue(code: str, message: str) -> SQLSafetyIssue:
    return SQLSafetyIssue(code=code, message=message)


def _has_comments(node: exp.Expression | None) -> bool:
    if node is None:
        return False
    if getattr(node, "comments", None):
        return True
    return any(_has_comments(child) for child in node.iter_expressions())


def _max_subquery_depth(node: exp.Expression) -> int:
    """Maximum depth of nested Subquery expressions."""
    max_depth = 0

    def walk(n: exp.Expression, depth: int) -> None:
        nonlocal max_depth
        if isinstance(n, exp.Subquery):
            depth += 1
            max_depth = max(max_depth, depth)
        for child in n.iter_expressions():
            walk(child, depth)

    walk(node, 0)
    return max_depth


def _is_select_list_star(star: exp.Star) -> bool:
    """Return True only when the star is a top-level SELECT projection.

    ``count(*)`` and arithmetic ``a * b`` are excluded because the star is
    inside a function/operator expression, not the projection list.
    """
    parent = star.parent
    if isinstance(parent, exp.Select):
        return True
    if isinstance(parent, exp.Column) and isinstance(parent.parent, exp.Select):
        return True
    return False


def _extract_limit_value(limit_node: exp.Limit, parameters: Mapping[str, Any] | None) -> int | None:
    expression = limit_node.expression
    if isinstance(expression, exp.Literal):
        try:
            return int(expression.name)
        except ValueError:
            return None
    if isinstance(expression, exp.Neg):
        inner = expression.this
        if isinstance(inner, exp.Literal):
            try:
                return -int(inner.name)
            except ValueError:
                return None
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


class SQLSafetyChecker:
    """AST-level SQL safety gate.

    The checker parses SQL with ``sqlglot`` and validates the resulting tree
    against a self-developed policy: SELECT-only, schema/table allow-list,
    no SELECT-star in the projection list, mandatory bound parameters,
    mandatory LIMIT, and an upper bound on LIMIT.  It is deliberately not a
    generic allow-everything parser; policy rules are the trust boundary and
    are owned by this module.
    """

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
        effective_max_limit = max_limit if max_limit is not None else self.policy.max_limit
        effective_allow_select_star = (
            allow_select_star if allow_select_star is not None else self.policy.allow_select_star
        )

        normalized = sql.strip()

        # Parse --------------------------------------------------------------
        try:
            tree = sqlglot.parse_one(normalized, read="postgres")
        except sqlglot.errors.ParseError as exc:
            issues.append(_issue("PARSE_ERROR", f"SQL parse error: {exc}"))
            return self._build_result(issues, normalized, parameters, None)

        # Structural gate: exactly one SELECT statement ----------------------
        if not isinstance(tree, exp.Select):
            issues.append(_issue("ONLY_SELECT", "Only SELECT statements are allowed."))
            # Surface any forbidden statement that caused the non-SELECT root.
            if any(tree.find(forbidden) for forbidden in _FORBIDDEN_STATEMENT_TYPES):
                issues.append(_issue("NO_WRITE_OR_DDL", "Write or DDL statements are forbidden."))

        # Forbidden statement traversal (catches nested/leading write ops) -----
        for forbidden in _FORBIDDEN_STATEMENT_TYPES:
            if tree.find(forbidden):
                issues.append(_issue("NO_WRITE_OR_DDL", "Write or DDL statements are forbidden."))
                break

        # UNION is forbidden in Tier 1 ---------------------------------------
        if tree.find(exp.Union):
            issues.append(_issue("NO_UNION", "UNION is forbidden in production templates."))

        # Comments -----------------------------------------------------------
        if _has_comments(tree):
            issues.append(_issue("NO_SQL_COMMENTS", "SQL comments are forbidden in templates."))

        # Multiple statements via semicolon or Block root ---------------------
        if ";" in normalized.rstrip().rstrip(";"):
            issues.append(_issue("SINGLE_STATEMENT", "Only one SQL statement is allowed."))

        # Subquery nesting depth (Tier 1: max 2) -----------------------------
        subquery_depth = _max_subquery_depth(tree)
        if subquery_depth > 2:
            issues.append(
                _issue(
                    "SUBQUERY_TOO_DEEP",
                    f"Subquery nesting depth {subquery_depth} exceeds the maximum of 2.",
                )
            )

        # Table / schema allow-list ------------------------------------------
        tables = list(tree.find_all(exp.Table))
        checked_schemas: list[str] = []
        checked_tables: list[str] = []

        if not tables and isinstance(tree, exp.Select):
            issues.append(
                _issue("SCHEMA_QUALIFIED_TABLE", "SQL must reference schema-qualified tables.")
            )

        for table in tables:
            table_name = table.name
            schema = table.db
            if schema:
                checked_schemas.append(schema)
                checked_tables.append(f"{schema}.{table_name}")
                if schema not in self.policy.allowed_schemas:
                    issues.append(
                        _issue("SCHEMA_ALLOWLIST", f"Schema is not allowlisted: {schema}")
                    )
            else:
                checked_tables.append(table_name)
                issues.append(
                    _issue(
                        "SCHEMA_QUALIFIED_TABLE",
                        f"Table reference must be schema-qualified: {table_name}",
                    )
                )

        # SELECT star guard --------------------------------------------------
        select_list_stars = [s for s in tree.find_all(exp.Star) if _is_select_list_star(s)]
        if select_list_stars and not effective_allow_select_star:
            issues.append(
                _issue("NO_SELECT_STAR", "SELECT * is forbidden in production templates.")
            )

        # Bound parameters ---------------------------------------------------
        placeholders = list(tree.find_all(exp.Placeholder))
        params = {p.name for p in placeholders}

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

        # LIMIT --------------------------------------------------------------
        limit_nodes = list(tree.find_all(exp.Limit))
        limit_value: int | None = None
        if self.policy.require_limit and isinstance(tree, exp.Select):
            if not limit_nodes:
                issues.append(_issue("MISSING_LIMIT", "SQL must include an explicit LIMIT."))
            else:
                limit_value = _extract_limit_value(limit_nodes[-1], parameters)
                if limit_value is None:
                    issues.append(_issue("MISSING_LIMIT", "SQL must include an explicit LIMIT."))
                elif limit_value < 1:
                    issues.append(
                        _issue(
                            "LIMIT_TOO_LOW",
                            f"LIMIT {limit_value} must be a positive integer.",
                        )
                    )
                elif limit_value > effective_max_limit:
                    issues.append(
                        _issue(
                            "LIMIT_TOO_HIGH",
                            f"LIMIT {limit_value} exceeds max allowed limit {effective_max_limit}.",
                        )
                    )

        return self._build_result(
            issues,
            normalized,
            parameters,
            limit_value,
            checked_schemas=checked_schemas,
            checked_tables=checked_tables,
            bound_parameters=params,
        )

    def _build_result(
        self,
        issues: list[SQLSafetyIssue],
        sql: str,
        parameters: Mapping[str, Any] | None,
        limit_value: int | None,
        *,
        checked_schemas: list[str] | None = None,
        checked_tables: list[str] | None = None,
        bound_parameters: set[str] | None = None,
    ) -> SQLSafetyResult:
        reasons = tuple(issue.message for issue in issues)
        return SQLSafetyResult(
            allowed=not issues,
            reasons=reasons,
            checked_schemas=tuple(dict.fromkeys(checked_schemas or ())),
            checked_tables=tuple(dict.fromkeys(checked_tables or ())),
            bound_parameters=tuple(sorted(bound_parameters or ())),
            limit_value=limit_value,
            issues=tuple(issues),
        )
