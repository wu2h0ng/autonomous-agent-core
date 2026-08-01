# Verification

## Required slice

- `148 passed in 42.08s` across responsibility contracts, Agent CLI/AgentLoop, responsibility controller, terminal history, long-horizon compensation and E2 recovery.
- Real responsibility surface integration: same Task/Run, two separately approved edits, two admitted files, detached verifier, `OutcomeStatus.VERIFIED`, settlement, and at least two responsibility-ledger effects.
- Verifier custody attack: external secret unreadable, original `.agent_os` state unchanged, `/tmp` escape absent, failed candidate compensated.
- Changed-file Ruff: pass.
- Changed production-file Pyright: `0 errors, 0 warnings, 0 informations`.
- `git diff --check`: pass before commit.

## Broad product suite

- `1740 passed, 1 skipped, 18 failed in 110.53s`.
- Sixteen failures are pre-existing date-rot in `test_provider_trajectory_binding.py`: fixed 2026-07-31 commitment expiry is earlier than the current 2026-08-01 clock. The file reproduces `16 failed` alone and is outside this change.
- Two additional failures in the broad-order run (`test_spine0_golden_path...`, `test_correction_after_permit...`) both pass together in isolation (`2 passed in 1.17s`), so they are suite-order/time contamination rather than a deterministic slice regression.

## Review

- Exact reviewed code head: `b87a69ffc60cd338dbc331b0410654a7a4fc41d1`.
- Independent reviewer: `responsibility_exact_head_review` (read-only, not the writer).
- Verdict: `TECHNICAL_REVISE`.
- P0: an older Help approval is not typed/bound end-to-end to the exact current pending action and can be substituted under an invalid resume path.
- P0: precise-loop provider failure, interruption and three effect/receipt/tool-completion crash windows lack a complete reconciliation-or-reverse-compensation state machine.
- P0: exact external approval is enforced only by AgentLoop control flow, not by the ActionPipeline/Policy boundary; durable mode also does not require custody/fence inputs.
- P0: compensation mutations bypass responsibility effect custody.
- P1: reserved governance/approval/evaluator/C7 paths are not contract-denied; action execution remains duplicated between AgentLoop and RunCoordinator; the adapter can seal/start a missing Run instead of requiring the pre-bound Run.
- Merge/push: denied until all P0 findings are remediated and a new exact-head review approves them.

## Final exact-head review

- Exact reviewed code head: `6a68b677bf0db40d13a268f4f77df457addf7c4b`.
- Independent reviewer: `responsibility_exact_head_review` (read-only, not the writer).
- Verdict: `TECHNICAL_APPROVE`.
- P0: none.
- P1: none.
- The final remediation denies `packages/os_core/src/agent_os_core/agent_cli.py` through both `target_path` and `additional_target_paths`.
- Reviewer verification: `139 passed in 36.66s`; Ruff passed; `git diff --check cf1bf1f7..HEAD` passed; worktree clean.
- Claim ceiling: technical approval for this exact head and review scope only. It is not release authority, autonomy evidence, or proof that SELFDEV reaches the final blueprint.
