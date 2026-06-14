## Summary

The four persistence follow-ups after #4, on top of `main`. All sync (per the reversed async decision).
233 tests (2 PG-integration skipped without a live DB); ruff clean.

## What's in here

**ApprovalStorePort (#4 of the list)** — split `ApprovalLiteRuntime` storage behind a new
`ApprovalStorePort` (in-memory default + `SqlApprovalStore`), so an approval created in one process
can be acted on later in another (durable governance gate). Lifecycle stays in `ApprovalLiteRuntime`;
public API unchanged. `approval_records` table + factory wiring.

**Transactional `record_outcome` (unit of work)** — SQL stores are now *bind-aware* (an `Engine` or a
shared `Connection`); `SqlUnitOfWork` yields connection-bound feedback+knowledge stores in one
transaction. `TrustedLoopRuntime.record_outcome` runs the feedback write + knowledge version bump
**atomically** — both commit or both roll back. Default (in-memory) path uses a `nullcontext` over its
own stores. Verified on SQLite: commit-both and rollback-both.

**JSONB + GIN migration** — Alembic `0002` promotes `payload` columns to `JSONB` and adds GIN indexes
on **PostgreSQL only** (no-op on other dialects, so SQLite tests are unaffected).

**Real PostgreSQL integration tests** — `tests/unit/test_persistence_postgres.py` runs the repository
round-trips + uow atomicity against a real PG when `AGENT_OS_DATABASE_URL` is set; otherwise skips, so
the default suite and bare-env CI stay green.

## Verification

- 233 tests pass (2 PG-integration skipped locally/CI). SQLite covers the repo logic incl. dedup/
  version/append, approval lifecycle across instances, and uow commit/rollback.
- `ruff check .` + `ruff format --check .` clean (whole repo). Alembic migrations compile.
- OS Core still imports no SQLAlchemy / persistence package — all wiring is in the factory.

## Notes

- JSONB/GIN and the PG integration tests can only be exercised against a live PostgreSQL (not
  available in this environment); they are written and compile, and run when a DSN is provided.
- `ApprovalStorePort` completes the store-Port family (feedback/knowledge/snapshot/approval).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
