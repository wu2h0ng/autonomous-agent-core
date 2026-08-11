# ADR-0002 / ADR-0003 Enterprise Integration Reconcile Review

- Date: 2026-06-24
- Branch: `codex/enterprise-integration-reconcile`
- Reviewed commit: `f2d444b`
- Scope: review the local reconcile of ADR-0003 Agent Runtime v0 main-line work with ADR-0002 report-read/postgres snapshot durability and connector-semantics cleanup
- Status: reviewed locally; approved for explicit local merge decision only; not merged, pushed, released, or deployed

## Findings

No code-level merge blocker found.

## Review Notes

- `GET /runs/{trace_id}/report` reads already-built report snapshots and does not re-enter `runtime.evaluate`, so report reads do not rerun SQL, create approvals, or touch action connectors.
- Memory report snapshots remain same-process only; postgres-backed report snapshots use the `report_snapshots` table keyed by `(trace_id, audience)` and survive fresh app/runtime instances.
- Internal and external report projections keep distinct `artifact_id` values, so differently redacted artifacts are not collapsed by clients or audit consumers.
- `external_report` is forced to the external projection through `audience_ceiling=external` and the dedicated `reports:read` scope; it remains blocked from outcome, adoption, search, trace, and approval-management surfaces.
- Connector execution-audit defaults now come from `ActionConnectorContract.execution_semantics`; the previous `action_record` connector-name special case is removed and covered by a static regression guard.
- Action connector replay and ACK fields are projected through the safe audit whitelist (`replay_status`, `external_ack_status`, `record_id`, `external_request_id`, `durability_scope`, `ledger_status`, `execution_certainty`, `ack_status`) without exposing raw parameters or raw connector payloads.
- `make ci` now runs a selected-`PYTHON` dependency preflight before lint/format/unit/eval/OpenAPI checks, giving an actionable bootstrap message when dev/http/postgres extras are missing.

## Required Changes

Completed in this review pass:

- Clarified the `InMemoryReportSnapshotStore` docstring so it no longer implies durable report storage is still only a future ADR/schema; same-process memory remains local, while durable cross-instance reads are provided by the configured persistence-backed report snapshot store.

## Verification

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Observed result after the docstring fix:

- 440 primary unittest/eval-discover tests OK.
- 4 tests skipped.
- 12 eval subset tests OK.
- ruff check clean.
- ruff format check clean.
- OpenAPI contract up to date.

## Approval Status

Approved for the next explicit local merge decision. This review does not approve push, production release, external release, full RBAC/DLP, tenant isolation, field/row-level authorization, external-system exactly-once, external ACK confirmation, durable arbitrary external connector recovery, workflow replacement, autonomous-core adoption, or automatic R4/R5 execution.
