# ADR-0002 Remediation Implementation Log — 2026-06-24

Branch: `codex/durable-action-ledger`

Source packet: `docs/decisions/ADR-0002-governed-action-outcome-loop-v0.CODEX-REMEDIATION-20260624.md`

## Scope

Implemented the three code/test remediation items from REVIEW-20260624:

- H1: stale approval-context reclaim TOCTOU.
- M1: audience-first read-side redaction with public-external infrastructure stripping.
- M2: operator-key unconfigured 503 regression coverage.

No merge, push, release, external-system exactly-once claim, full RBAC/DLP claim, or R4/R5 automatic execution was performed.

## Files Changed

- `packages/persistence/src/agent_os_persistence/repositories.py`
- `apps/api_server/src/agent_os_api/outcome_service.py`
- `tests/unit/test_persistence.py`
- `tests/unit/test_outcome_service.py`
- `tests/unit/test_http_app.py`
- `docs/CURRENT_STATE.yaml`
- `README.md`
- `apps/api_server/README.md`

The review, AR, and remediation packet documents are part of the same branch-gate trail:

- `docs/decisions/ADR-0002-governed-action-outcome-loop-v0.REVIEW-20260624.md`
- `docs/architecture_reviews/AR-20260624-http-principal-scope-and-redaction.md`
- `docs/decisions/ADR-0002-governed-action-outcome-loop-v0.CODEX-REMEDIATION-20260624.md`

## Implementation Notes

H1:

- Added a deterministic two-reclaimer race regression test.
- Changed stale executing reclaim from status-only CAS to observed claim-token CAS using `_claim.claimed_at`.
- The pending-to-executing CAS path remains unchanged.

M1:

- Split redaction into infrastructure redaction and metric-data redaction while keeping the public response shape unchanged.
- `audience=external` always hides physical schemas/tables, bound parameter names, limit metadata, and SQL fingerprints.
- `audience=external` plus `data_classification=public` may still show public metric dimensions, columns, preview rows, chart fields, and KPI values.
- `audience=external` plus non-public classification still hides non-public metric data.
- `audience` remains `internal|external`; no M2 `audience_profile` was added.

M2:

- Added a targeted HTTP test for `operator_api_key=None` on `/approvals/{approval_id}/execute`.
- The test uses an arbitrary approval id because the operator-key dependency returns 503 before approval lookup.

