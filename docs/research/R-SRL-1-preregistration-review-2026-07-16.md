# R-SRL-1 Preregistration — Independent Methodology Review

> Reviewer: Independent methodology reviewer  
> Date: 2026-07-16  
> Reviewed document: `docs/research/R-SRL-1-preregistration-2026-07-16.md`  
> Supporting context: `docs/research/situated-responsibility-loop-architecture-2026-07-16.md`, `docs/architecture/A-SRL-1-threat-model-and-authority-invariants.md`, `docs/research/RR-0024-operational-foundations-cleanup.md`

## Summary verdict: CONDITIONAL_APPROVE

The preregistration is methodologically sound in principle: it uses a falsifiable joint gate, strong matched baselines, explicit leakage controls, decisive negative-result verdicts and adequate adjudication blinding. However, it cannot be frozen until **P0** inconsistencies and missing preconditions are resolved. The **P1** items should be closed before run because they materially affect interpretability and anti-leakage defensibility.

---

## P0 findings (must fix before freeze)

### P0-1. Event-count inconsistency
Section 3.2 calls each unit a “sealed **eight-event** sequence,” but Section 3.4 lists **nine** required event types. These must agree. If the decoy is the ninth event, update the unit definition to “nine-event sequence”; if one type is optional, state that explicitly and reconcile the count.

### P0-2. Primary hypothesis vs. success criterion mismatch
- Hypothesis (Section 2): HCW ≤ 70% of the **better baseline** and outcomes/HCW ≥ 1.30× the **better baseline**.
- Criterion (Section 8): HCW ≤ 70% of **each baseline**.

These are not equivalent. Requiring ≤70% of *each* baseline is stricter and changes the power claim. Pre-register exactly one gate and justify the choice.

### P0-3. Missing safety/contract precondition
The prereg depends on `A-SRL-1` but does not state that all machine-testable invariants in `A-SRL-1` §5 must be demonstrated by RED tests **before** the result-bearing run. Add a frozen precondition: every invariant I-1 through I-25 (or the applicable V1/RT subset) must have a failing test that passes only when the Runtime enforces it, and the test suite must be green at freeze.

### P0-4. “Verified outcomes per HCW minute” is under-operationalized
The compound secondary metric used in the joint gate lacks a precise numerator. Define:
- what counts as a verified outcome unit (commitment satisfied, failing test fixed, drift detected, etc.);
- how partial outcomes are scored;
- whether outcomes are weighted by difficulty or counted as binary;
- who applies the verdict (the `DeterministicOutcomeEvaluator` alone, or rater-confirmed).

---

## P1 findings (should fix before freeze)

### P1-1. Operator blinding limitation is not acknowledged
Arm 2 (user-driven) inherently requires the operator to know they are driving; Arm 3 requires handling `HelpRequest`s. Full operator blinding is impossible, but adjudicator blinding is claimed. State explicitly that operators are **not** blind to arm identity, that adjudicators are, and list the residual bias controls (e.g., standardized operator instructions, prohibited coaching, scripted prompts).

### P1-2. “Restart state equivalence ≥ 8/9” is undefined
Section 8 requires restart state equivalence in at least 8/9 units but does not define equivalence. Specify the comparator (post-restart state vs. pre-interruption state, vs. ground-truth expected state), the fields checked (commitment portfolio, active goals, pending HelpRequests, belief checksums), and the scorer.

### P1-3. Missing structural ablation
Two strong baselines are included, but there is no ablation isolating the SRL machinery itself. Add at least one of:
- **Persistent-state-only arm**: same memory/event access as SRL but no Mandate/Commitment/Relevance structure (executes via fixed heuristic or simple loop);
- **No-help-limit arm**: same loop without HelpRequest burden budget, to measure how much of the HCW reduction comes from disciplined escalation rather than state persistence.

Without this, a reduction could be attributed to persistent memory rather than the SRL design.

### P1-4. Implementer / unit-designer separation not addressed
Leakage risk exists if the same people who designed the event sequences also implemented the SRL. Pre-register a separation rule: unit authors, SRL implementers and operators should be disjoint roles, or if overlap is unavoidable, disclose it and add a held-out unit set designed by an independent party.

### P1-5. HCW category scheme not specified for kappa
Section 6.1 requires category kappa ≥ 0.75 but does not list the categories raters use. Define the category taxonomy (e.g., `DISCOVER`, `RESTATE`, `GOAL_FORM`, `LOCATE`, `PRIORITIZE`, `INTERPRET`, `REPEAT`, `AUTH`, `WAIT`, `OTHER`) before freeze so kappa is computable and reproducible.

### P1-6. “Public state” sharing needs clarification
Section 4 says arms share “public state,” but the SRL arm is defined by persistent mission/commitment state. Clarify what state is arm-specific vs. shared, and how the baselines are given equivalent read access to any shared state without also receiving SRL-internal structures (e.g., relevance assessments, commitment portfolio).

---

## P2 findings (nice to have)

### P2-1. Event sequence is highly structured
Requiring exactly one of each event type per timeline improves measurement but reduces ecological validity. Consider pre-registering one naturalistic validation stream as a secondary robustness check, or report the artificiality as a boundary in Section 13.

### P2-2. Add a cheap “indiscriminate help” baseline
A trivial baseline that emits a `HelpRequest` on every non-obvious event would calibrate the HelpRequest precision/recall burden floor and strengthen the claim that SRL’s help discipline is non-trivial.

### P2-3. Pre-register missing-data handling
State how units are handled if a rater pair fails to meet reliability, if an arm crashes, or if an operator cannot complete a unit. Default to `INVALID` is acceptable, but should be explicit.

### P2-4. Wall-clock budget enforcement
Section 4 says arms share a wall-clock budget but does not state the value or the enforcement rule. Add the budget and the consequence of exceeding it (e.g., unit marked `INVALID` for that arm).

---

## Open questions

1. **Operator pool**: Are the same operators used across all arms? If operator skill varies, how is that counterbalanced? Latin-square balances order but not operator-task interaction.
2. **AUTH labeling**: Who decides which events contain “genuinely irreducible” human judgment, and is this label available to raters but not to arms?
3. **Mission-pass threshold**: What exactly is “mission pass and verified commitment outcomes no worse than the better baseline”? Is this a binary pass/fail per unit or a continuous score?
4. **Pilot calibration**: Is there a pre-registered pilot to validate HCW annotation and event timing, and if so, are pilot units excluded from the 8/9 count?
5. **Provider/model lock**: Section 4 mentions exact provider/model revision, but the prereg does not specify how model-version drift during the run will be detected and invalidated.

---

## Required changes

1. Fix the event-count inconsistency (P0-1): align “eight-event” with the nine listed event types.
2. Align the primary hypothesis and success criterion to a single pre-registered gate (P0-2).
3. Add a frozen precondition requiring `A-SRL-1` invariant RED tests to pass before run (P0-3).
4. Operationalize the “verified outcomes per HCW minute” numerator, weighting and scorer (P0-4).
5. Add an explicit statement on operator non-blinding and adjudicator blinding controls (P1-1).
6. Define restart-state equivalence, comparator and scorer (P1-2).
7. Add at least one structural ablation arm or justify its absence (P1-3).
8. Pre-register a separation rule between unit designers, SRL implementers and operators (P1-4).
9. Publish the HCW category taxonomy used for kappa computation (P1-5).
10. Clarify what “public state” is shared and how baselines receive equivalent access without SRL-internal structures (P1-6).

Once P0 items are resolved and P1 items are addressed or explicitly deferred with rationale, the preregistration can move to `FROZEN` pending environment/scorer freeze.
