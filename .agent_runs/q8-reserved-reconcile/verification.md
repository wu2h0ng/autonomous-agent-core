
## 2026-09-27 continuation
- Previous turn: PROGRESS (loop routing implementation + full-loop failure evidence).
- `uv run --extra product-test pytest tests/product/test_spine0_security_and_persistence.py -q`: 34 passed, including exact reservation/active same-owner/active other-owner/missing/content-drift lease claim tests.
- Scoped pyright persistence/postgres/outcome: 0 errors. Ruff and diff-check clean.
- New full-loop restart test: NOT_MET; ordinary turn has no durable execution cursor, resumes provider with unanswered tools.
- Remaining: typed ordinary-turn cursor/counters, completion held under execution scope/lease, PostgreSQL runtime gate, independent final review. No commit/push/release this continuation.

## Ordinary turn progress implementation
- Added additive message progress and typed projected ordinary cursor; assistant/reply + cursor commit in same event. Resume preserves tool index, step/token budgets and action fingerprint counters. Exact prior approval reused, never silently replaced.
- Real AgentLoop crash-after-effect recovery scenario now PASS, dispatch count remains one.
- Focused terminal+persistence suite: 75 passed. Ruff/Pyright scoped cursor files: clean.
- Tool completion now written while holding/binding lease; stale ownership propagates without failure truth write.
- Still WIP/uncommitted: provider-receipt-before-assistant crash window, counter/source validation and approval path fencing need independent review.

## Budget continuity gates
- Typed writer validates progress before append; step/token counters cannot regress; same assistant advances exactly one reply, new assistant advances one provider step.
- Real-loop test now verifies restored budgets and rejects a budget regression without appending events.
- Review P1 budget-edge repaired: continuation processed even when accepted provider step exhausted max_steps; next provider still prohibited. 7 crash/recovery scenarios PASS.
- Review P0 outstanding: TOOL reply+progress currently after lease release; must retain claim through progress commit. Changes remain uncommitted, not merge-ready.

## Progress under ownership
- Tool success reply/cursor commit callback now executes inside bound execution scope before lease release, including sealed historical replay. ConcurrentWriteError propagates without writing failure truth.
- New loop_progress_takeover: takeover before TOOL progress rejects old writer, cursor unchanged, new worker restores sealed outcome with dispatch count=1. 8 recovery scenarios pass.
- Terminal+persistence:77 passed. Scoped Ruff/Pyright clean.
- Earlier broad command used nonexistent test filenames and ran no tests; corrected to spine0_golden_path/e2_long_horizon_recovery/long_horizon_compensation.
- Independent re-review requested. Still uncommitted/unpushed/unreleased. Approval/UNKNOWN failure progress path and provider receipt-before-message gap remain open.

## Approval and failure ownership
- Ordinary generic exception records NODE_FAILED and TOOL/progress callback inside bound claim, before release.
- Approval success/error resolution writes held under claim; historical replay obtains reconciliation lease. ConcurrentWriteError propagates without resolution.
- Approval UNKNOWN pause binds held claim and releases only in finally.
- Prior terminal+e2 suite50passed; expanded compensation verification rerun. Independent review requested, specific approval takeover tests still required. No commit/push/release.

## UNKNOWN and correction pause
- Ordinary UNKNOWN acquires a fresh reconciliation claim before all reply/cursor/pause writes. Active takeover prevents closure; no effect redispatch.
- Approval correction pause uses held claim then finally releases. Stale responsibility fence now releases approval lease.
- Terminal+e2:50 passed; pyright/ruff/diff-check clean.
- Added loop_unknown_takeover test: tampered effect remains unsealed, old writer cannot advance cursor after takeover. Approval correction takeover test still outstanding.

## Provider response-to-message crash window
- Full typed ProviderResponse now retained in durable provider output. Exact node replay validates source receipt, digest, current profile digest and C7 epochs before returning recorded response. Historical rows missing full response fail closed.
- New crash test after provider commit/before assistant progress: recovery dispatches patch once and never appends second response for original node. PASS.
- Before added test:44 terminal tests passed, scoped pyright/ruff clean. Expanded five-module regression run started. Independent review requested. No commit/push/release; approval correction takeover and full regression/review still required.

## Provider C7 projection race
- Reviewer identified snapshot-to-assistant race. Ordinary progress now requires exact node provider receipt and uses receipt epochs in store append_guarded/append_fenced transaction.
- Scoped terminal before race test:45pass; task_service pyright/ruff clean.
- Provider window tests2pass: ordinary recovery + correction immediately before projection rejects append, no cursor and zero tool dispatch.
- Approval correction takeover test and full regression/review remain required. Uncommitted/unpushed/unreleased.
