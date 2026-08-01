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

Pending exact-head independent code review.
