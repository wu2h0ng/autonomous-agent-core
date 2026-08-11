# AR-20260611: API Contract Stabilization (OpenAPI snapshot gate) + CI full-suite execution

- **Status**: Accepted
- **Date**: 2026-06-11
- **Completes**: PR-02 (API Contract Boundary) remaining scope — "正式 typed API contract / OpenAPI 稳定化"
- **Related**: AR-20260606-unified-block-outcome (the 422 block contract this AR freezes into the schema)

## Problem

1. **The HTTP API has no committed contract.** FastAPI generates an OpenAPI schema at
   runtime, but nothing pins it: a route, parameter, or response shape can change in a
   PR without any reviewable diff or failing test. PR-02's goal was a *typed API
   contract*; today the contract exists only as live code.
2. **The unified block contract (AR-20260606) is invisible to API consumers.** `/runs`
   returns the structured 422 block detail (code/message/stage/details), but the OpenAPI
   schema does not declare it — consumers cannot generate clients or validate against it.
3. **CI never runs the guarded suites.** CI installs only `.[dev]` (ruff), so every test
   skip-guarded on sqlalchemy/fastapi — the SQL retrieval suite, the transactional uow
   suite, the HTTP end-to-end suite, the PG integration suite — silently skips in CI.
   "CI green" currently proves the bare-env subset only; the persistence and HTTP
   behavior is verified solely on developer machines.

## Decision

1. **The committed OpenAPI snapshot is the API contract.**
   `apps/api_server/openapi.json` is generated from the app (deterministically: sorted
   keys, fixed indentation) and committed. A skip-guarded unit test regenerates the
   schema and fails on ANY drift, with instructions to regenerate. API changes therefore
   always produce a reviewable diff of the contract artifact in the same PR.
   - Regeneration entry point: `python -m agent_os_api.openapi_contract`
     (writes the snapshot; `--check` exits non-zero on drift without writing).
2. **The 422 block contract is declared in the schema.** `/runs` documents its 422
   response with a typed `BlockedResponse` model mirroring `TrustedLoopBlock`
   (code/message/stage/details), so the unified failure contract is part of the
   published API surface, not folklore.
3. **CI installs `.[dev,http,postgres]` and provides a postgres:16 service.** The
   skip guards remain (bare-env `make ci` still works locally without extras), but CI
   now exercises: the HTTP suite, the SQL retrieval/uow suites (SQLite), the OpenAPI
   drift gate, AND the real-PG integration suite via `AGENT_OS_DATABASE_URL` pointed at
   the service container. The plain `postgres:16` image has no pgvector, so CI also
   permanently exercises the 0004 graceful-skip guard.

## Consequences

- Any change to routes, models, parameters, or status codes fails the drift test until
  the snapshot is consciously regenerated and committed — compatibility review becomes
  a diff review of `openapi.json`.
- A FastAPI/pydantic version upgrade that alters schema generation will surface as a
  drift failure; regenerating the snapshot in the upgrade PR is the intended, explicit
  acknowledgement of the new serialized contract.
- CI runtime grows slightly (extras install + PG service); acceptable against the
  alternative of shipping unverified persistence/HTTP behavior.
- The snapshot freezes the contract of the composition-layer app only; OS Core remains
  HTTP-free and is unaffected.

## Completion gate mapping

- **Entry point**: `python -m agent_os_api.openapi_contract` (and `--check`).
- **Contract**: `apps/api_server/openapi.json` (the typed API contract artifact).
- **Negative path**: drift test fails on any schema mismatch; `--check` exits 1.
- **Bypass-detection**: editing a route without regenerating the snapshot fails CI.
- **Boundary**: all changes in `apps/api_server` + CI config; OS Core untouched.
