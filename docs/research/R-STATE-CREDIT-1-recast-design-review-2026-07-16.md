# R-STATE-CREDIT-1 Recast Design — Independent Review

> Date: 2026-07-16
> Reviewer: global-orchestrator / claude-code
> Status: `CONDITIONAL_APPROVE / DESIGN_ONLY / NOT_FROZEN / NOT_IMPLEMENTED`
> Scope: review the recast design packet at `f5fd8eb`; no code review, no run authority.

## Summary

The recast design packet directly addresses all six independent-review findings that led to `ARCHITECTURE_REVISE / PREREG_REVISE` for head `7852671`. It converts a fixed 24-event classification template into an interactive turn-based episode envelope, removes the A3 policy confound, introduces arm blinding and order balancing, and specifies a non-self-minting authority topology. The design is coherent and research-executable.

## Findings and required close conditions

| # | Topic | Assessment | Required before freeze |
|---|---|---|---|
| 1 | Instance independence | ACCEPTED in design. Seed must enter perturbation schedule, entity count, alias topology, valid-time offsets, and state transitions. | Pre-freeze diagnostic `test_instance_independence.py` must show no seven-template clustering; at least 30% of checkpoints within each family must have seed-dependent correct actions. |
| 2 | Public metadata leakage | ACCEPTED in design. Family and checkpoint must not predict sealed truth; public case files are blinded. | Dummy classifier using only `family + checkpoint` must not exceed chance on held-out seeds. |
| 3 | Authority non-self-minting | ACCEPTED in design. Distinct identities for builder, prereg reviewer, architecture reviewer, freezer, C7 owner, founder/CTO. | Mechanical verification that builder-generated authority files are rejected; real artifacts from distinct identities must exist. |
| 4 | Arm blinding and balancing | ACCEPTED in design. `arm_id` removed from actor request; neutral labels; randomized balanced order. | Qualification test: χ² uniformity, independence from family/seed, byte-level absence of arm names. |
| 5 | A3 policy confound | ACCEPTED in design. Option A removes `recovery_directive` from A3 output. | Test asserts no arm output contains directive or privileged action hint. |
| 6 | Interactive task envelope | ACCEPTED in design. 20–60 turn interactive loop with perturbations and seed-determined checkpoints. | Reversibility test passes for every family on development seeds; no external side effects. |

## Open concerns

1. **Effective sample size.** The design still targets 7 families × 20 seeds = 140 episodes. If the instance-independence diagnostic reveals residual template structure, the seed set or generator must be revised before freeze. The design correctly makes this a hard gate.
2. **Representation budget and pressure.** Section 3.3 says observations are released incrementally, but the design does not specify how A0 (full log) handles episodes that exceed a representation budget. A0 cannot truncate or select, so a budget overflow must have a defined fail-closed behavior.
3. **A0 truncation risk.** The requirement that "A0 remains mandatory strong full-log baseline; cannot truncate/select" may be impossible for 60-turn episodes with large observations. The design should define a maximum observation size per turn or admit that A0 receives the complete ordered tuple up to a hard cap, with overflow forcing `ABSTAIN`.
4. **Checkpoint trigger semantics.** "Seed-determined checkpoint triggers" are defined by perturbation terminal phase, but the exact deterministic rule is not specified. This must be frozen to prevent scorer drift.
5. **Authority artifact format.** The topology in §7.2 is clear, but the exact JSON schema, signature mechanism, and verification code are not specified. These must be added before freeze.

## Verdict

`CONDITIONAL_APPROVE` as a design candidate. The design is ready to be converted into a frozen preregistration candidate once the open concerns above are resolved and the pre-freeze gates in §9 are mechanically checked.

No implementation, no provider call, no training, no freeze, and no run are authorized by this review.

## Recommended next steps

1. Resolve open concerns 2–5 in a design amendment or add them as explicit freeze gates.
2. Produce a draft preregistration candidate JSON that instantiates §3–§8.
3. Implement the recast environment, corpus generator, arm blinding, and authority verification.
4. Run instance-independence, leakage, blinding/balancing, and policy-confound qualification tests on development seeds.
5. Seek independent preregistration and architecture-theory (RR-0029/RR-0031) review on the new exact bytes.
