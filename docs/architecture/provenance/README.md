# SPINE-1 Provenance — Generic Product-Core Decisions (HISTORICAL_NON_AUTHORITY)

> Status: `HISTORICAL_NON_AUTHORITY / RE-HOMED_PROVENANCE`
> Date re-homed: 2026-09-15
> Source donor: `ai-native-business-data-agent-os` @ `aaea36c694adb04664ff30fddccb43c2eb6a6614`
> Manifest: `docs/architecture/SPINE-1-DONOR-OWNER-COMPLETENESS-MANIFEST.yaml` (`D-DOCS-EXTRACT-INVARIANTS`)

These donor ADRs/architecture reviews explain **generic Product-core behavior** that is being carried
forward into Agent OS. They are re-homed here so a future implementer of the corresponding capability
(e.g. C7 execution-time recheck, ledger consequence preview, approval choice-set, governed decision
seam) has its original rationale.

They are **not** current authority:

- They describe the donor system, not this monorepo.
- Any capability they describe still needs a monorepo-native implementation, contract, failure path,
  tests and independent review. Re-homing a decision does not implement it.
- They do not authorize merge, release or a research claim.
