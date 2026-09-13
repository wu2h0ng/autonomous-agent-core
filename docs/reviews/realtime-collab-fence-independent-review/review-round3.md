# Realtime Collaboration Fence — Exact-Head Review (Round 3, P2 remediation)

- Date: 2026-08-14
- Review target: `f7453f17ac1a28b891ad19666e5577e7038405b5`
- Prior review target: `d0afc3a6` (APPROVE_WITH_P2)
- Base: `c819f75b9ad01850a90850d72da2b621129308a2`
- Reviewer: OpenCode / DeepSeek (`deepseek/deepseek-v4-pro`), read-only
- Builder: Codex

## Scope of this round

Round 2 returned `APPROVE_WITH_P2` with five P2 findings. This round closes the
two action-required P2s (disposition priority ordering, architecture-brief
accuracy). The remaining three P2s are explicitly non-blocking documentation/
follow-up items and are carried forward as debt.

## Verification this round

- Collaboration tests: **37 passed** (2 new disposition-priority regression tests).
- Full Product: **2202 passed, 1 skipped, 1 failed** (`test_product_entrypoint`
  editable-install environment debt, reproduces on base).
- Ruff: clean. Pyright: 0 on changed files.

## P2 closure

- **P2 #1 (disposition ordering)** — CLOSED. `workspace_collaboration.py:190-197`
  now guards both `WRITE_CONFLICT` and `WORK_CANCELLED` so later lower-severity
  events cannot downgrade them (`CONFLICT > CANCEL > REPLAN`). Regression tests:
  `test_conflict_not_downgraded_by_later_lower_severity_event`,
  `test_cancel_not_downgraded_by_later_context_change_event`.
- **P2 #2 (doc accuracy)** — CLOSED. `T-P-REALTIME-COLLAB-FENCE` §2.2 documents
  that the broker resolves the trusted registry on every dispatch (contract
  tightening), not a no-op fast path.

## Carried-forward P2 (non-blocking, follow-up only)

- P2 #3: no production event producer; `event_cursor` never advances in production
  (fence is a preflight seam; M1b event source is future work).
- P2 #4: `ExecutionLease.owner` not bound to `WorkLease.holder_id` (worker/principal
  separation; document before multi-principal).
- P2 #5: dead code (`WorkspaceFenceUnavailable` never raised; unused `shared_version`
  fields; `PLAN_INVALIDATED` falls into REPLAN with no dedicated test).

## Verdict

`APPROVE`

All P1s from the first review and both action-required P2s are closed and
independently verified. Remaining items are explicit non-blocking follow-up debt
that does not create a bypass, regression, or unsafe authority path.

This verdict applies to `f7453f17ac1a28b891ad19666e5577e7038405b5`. It does not
authorize push, merge, release, production activation, or a product completion
claim. The CTO merge gate remains a separate decision.
