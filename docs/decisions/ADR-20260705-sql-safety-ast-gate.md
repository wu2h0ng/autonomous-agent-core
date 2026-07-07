# ADR-20260705: SQL Safety Gate — AST-Based Validation

## Status

Accepted — implemented and merged to deployment local main as part of Tech-Engineering-20260705.

## Context

The original `SQLSafetyChecker` relied on regular expressions to enforce the Tier 1 policy:

- SELECT-only
- schema/table allow-list
- no SELECT-star in projection lists
- mandatory bound parameters and LIMIT
- no SQL comments, no multiple statements

Regex-based validation is fast but brittle.  Comments, whitespace, nested structures, and dialect-specific syntax can evade a regex guard.  As the deployment layer moves toward a controlled pilot with real customer data, SQL Safety must become machine-verifiable and resistant to the most common bypass patterns.

## Decision

Replace the regex-first implementation with an AST-first implementation while preserving the public `SQLSafetyChecker.check()` contract.

- Parser: `sqlglot` (purchased library).
- Policy rules: self-developed in `packages/os_core/src/agent_os_core/sql_safety/`.
- Validation surface: SELECT-only root, forbidden statement traversal, UNION block, schema/table allow-list, SELECT-star guard, parameter binding, LIMIT enforcement, subquery depth ceiling (max 2), comment detection.

`sqlglot` is added to the runtime dependency set; external agent frameworks remain forbidden in OS Core (boundary #7).

## Consequences

### Positive

- Bypass patterns such as comment hiding, UNION injection, nested subqueries, and multi-statement payloads are rejected by structural analysis rather than pattern matching.
- The red-team suite (`tests/redteam/test_sql_safety_bypass.py`) can be extended without rewriting the parser.
- Existing callers and unit tests continue to work unchanged.

### Negative / Risks

- `sqlglot` is an additional runtime dependency.  Mitigation: it is a parser library, not an agent framework, and its behavior is wrapped by self-developed policy code.
- New SQL dialect edge cases may surface.  Mitigation: the gate fails closed (`PARSE_ERROR` blocks) when parsing fails.

## Alternatives Considered

1. **Keep regex and add more patterns.** Rejected: pattern escalation is an arms race and hard to regression-test.
2. **Build a custom SQL parser.** Rejected: out of scope for a 90-day milestone; `sqlglot` is a mature, open parser that can be studied and wrapped.
3. **Use a database-native parser (e.g. PostgreSQL `pg_query`).** Rejected: couples the gate to one dialect and adds a native dependency.

## Validation

- `tests/unit/test_sql_safety.py`: all 14 existing cases pass.
- `tests/redteam/test_sql_safety_bypass.py`: 14 bypass categories fail deterministically.
- `make ci`: passes.
- `scripts/anti_stub_linter.py`: added to CI to prevent future skeleton-only additions.

## Related

- `technical_engineering_plan.md` §5, §10
- `packages/os_core/src/agent_os_core/sql_safety/__init__.py`
- `tests/redteam/test_sql_safety_bypass.py`
- `scripts/anti_stub_linter.py`
