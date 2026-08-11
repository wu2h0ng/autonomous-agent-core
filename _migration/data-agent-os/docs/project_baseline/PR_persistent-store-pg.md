## Summary

Phase 2 of the persistent store: durable PostgreSQL persistence for the loop's stateful stores,
implemented as a **synchronous** SQLAlchemy-Core adapter package, wired into the runtime factory,
with an Alembic migration scaffold. 2 commits on top of `main`.

### Strategy note (async reversed on review)
The ratified Phase 2 stack was SQLAlchemy Core + Alembic + `packages/persistence/` + **async asyncpg**.
On review the async choice was **reversed to sync**: async would force the entire runtime + 220-test
suite to become `async` (viral) while the dominant I/O (model calls, warehouse query execution) is
still synchronous — paying the async tax with no current benefit. We migrate to async only when the
whole I/O path goes async together under real concurrency. (The async core was prototyped and then
`git reset` before this branch — never reaching `main`.)

## What's in here

**`packages/persistence/` (`agent_os_persistence`)** — adapter layer, outside OS Core:
- `SqlFeedbackStore` / `SqlKnowledgeStore` / `SqlSnapshotStore` implementing OS Core's sync store Ports
  via SQLAlchemy Core; schema (generic `JSON`) + explicit (de)serialization mappers + `create_all`.
- Dialect-portable: same code runs on **SQLite (tests)** and **PostgreSQL (prod)**.
- Alembic scaffold (`alembic.ini`, `env.py` targeting the shared metadata, `0001_initial`).

**Factory wiring** — `RuntimeFactoryConfig.store_backend = "memory" | "postgres"`:
- `memory` (default): unchanged in-memory stores.
- `postgres`: lazily builds the SQLAlchemy stores on an injected engine / `database_url` and injects
  them. OS Core still imports no persistence — wiring lives in the composition layer.

## Verification

- 223 existing tests untouched and green; **228 total** (+5: persistence round-trip/dedup/version, factory durability, unknown-backend).
- Headline test: a knowledge candidate written by one runtime instance is visible to a SEPARATE
  runtime instance on the same engine — i.e. it survives a simulated restart (in-memory cannot).
  Verified on in-memory SQLite (no DB infra).
- `ruff check .` + `ruff format --check .` clean (whole repo). Persistence tests skip-guarded on
  SQLAlchemy so bare-env `make ci` stays green.

## Not in this PR (follow-ups)

- Real PostgreSQL **integration tests** (need a live PG / CI service; SQLite covers the logic).
- JSONB column refinement + GIN indexes (PG-only Alembic migration).
- Transactional `record_outcome` unit-of-work across feedback + knowledge writes.
- `ApprovalStorePort` (approval storage still in-memory).

## Review focus

- `packages/persistence/src/agent_os_persistence/repositories.py` (Port semantics: dedup/version/append).
- `apps/api_server/.../runtime_factory.py` `_build_stores` (lazy import; boundary preserved).
- OS Core imports no SQLAlchemy / persistence package.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
