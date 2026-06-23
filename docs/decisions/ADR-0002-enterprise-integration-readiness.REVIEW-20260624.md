# ADR-0002 Enterprise Integration Readiness Review

- Date: 2026-06-24
- Branch: `codex/enterprise-integration-readiness`
- Scope: local integration of `codex/connector-semantics-generalization` and `codex/report-read-projection`
- Status: reviewed locally; not merged, pushed, released, or deployed

## Findings

No code-level merge blocker found.

## Review Notes

- `GET /runs/{trace_id}/report` reads from an injected same-process report snapshot store and does not re-enter `runtime.evaluate`.
- `external_report` has only `runs:external` and `reports:read`; it remains blocked from outcome, adoption, search, trace, and approval management surfaces.
- External report reads are capped by `audience_ceiling=external` even when the caller requests `audience=internal`.
- Report snapshots remain explicitly same-process memory only; this branch does not claim durable cross-restart report persistence.
- Connector execution-audit defaults now come from `ActionConnectorContract.execution_semantics`; the removed `action_record` connector-name special case is covered by a static regression guard.
- Action connector replay fields are projected as safe audit fields (`replay_status`, `external_ack_status`) without exposing raw connector payloads or `last_replay_status`.

## Required Changes

Completed in this review pass:

- Added `test_report_read_respects_internal_access_and_external_ceiling` to lock internal report access and external forced projection.
- Updated README, AGENTS, and CURRENT_STATE verification counts from 417 to 418 after full CI.

## Verification

- `PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_report_read_respects_internal_access_and_external_ceiling -v`
  - Result: 1 test OK.
- `PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_http_app -v`
  - Result: 40 tests OK.
- `make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python`
  - Result: 418 tests OK, 4 skipped; 12 eval tests OK; OpenAPI contract up to date; ruff and format clean.

## Approval Status

Merge-ready as a local integration branch, subject to explicit founder approval for merge, push, and any release gate. This review does not approve external release, production deployment, durable report persistence, full RBAC/DLP, tenant isolation, external-system exactly-once, external ACK confirmation, durable arbitrary external connector recovery, or automatic R4/R5 execution.
