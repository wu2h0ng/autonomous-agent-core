# Legacy W1/W2 Characterization Review

> Reviewer: `legacy_w1w2_characterizer` (read-only)
> Heads: `8c090f1604b83a6d10c3a1cbe6f557cfe1553e6e`, `a4afe1401671c3ea0dae3efde6ecf0284d5f9269`
> Disposition: `CHARACTERIZATION_ONLY / NO_REUSE_AS_IS / NO_FREEZE_OR_RESULT_EVIDENCE`

## P0 findings

1. Online control consumes `oracle_reward` before a stage-global seal (`transfer_monitor.py:22-26,108-124`; `harness.py:949-969`). This violates the external post-seal scorer topology.
2. `LocalCharacterizationCustody` is caller-seeded and same-process (`nonreducible_env.py:634-638,708-746,940-1045`); it cannot prove transcript-safe independent custody.
3. Both environments are single-family synthetic characterizations, not three prospective real families × five arms (`harness.py:174-251`; `nonreducible_env.py:37,682-746,1304-1327`). Ten thousand seeds do not increase N.
4. The arm set is not the approved five-arm set; `ScheduledKnownArm` owns the full schedule, the legacy adapter drops context, and resource equality is reduced to step count (`harness.py:118-169,334-359`; `nonreducible_env.py:1167-1201,1284-1324`).
5. Candidate and W1-only behavior substantially reduce to last-reward win-stay/lose-switch; the local causal flag checks only digest/action diversity and does not identify W1/W2 incremental value (`harness.py:442-472,516-554,654-694,1006-1019`; `w2_selector.py:286-313`).

## P1 findings

- W1 provenance is caller-asserted rather than bound to an accepted release schedule; rollback/restore does not prove descendant/reader closure (`w1_linter.py:34-53`; `w1_state.py:335-482,594-650`).
- Per-arm run authorization can complete one arm without a stage-global root, five bundles, global seal or stage one-shot receipt (`_authority.py:23-42`; `harness.py:1046-1094`).
- Legacy regret/recovery thresholds have no accepted new preregistration binding and cannot be inherited (`harness.py:720`; `nonreducible_env.py:37-40,870-937`).

## Module dispositions

- `REUSE_AS_IS`: none.
- `REUSE_AFTER_REWRITE`: canonical JSON/digest primitives; W1 append-only ledger and exact reader binding; immutable W2 option registry/decision receipt; exact-input receipt; tamper-evident CAS primitive; a minimal bounded-full-log skeleton.
- `CHARACTERIZATION_ONLY`: legacy harness, synthetic nonreducible environment, recovery/seed tests.
- `PARK`: checkpoint duplicate, online transfer monitor, local scorer/custody, scheduled/change-point/recency arms, legacy adapter, legacy metrics/gates and umbrella exports.

Only approximately 15–25% of the legacy code has donor value, and every donor requires rewrite against the new public contract. The 4,240/6,530 lines and green unit tests are engineering characterization, not admission evidence.
