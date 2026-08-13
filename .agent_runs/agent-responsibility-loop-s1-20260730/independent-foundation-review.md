# Independent Foundation Review

> Verdict: `TECHNICAL_REVISE_FOUNDATION`
> Reviewed range: `cb86bf252864df368a5add98b541544c1c2ccbc6..3cbaf820b90b760b7ef8c37269000712a5d03808`
> Reviewer: `responsibility_foundation_review` (read-only Codex subagent)
> Findings: `P0=0 / P1=5 / P2=1`

## P1 findings

1. `binding_digest` contains repository/configuration/correction state but is
   also the lease primary key. The same Mandate/workspace can therefore acquire
   multiple live leases after binding drift. A stable `lease_scope_id` must own
   the lease row; changed authority/configuration must fail closed until an
   explicit inactive rebind.
2. `execute_effect` holds the shared lock across the external callback and
   rechecks the fence using the old caller-provided timestamp. A long effect can
   cross TTL while blocking takeover and still be marked `APPLIED`. Runtime
   time must come from a trusted store clock; external dispatch must not hold
   the takeover lock; post-effect expiry/takeover must become `UNKNOWN`.
3. `APPLIED` has no typed, content-bound effect receipt. Callback success alone
   is not evidence of a durable effect. Persist and verify a canonical receipt
   digest before `APPLIED`; otherwise retain `PREPARED/UNKNOWN`.
4. HCW accepted-outcome counting defaults missing `cycle_id` to the requested
   cycle, so every historical `SETTLED_MET` can enter every denominator. Require
   an immutable cycle-to-task/run-to-settlement binding and exact
   Mandate/workspace scope; missing binding means `HCW_INSUFFICIENT_DATA`.
5. Checkpoints lack head CAS and monotonic sequence enforcement. A later
   caller-provided timestamp can make sequence 1 replace sequence 10, while a
   changed binding appears as no checkpoint instead of drift.

## P2 finding

The eight tests use two process identifiers in one Python process. They do not
exercise OS-process lock contention, kill/crash recovery, long effects crossing
TTL, same-scope binding drift, or a real Outcome Portfolio settlement ledger.

## Claim boundary

The reviewed head is only:

`LOCAL_PERSISTENCE_PROTOTYPE / 8_TARGETED_UNIT_TESTS_GREEN / FOUNDATION_NOT_APPROVED`

The complete product item remains:

`IMPLEMENTATION_INCOMPLETE / PRODUCT_LOOP_NOT_INTEGRATED / NOT_APPROVED / NOT_MERGED / NOT_RELEASED`

No HCW reduction, sustained responsibility, self-improvement, release or
`Autonomy(S,E,O,V,T)` claim follows.
