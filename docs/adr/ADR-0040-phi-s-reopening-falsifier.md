# ADR-0040: φ_S Reopening Falsifier — does a fixed prior yield an irreducible control signal under fair, representation-symmetric online acquisition?

- Status: **PREREGISTERED (DRAFT v2, revised per Kimi prereg-review round 1; awaiting re-review + opencode freeze)**. Decides nothing until frozen.
- Date: 2026-06-29
- Deciders: founder approved reopening + authorized the run/review loop (2026-06-29). Builder/reviewer firewall below.
- Predecessors: ADR-0037 (SD4/Q2), `docs/CONSTRUCTION-AUDIT-CROSSMODEL-REOPEN-2026-06-29.md`, `docs/research/thin-readout-law-...-2026-06-28.md`.
- Revision note: v1 was REVISED by cross-model review (Kimi): v1's BASE-FAIR was locked to low-order closure(B_K) so the test could not yield H0 (rigged toward reopen). v2 makes the baseline representation-symmetric, freezes φ* provenance, anchors the budget to a learnability horizon, splits H1 into sample-efficiency vs irreducible-gap, and adds the INPUT-DENIED category + ORACLE-FEATURE diagnostic.

## Context — what this can and cannot resolve
The reopen cast rests on a quantifier-order / no-free-lunch modeling choice an experiment cannot decide. This falsifier LOCATES the choice quantitatively and, under a fair representation-symmetric baseline, tests whether ANY empirical irreducibility remains once the candidate-9 strawman (feature-starved baseline) is removed. **Honest prior:** with a representation-symmetric baseline, observable state, and unbounded fair budget, a low-description-length φ* is very likely RECOVERABLE → the result leans H0; the reopen then survives only under the contested acquisition convention, which the curve quantifies and the founder rules.

## Hypotheses (split per review)
- **H0 (foreclosure holds under fair acquisition):** BASE-FAIR ties ORGAN (adv ≤ δ) by the learnability horizon.
- **H1a (sample-efficiency only, NOT a reopen):** ORGAN beats BASE-FAIR at low budget, but BASE-FAIR converges to a tie by the learnability horizon. The fixed prior was pre-paid acquisition, not irreducibility.
- **H1b (REOPEN confirmed):** BASE-FAIR fails to recover φ* and stays beaten by adv ≥ δ **even at/beyond the learnability horizon with unbounded fair budget**, AND it is NOT INPUT-DENIED (the ORACLE-FEATURE arm recovers the policy), AND NOT VACUOUS. Only H1b reopens enrich-S for this signal class.
- **INPUT-DENIED (fairness-convention failure, not a result):** BASE-FAIR fails but ORACLE-FEATURE-BASE (which receives φ*(x_t) as input) succeeds in budget → the gap is representation/input denial, a rigged convention; re-design required.

## FROZEN φ* provenance (fix 1, 5 — set BEFORE env design)
- φ* is drawn from a **pre-specified archive A** of low-description-length, interpretable readouts fixed BEFORE the env: {k-bit parity over a SMALL fixed OBSERVABLE index set (k ≤ 4); low-degree (≤3) polynomial threshold; small (≤5-gate) Boolean circuit over observable variables}. Description-length bound L is frozen.
- φ* is INDEPENDENT of this env's reward/label stream; it is NOT permitted to be the env's hand-tuned optimal readout. The env is then drawn in two conditions: **ALIGNED** (env optimum = φ*) and **MISALIGNED** (env optimum = a different archive readout) — the prior helps only if alignment is real and irreducible.
- Excluded: secret random subsets, large parity, cryptographic hashes (→ VACUOUS by definition).

## Environment (fix 7 — full observability)
Non-bijective long-horizon ecology; optimal action `a* = readout(observable history)`, readout drawn from A. ALL state needed for a* — including c_slow and the lag selector k — is OBSERVABLE in the shared channel (else the experiment is a hidden-state inference test, not a prior-fairness test). Discrete payoff cliff so paid regret is bounded away from 0. |A| = 2.

## Arms (fix 2, and the ORACLE-FEATURE diagnostic)
| Arm | Representation | Acquisition | Purpose |
|---|---|---|---|
| `ORGAN` | fixed φ* | none | enrich-S candidate |
| `BASE-FAIR` | **representation-symmetric**: same raw channel + same admissible-recurrence family as ORGAN (arbitrary bounded Boolean latches up to ORGAN's buffer capacity M) + in-budget online learner over that family | frozen acquisition-budget sweep | the decisive comparator |
| `ORACLE-FEATURE-BASE` | BASE-FAIR + receives φ*(x_t) as an extra input | same sweep | INPUT-DENIED detector |
| `BASE-NAIVE` | geometric closure only | none | sanity floor (must lose) |
| `ORACLE` | knows the env readout + k | none | regret normalizer |

## Learnability horizon (fix 3)
The "fair" budget is not an arbitrary grid point: it is anchored to the budget B* at which an **oracle-initialized BASE-FAIR** (handed φ* at init) converges to within η of ORGAN. The acquisition sweep covers [small ... B* ... ≫B* (unbounded-fair proxy)]. H1b requires ORGAN's advantage to persist at ≫B*.

## Pre-registered, frozen quantities (fix 4)
Exact BASE-FAIR feature/recurrence class; exact φ* archive A + description-length bound L; the acquisition-budget grid; δ, ε, η; the φ*-recovery metric (accuracy of BASE-FAIR's learned readout vs φ* on held-out observations); seeds. Include in the freeze artifact a proof-sketch that BASE-FAIR's family CAN represent every φ* ∈ A given its inputs (so any failure is acquisition, not representability).

## Decision rule (binary, frozen final seeds, no threshold movement)
- **H0** if adv(ORGAN, BASE-FAIR) ≤ δ at B*.
- **H1a** if adv ≥ δ at small budget but ≤ δ at B* (converges) → not a reopen; record sample-efficiency curve.
- **H1b (REOPEN)** if adv ≥ δ at ≫B* AND BASE-FAIR φ*-recovery < chance+ε AND ORACLE-FEATURE-BASE ties ORGAN (not INPUT-DENIED) AND not VACUOUS.
- **INPUT-DENIED** if BASE-FAIR fails but ORACLE-FEATURE-BASE ties → redesign (rig).
- **VACUOUS** per the operationalization below.
- Primary deliverable regardless: the curve adv(ORGAN, BASE-FAIR) vs budget, in ALIGNED and MISALIGNED conditions, with the crossover budget.

## VACUOUS operationalization (per review)
VACUOUS iff (i) φ* is provably hard for the frozen fair learner class under a stated computational model (statistical-query / finite-automaton) even with unbounded fair observations + compute, OR (ii) φ* exceeds the frozen description-length bound L (secret random params, large parity, crypto hash). NOT vacuous if BASE-FAIR fails only on input representation — that is INPUT-DENIED (a convention failure), detected by the ORACLE-FEATURE arm.

## Seeds (frozen, disjoint)
Calibration 2000..2019 (tunes nothing in the mechanism; confirms harness + sets B* only). R-final 2100..2129.

## Builder / reviewer firewall (CLAUDE rule 23)
prereg author: Claude. prereg reviewer (cross-model): Kimi. freezer (independent): opencode. mechanism builder: Codex. result adjudicator (cross-model): Kimi. final verdict cast: founder. builder_id ≠ reviewed_by. No retune after freeze without a new founder ADR + fresh seeds.

## C6/C7 guards
φ* is a deterministic function of the observation buffer (bounded-memory observation), out of the correction path; no run-time oracle/privileged control surface; pause/forbidden dominance unchanged. The ONLY asymmetry under test is the acquisition convention — the founder-reserved modeling axis.
