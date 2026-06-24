# ADR-0002 Enterprise Integration Readiness Review

- Date: 2026-06-24
- Branch: `codex/enterprise-integration-readiness`
- Scope: local integration of `codex/connector-semantics-generalization` and `codex/report-read-projection`
- Status: reviewed locally; not merged, pushed, released, or deployed

## Findings

No code-level merge blocker found.

## Review Notes

- `GET /runs/{trace_id}/report` reads from an injected report snapshot store and does not re-enter `runtime.evaluate`; memory remains same-process, while postgres-backed report snapshots survive fresh app/runtime instances.
- Internal and external report snapshots now use projection-scoped `artifact_id` values, so client caches and audit consumers cannot treat differently redacted views as the same rendered artifact.
- `external_report` has only `runs:external` and `reports:read`; it remains blocked from outcome, adoption, search, trace, and approval management surfaces.
- External report reads are capped by `audience_ceiling=external` even when the caller requests `audience=internal`.
- Report snapshot durability is scoped to the postgres store backend's `report_snapshots` table; this branch does not claim external release, full RBAC/DLP, external-system exactly-once, or durable arbitrary external connector recovery.
- Connector execution-audit defaults now come from `ActionConnectorContract.execution_semantics`; the removed `action_record` connector-name special case is covered by a static regression guard.
- Action connector replay fields are projected as safe audit fields (`replay_status`, `external_ack_status`) without exposing raw connector payloads or `last_replay_status`.
- `make ci` now starts with a selected-`PYTHON` dependency preflight for the dev/http/postgres extras needed by lint, OpenAPI, and the current persistence-backed test coverage.

## Required Changes

Completed in this review pass:

- Added `test_report_read_respects_internal_access_and_external_ceiling` to lock internal report access and external forced projection.
- Extended the same report-read regression to pin distinct internal/external `artifact_id` values, then scoped `_build_user_result_artifact()` artifact ids by audience.
- Updated README, AGENTS, and CURRENT_STATE verification counts from 417 to 418 after full CI.
- Updated README and CURRENT_STATE wording after the projection-scoped artifact hardening so the active branch is `codex/enterprise-integration-readiness`, not the older component branch name.
- Added `check-ci-env` to prevent opaque missing-`ruff`/missing-`fastapi` failures when `make ci` runs against an unbootstrapped default interpreter; `ci-local-full` retains the separate database URL preflight.
- Added `SqlReportSnapshotStore`, the `report_snapshots` schema/migration, and a fresh-app HTTP regression proving postgres-backed internal/external report projections can be read without re-running the loop.

## Verification

- `PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_report_read_respects_internal_access_and_external_ceiling -v`
  - Result: 1 test OK.
- `PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_http_app -v`
  - Result: 40 tests OK.
- `make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python`
  - Result: 419 tests OK, 4 skipped; 12 eval tests OK; OpenAPI contract up to date; ruff and format clean.
- `git diff --check`
  - Result: clean after README/review status synchronization.
- `make check-ci-env PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python`
  - Result: dependency preflight passed.
- `make check-ci-env`
  - Result: failed as expected in the unbootstrapped default interpreter with an actionable `missing ci dependencies ... run make bootstrap-dev ... or pass PYTHON=...` message.
- `PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_http_app.HttpKnowledgeSearchTest.test_report_snapshot_survives_fresh_app_on_postgres_backend -v`
  - Red result before implementation: failed because `ContentCommerceRuntimeFactory` had no `build_report_snapshot_store`.
  - Green result after implementation: 1 test OK.
- `PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_migrations_cover_schema -v`
  - Result: 2 tests OK.

## Approval Status

Merge-ready as a local integration branch, subject to explicit founder approval for merge, push, and any release gate. This review does not approve external release, production deployment, full RBAC/DLP, tenant isolation, external-system exactly-once, external ACK confirmation, durable arbitrary external connector recovery, or automatic R4/R5 execution.
