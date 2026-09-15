# Architecture Design Brief: SQL Safety SELECT * Hardening

> Review ID: AR-20260606-sql-safety-select-star-hardening
> Date: 2026-06-06
> Prepared by: Code Review Agent
> Review owner: CTO
> Status: Proposed for CTO review
> Scope: SQL Safety guard behavior (`packages/os_core/src/agent_os_core/sql_safety`)

## 1. Context

SQL Safety is a hard boundary: all formal data answers must pass through it
(see `CLAUDE.md` Hard Rules). One of its production guards forbids `SELECT *`
in templates unless `allow_select_star` is explicitly set, so that result shape
stays bound to the metric contract rather than leaking arbitrary columns.

A code review probed the checker with adversarial inputs and found the guard was
**bypassable**. The detection pattern was:

```python
SELECT_STAR = re.compile(r"\bselect\s+\*", re.IGNORECASE)
```

This only matches a star immediately following `SELECT`. The following column
expansions were therefore accepted as safe (`allowed=True`) even with
`allow_select_star=False`:

- `select distinct *`
- `select all *`
- `select t.*` (qualified-star expansion)

## 2. Decision

Tighten the `SELECT_STAR` pattern to recognize the `DISTINCT`/`ALL` quantifier
and qualified-star forms, while continuing to ignore non-expansion stars:

```python
SELECT_STAR = re.compile(
    r"\bselect\s+(?:distinct\s+|all\s+)?(?:[a-zA-Z_]\w*\s*\.\s*)?\*",
    re.IGNORECASE,
)
```

- Blocks: `select *`, `select distinct *`, `select all *`, `select t.*`,
  `select distinct t.*`.
- Still allows: `count(*)` (parenthesised aggregate) and arithmetic `price * qty`
  (a star not in the leading select-list position), so the guard does not misfire
  on legitimate SQL.

This is a strengthening change: it closes a bypass and does not weaken,
remove, or relax any existing safety rule.

## 3. Consequences

- Templates relying on `SELECT DISTINCT *` / `SELECT t.*` while
  `allow_select_star=False` will now be correctly refused. No such template
  exists in the current domain packs (`domain_packs/content_commerce`).
- Negative path is covered by `tests/unit/test_sql_safety.py`:
  - `test_blocks_select_star_with_distinct_or_qualifier` (bypass closed)
  - `test_allows_count_star_and_arithmetic_star` (no false positives)
- No contract/schema change; `SQLSafetyResult` shape is unchanged.

## 4. Alternatives Considered

- **Full SQL parser / AST analysis**: more robust against every star form
  (e.g. `select a, * from ...`) but introduces a parsing dependency and
  complexity beyond MVP scope. Deferred.
- **Reject any bare `*` token**: would false-positive on arithmetic
  multiplication (`a * b`), breaking legitimate templates. Rejected.

## 5. Change Rules

Revisit when: SQL Safety adopts an AST-based analyzer; or additional star-form
bypasses (e.g. mid-list `select a, *`) are reported. Any change to this guard
must keep the two regression tests above passing and must not weaken the
existing forbidden-keyword, schema-allowlist, single-statement, no-comment, or
limit guards.
