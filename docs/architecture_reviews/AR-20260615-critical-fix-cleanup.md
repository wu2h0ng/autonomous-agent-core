# AR-20260615: Critical Fix Cleanup — SQL Safety, CLI Env Wiring, Persistence Atomicity

- Status: Accepted (CTO cleanup, 2026-06-15)
- Scope: absorb the non-duplicative fixes from stale draft PRs #10, #11, #17, and #20 onto current `main`; close duplicate draft PRs #18/#19 and superseded drafts after merge.
- Risk class: R2/R3. Touches SQL Safety, persistence consistency, and CLI/runtime composition. No public schema or OpenAPI shape change.

## 1. Context

The repository had several old Cursor draft PRs against earlier `main` states. They were not safe to merge as-is because current `main` already moved through PR-06, P5.1b, P5.1b-ii, and P5.2a. Manual reapplication on current `main` was safer than merging stale branches.

## 2. Accepted Fixes

1. **SQL Safety non-positive LIMIT guard**  
   `SQLSafetyChecker` now rejects `LIMIT <= 0` with `LIMIT_TOO_LOW`. This blocks SQLite's `LIMIT -1` unlimited-row behavior from bypassing `max_limit`.

2. **CLI 12-factor store wiring parity**  
   CLI `query` and `record-outcome` now resolve `RuntimeFactoryConfig` from `AGENT_OS_*` env vars plus explicit CLI overrides. This matches the HTTP app path and prevents postgres deployments from accidentally writing CLI feedback/knowledge/traces into ephemeral memory stores.

3. **KnowledgeAsset + search-index atomicity**  
   `EmbeddingKnowledgeStore` now writes canonical `knowledge_assets` and `knowledge_index` projection rows in one transaction on the Engine-bound runtime path. A failed embed/reindex step rolls back the canonical row rather than leaving durable knowledge invisible to search.

4. **Atomic knowledge version bump**  
   `SqlKnowledgeStore.register_version` now uses atomic `version = version + 1` updates, with row locking for connection-bound reads inside a unit of work. This prevents concurrent outcome submissions from silently losing a supersession bump.

## 3. Entry Points

- `TrustedLoopRuntime.run()` -> SQL Safety -> KnowledgeAsset write/index path.
- CLI `query` / `record-outcome`.
- `TrustedLoopRuntime.record_outcome()` -> `SqlUnitOfWork` -> `SqlKnowledgeStore.register_version`.

## 4. Tests

Verified locally after the cleanup:

```text
python -m pytest tests/unit -q
315 passed, 4 skipped, 7 subtests passed

python -m pytest tests/eval -q
2 passed, 10 subtests passed

python -m agent_os_api.openapi_contract --check
OpenAPI contract is up to date.

python -m ruff check .
All checks passed.

python -m ruff format --check .
97 files already formatted.
```

New/updated regression coverage:

- `tests/unit/test_sql_safety.py`: rejects negative, zero, and literal negative limits.
- `tests/unit/test_cli_record_outcome.py`: CLI env parity and override behavior.
- `tests/unit/test_knowledge_retrieval_sql.py`: failed reindex rolls back canonical write.
- `tests/unit/test_persistence.py`: sequential supersede bumps version beyond 2.
- `tests/unit/test_persistence_postgres.py`: guarded live-PG concurrent supersede regression.

## 5. PR Disposition

- Absorbed: #10, #11, #17, #20.
- Duplicate/superseded: #18, #19.
- After this AR is merged to `main`, all six stale draft PRs should be closed with a superseded note pointing to the cleanup commit.

## 6. Boundaries

- OS Core dependency boundaries remain intact.
- No domain-pack logic entered OS Core.
- No OpenAPI change.
- No runtime framework dependency added.
- No P5 research claim changes; this is product implementation hygiene.
