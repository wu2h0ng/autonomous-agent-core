# Realtime Collaboration M1b — Exact-Head Review (Round 2, P2 remediation)

- Date: 2026-08-14
- Review target: `57f250b52116cb84f6ead65d6ed12ce5a1984628`
- Prior review target: `4f5753fd` (APPROVE_WITH_P2)
- Base: `bcab802efb974634b90e32c91c4f78eec8023ef7`
- Reviewer: OpenCode / DeepSeek (`deepseek/deepseek-v4-pro`), read-only
- Builder: Codex

## Scope of this round

Round 1 returned `APPROVE_WITH_P2` with three P2 findings. This round closes the
action-required P2 #1 (cursor advance gated on explicit replan). P2 #2 and #3 are
non-blocking and carried forward as debt.

## P2 closure

- **P2 #1 (resume advances cursor = silent override)** — CLOSED.
  `_install_run_work_lease` is now invoked only from `start_run` (new run) and
  `replan_task` (explicit acknowledge), not from `run_task` on every resume.
  A plain retry re-uses the existing lease cursor and keeps the conflict
  detected. Regression test
  `test_retry_without_replan_keeps_original_cursor_and_keeps_conflict`.

## Carried-forward P2 (non-blocking)

- P2 #2: producer read-then-append is non-atomic; concurrent external writes can
  be dropped as `WorkspaceEventSequenceConflict` (fail-closed, no retry). Acceptable
  for single-operator; document retry semantics before multi-writer.
- P2 #3: `SurfaceConflictProjection.from_decision` raises an opaque
  `ValidationError` for a CONTINUE decision (denial-only API; add a typed guard
  when a CONTINUE projection becomes a caller path).

## Verification

- Collaboration tests: **50 passed**.
- Full Product: **2215 passed, 1 skipped, 1 failed** (`test_product_entrypoint`
  pre-existing environment debt).
- Ruff: clean. Pyright: 0 on changed files.

## Verdict

`APPROVE`

All P0/P1 clear and the action-required P2 #1 is closed and regression-tested.
Remaining P2 #2/#3 are explicit non-blocking follow-up debt.

This verdict applies to `57f250b52116cb84f6ead65d6ed12ce5a1984628`. It does not
authorize push, merge, release, production activation, or a product completion
claim. The CTO merge gate remains a separate decision.
