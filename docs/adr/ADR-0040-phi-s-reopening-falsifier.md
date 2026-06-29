# ADR-0040: φ_S Reopening Falsifier — does a fixed prior yield an irreducible control signal under fair online acquisition?

- Status: **PREREGISTERED (DRAFT, awaiting cross-model prereg review + opencode freeze)**. Decides nothing until frozen.
- Date: 2026-06-29
- Deciders: founder approved reopening + authorized the run/review loop (2026-06-29). Builder/reviewer firewall declared below.
- Predecessors: ADR-0037 (SD4/Q2), `docs/CONSTRUCTION-AUDIT-CROSSMODEL-REOPEN-2026-06-29.md` (the reopen cast), `docs/research/thin-readout-law-...-2026-06-28.md`.

## Context (why this experiment, and what it can / cannot resolve)
The cross-model-verified reopen cast withdrew "enrich-S autonomy is FORECLOSED under C6." The surviving construction was a fixed encoder `z_t = φ_S(x_t)` outside closure(B_K). The irreducible crux is a **quantifier-order / no-free-lunch modeling choice** (∀env∃useful-S vs ∀S random-env). An experiment CANNOT decide a modeling choice. It CAN locate, quantitatively, **where the choice bites**: the minimal baseline-acquisition budget at which the organ's fixed-prior advantage collapses.

**Honest framing (load-bearing, anti-self-deception):** a fair test tends toward H0 (a baseline given a fair acquisition opportunity recovers φ* and ties); H1 is reachable trivially by making φ* cryptographically unlearnable (the candidate-9 strawman the doc warns against). Therefore the PRIMARY deliverable is NOT a binary verdict but the **advantage curve** `adv(ORGAN, BASE-FAIR)` as a function of the baseline's frozen acquisition budget. The crossover is the quantified answer; the founder rules which side of it is "free prior" vs "privileged side-information."

## Hypotheses
- **H0 (foreclosure holds):** with a fair, frozen online-acquisition opportunity on the same observation channel, BASE-FAIR ties ORGAN (adv ≤ δ). The fixed prior was pre-paid acquisition, not irreducibility.
- **H1 (reopen confirmed for this signal class):** ORGAN beats BASE-FAIR by adv ≥ δ on frozen final seeds, AND the acquisition diagnostic shows BASE-FAIR provably cannot recover φ* within the frozen acquisition budget on the observation channel (no privileged-label leak).

## FROZEN prior-fairness convention (the load-bearing freeze — set BEFORE any run)
1. ORGAN receives a fixed encoder φ* as a free architectural prior (NOT fit on this env's reward).
2. BASE-FAIR receives: (a) the SAME run-time recurrence/memory budget K/M as ORGAN; AND (b) a fair ONLINE acquisition phase on the SAME observation channel ORGAN saw, with a frozen acquisition budget (steps × compute) and an unrestricted in-budget learner class. BASE-FAIR is DENIED only the privileged labeled-context channel (the one C6 forbids as an oracle).
3. The acquisition budget is swept on a FROZEN grid (the curve), not chosen post-hoc.
4. φ* is a NATURAL high-order readout (below), NOT a cryptographic gadget. If φ* is only separable because it is crypto-hard, the result is declared VACUOUS (H1-trivial), not a reopen.

## Environment (frozen)
Non-bijective long-horizon ecology; optimal action depends on a high-order readout:
`a* = sign[ (c_i at state-selected lag k) ⊗ (c_j now) ]`, `k = f(c_slow)`; `|A| = 2`; a **discrete payoff cliff** at the XOR flip so paid regret is bounded away from 0 (closes the "errors only where regret→0" escape). This is the thin-readout-law §5 env, repurposed from foreclosure-test to reopening-test.

## Arms (pre-specified)
| Arm | Encoder | Acquisition | Purpose |
|---|---|---|---|
| `ORGAN` | fixed φ* (free prior) | none needed | the enrich-S candidate |
| `BASE-FAIR` | closure(B_K) + bounded recurrence | frozen online-acquisition sweep on observation channel | the fair baseline (the decisive comparator) |
| `BASE-NAIVE` | closure(B_K), geometric only | none | sanity floor (must lose) |
| `ORACLE` | knows φ* + lag k | none | upper bound / regret normalizer |

## Metrics
- Primary: post-decision regret area (lower better); report `adv(ORGAN, X) = 1 − area(ORGAN)/area(X)`.
- Primary deliverable: `adv(ORGAN, BASE-FAIR)` vs frozen acquisition budget (the curve).
- Diagnostic: BASE-FAIR's recovered-φ* accuracy vs acquisition budget (did it acquire the readout?).
- Paired per-seed differences, Wilcoxon one-sided, bootstrap 95% CI.

## Pre-registered decision rule (binary, on frozen final seeds, no threshold movement)
- **H0** if `adv(ORGAN, BASE-FAIR) ≤ δ` at the frozen "fair" acquisition budget (BASE-FAIR ties) → SD4/Q2 stays NEGATIVE (foreclosure holds under fair acquisition).
- **H1** if `adv(ORGAN, BASE-FAIR) ≥ δ` AND BASE-FAIR φ*-recovery < chance+ε at that budget → reopen CONFIRMED for this signal class.
- **VACUOUS** if H1 holds only because φ* is crypto-hard (recovery stays at chance for ALL budgets including unbounded-but-fair).
- **INCONCLUSIVE** otherwise; report the curve and the crossover budget regardless.
- `δ`, `ε`, the acquisition-budget grid, seeds, env, and φ* are FROZEN before running.

## Seeds (frozen, disjoint)
- Calibration: 2000..2019. R-final: 2100..2129. (Calibration may tune nothing in the mechanism; only confirms the harness runs.)

## Builder / reviewer firewall (CLAUDE rule 23: builder_id ≠ reviewed_by)
- prereg author: Claude. **prereg reviewer (cross-model, builder≠reviewer): Kimi.** freezer (independent): opencode. mechanism builder: Codex. result adjudicator (cross-model): Kimi. conclusion / final verdict cast: founder.
- No arm/threshold/φ*/budget retune after freeze without a NEW founder ADR + fresh seeds.

## C6/C7 guards
- φ* is a deterministic function of the observation buffer (bounded-memory observation), kept out of the correction path; no oracle/privileged control surface at run-time; pause/forbidden dominance unchanged. The ONLY admitted asymmetry under test is the prior-fairness convention (acquisition), which is exactly the founder-reserved modeling axis.

## Disposition possibilities
| Outcome | Meaning |
|---|---|
| H0 | foreclosure holds under fair acquisition; SD4 bet stays negative; reopen retracted |
| H1 (non-vacuous) | a fixed natural prior yields an irreducible control signal; enrich-S autonomy is a real lever for this signal class; next: characterize the class |
| VACUOUS | separation is crypto-artifact; no real reopen; record and park |
| Curve + crossover | the quantified prior-fairness boundary; founder rules where "free prior" ends |
