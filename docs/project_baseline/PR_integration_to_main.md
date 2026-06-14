## Summary

Catch `main` up to the integration line `fix/security-advisory-url`, which has accumulated all of
the recent work via reviewed, CI-green PRs (#2, #3). 22 commits; brings `main` from `8dcab4a` to the
current integration head.

This is an integration PR — every change here already landed through its own reviewed PR with green
CI; this merge simply advances `main`.

## What `main` receives

**Trusted Loop end-to-end hardening (PR #2):**
- Governance gate — approval-required (incl. R4/R5) ops halt at `AWAITING_APPROVAL`, no auto-execute.
- Real data path — `SQLiteQueryExecutor` behind `ProviderContract`.
- Back half — Feedback + KnowledgeAsset builders/stores; loop emits a DRAFT knowledge candidate;
  `record_outcome()` supersedes it; `OperationTrace` in the result.
- First real governed write connector (`action_record`) + L3 snapshot/rollback.
- Trigger surfaces — CLI subcommand + FastAPI `/runs` & `/outcomes` with `X-API-Key` auth boundary.
- Eval Hub threshold report; SQL-safety SELECT-star hardening.
- Multi-metric template selection (`TemplateRegistry`); unified failure/block contract
  (`BlockCode` / `TrustedLoopBlock` / `TrustedLoopOutcome`, HTTP 422 / non-zero CLI).
- roi + conversion_rate templates + `visits` seed column (gmv/spend/roi/conversion_rate end-to-end).
- CI fixes: empty-module root distribution for editable install; whole-repo `ruff format`.

**Persistent store, Phase 1 (PR #3):**
- Design AR for the in-memory → PostgreSQL migration.
- `FeedbackStorePort` / `KnowledgeStorePort` ABCs; in-memory stores implement them; runtime programs
  to the ports. Decision-free, no DB.

**Plus:** the original `docs: fix security advisory URL` commit.

## Verification

All squashed into reviewed PRs that passed CI on Python 3.11/3.12/3.13. Integration-line parity
re-checked locally: `ruff check .` clean, `ruff format --check .` clean (whole repo), 223 tests pass
with the Makefile PYTHONPATH.

## Follow-ups (tracked, not in this PR)

Persistent store Phase 2 (PG adapter — pending backend/tooling decisions in the AR); `ApprovalStorePort`;
ActionProposalBuilder → real-write-connector routing (product decision); L3 → PG JSONB; L4 Temporal;
F1 static workspace.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
