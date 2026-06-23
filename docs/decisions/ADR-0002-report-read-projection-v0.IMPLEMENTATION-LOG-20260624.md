# ADR-0002 Report Read Projection v0 — Implementation Log

Date: 2026-06-24
Branch: `codex/report-read-projection`
Status: implemented on feature branch; not merged, pushed, released, or deployed

## Scope

Add a side-effect-free HTTP read surface for an existing data-agent result:

- `GET /runs/{trace_id}/report`
- dedicated `reports:read` principal scope
- internal callers may request internal or external audience projection
- `external_report` callers are forced to the external projection
- unknown report snapshots return 404

This closes the product gap where an external report consumer previously had to call `POST /runs` again to receive a projection. `POST /runs` remains the only path that executes the Trusted Loop and builds evidence; the new GET surface only reads a snapshot already produced by a successful run.

## Implementation

- Added `InMemoryReportSnapshotStore` in the API service layer.
- `run_service(..., report_store=...)` stores both internal and external `user_result` projections after a successful run.
- Added `report_snapshot_service(...)` as a framework-agnostic read helper.
- `create_app(...)` wires a same-process report snapshot store by default.
- Added `RunReportResponse` and OpenAPI route schema for `GET /runs/{trace_id}/report`.
- Added `API_SCOPE_REPORT_READ`; internal and external-report principals can read reports, operator principals cannot.

## Verification

Red observed before implementation:

- `test_external_report_key_reads_existing_report_without_reexecuting_run` failed with 404 because the route did not exist.
- `test_api_principal_scope_contract_is_explicit` failed because `API_SCOPE_REPORT_READ` did not exist.

Green after implementation:

- targeted new tests pass
- `tests.unit.test_http_app` and `tests.unit.test_outcome_service`: 55 tests OK
- `tests.unit.test_openapi_contract`: 7 tests OK
- `make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python`: 415 unit tests OK, 4 skipped; 12 eval tests OK; ruff clean; format clean; OpenAPI contract up to date

## Boundaries

- No release, push, or merge.
- No new external action execution path.
- No automatic R4/R5 execution.
- No full RBAC, tenant isolation, field/row authorization, or DLP claim.
- No durable cross-restart report persistence claim; the v0 store is same-process memory.
- No external-system exactly-once or external ACK confirmation claim.
