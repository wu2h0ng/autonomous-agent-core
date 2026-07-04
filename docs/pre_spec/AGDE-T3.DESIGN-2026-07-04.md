# AGDE-T3 design — SVAR dynamics: the hypothesis class becomes TEMPORAL (freeze-ready; run next session)

## Claim (bounded)
The governed discovery loop identifies STRUCTURAL-VAR structure — contemporaneous DAG (the observation-
unidentified MEC fraction) × lagged-edge support — from trajectories, with interventions (window-clamps)
resolving what observation cannot, at the information-feasible budget. Upgrade over T2: T2's hypothesis
class was static-MEC with a WHEN coordinate; T3's hypothesis class IS dynamical (trajectory-consuming
verifier, lagged structure co-identified).

## Arena (pure stdlib; spectral radius < 1 enforced)
x_t = C x_t + A x_{t-1} + eps (SVAR): n=6; contemporaneous skeleton with MEC_c >= 4 (pinned+free mix);
lagged candidates = 3 frozen node-pairs, true support a random subset -> pool = MEC_c x 2^3 (32-64).
do(k) = clamp node k for a T_do window; verifier compares measured late-window means + lag-1 cross-
covariances against each hypothesis's fitted linear fixed-point prediction (OLS per node on
[contemporaneous parents, lagged parents]; closed form, deterministic). Signature = quantised
(means ++ lag-covs) vector; chooser/prune/gate/ledger UNCHANGED (byte-frozen mechanisms).

## Protocol self-check (pre-answered — the discipline that failed 4x today, applied while fresh)
1. Referee reachable? Grade vs measured truth-blind ceiling at the frozen budget (compute per family in
   the PILOT, as AGDE-2 learned; never a truth-informed oracle at a blind-infeasible budget).
2. Bars have room? PILOT first (calib seeds): measure t1 cost, id ceiling, lag-part identifiability from
   observation alone (Granger arm — the CHEAP BASELINE: if lagged support + MEC-c resolve observationally,
   the gate is vacuous -> arena must make the contemporaneous fraction carry >= 1 bit beyond Granger).
3. Bandwidth matches uncertainty? tol calibrated on pilot (truth survival >= 0.99), late-window length
   set so mean-SE << tol.
4. Trust semantics: no caching in T3 (single-task gate) — no trust surface.
KILL-CONDITIONS (pre-freeze): Granger-alone resolves everything (vacuous); stability filter rejects
> 60% of random draws (arena too narrow); pilot t1 < 2 (no room for choice value).

## Decision (mechanical, to freeze after pilot)
ID score over (contemporaneous, lagged) joint structure; arms: ACTIVE (min-max over window-clamp
signatures) / RANDOM / GRANGER+ACTIVE-residual / measured blind ceiling. MET iff active captures >= 0.5
of the (blind-ceiling - random) gap at the pilot-set budget AND Granger-arm gap confirms the
interventional fraction is real AND controls (determinism, gate audit, perm-collapse, halt) pass.

## PILOT RESULT (2026-07-04, calib families 9000-9004; NO freeze — the pilot did its job)

- **K3 CLEAN (arena has real interventional content):** obs screen shrinks the 96-pool to 45% but
  orientation resolved 0/5 (no vacuity), truth survives obs screen 5/5.
- **K2 RED (apparatus not sound yet):** truth survival on its OWN clamp data only 0.72-0.83 even at
  tol 0.9 (must be >= 0.99). Suspected implementation bug in predict_clamp's fixed-point propagation
  (hasty inner/outer loop mixing — late-session code slip, exactly what the pilots-before-bars rule
  exists to catch). NEXT SESSION FIRST TASK: rewrite predict_clamp cleanly (solve the linear
  fixed point directly per hypothesis), re-pilot K2, THEN freeze. Tonight's freeze would have been
  checklist-miss #5; the pilot prevented it.

## PILOT v2 (2026-07-04, predictor rewritten as EXACT linear fixed-point solve): **APPARATUS SOUND**

K2 GREEN: truth survival on own clamp data **1.000 at every tol {0.5, 0.7, 0.9}** (buggy iterator gave
0.72-0.83; the exact solve fixed it completely). K3 unchanged-clean (orientation 0/5 obs-resolved;
truth 5/5 survives obs screen; pool 96). All three kill conditions CLEAR. T3 is freeze-ready.
NEXT SESSION (per the first-half-freeze rule): (1) cost/gap pilot (t1 active cost + measured blind
ceiling at candidate budgets, calib seeds) -> (2) set bars from those numbers -> (3) freeze -> (4) run.
Tolerance candidate: 0.5 (tightest green).

## COST/GAP PILOT (2026-07-04): **arena separation INSUFFICIENT — third arena-physics catch, no freeze**

Identification near zero for BOTH policies (active 0.083, random 0.000 at every B in {3..6}) while K2
truth-survival is 1.000: the prune never wrongly kills truth but barely kills ALTERNATIVES — the
stability scaling (row-sum cap 0.85 over C+A jointly) shrinks effective weights until inter-hypothesis
clamp-prediction differences fall below tol 0.5; 96 hypotheses are mutually indistinguishable at this
effect size. NEXT-SESSION FIX (design judgment, per the freeze rule): re-derive separation — raise
do_value and/or manage stability with a per-matrix cap instead of joint row-sums, and/or set tol from
the MEASURED inter-hypothesis separation distribution (separation-aware tolerance), then re-run this
pilot until active_id >= 0.7 with a real gap, THEN freeze. Pilot lineage for T3: v1 caught the predictor
bug; v2 validated the verifier; v3 caught the separation deficit — three would-be broken freezes
prevented at calibration cost only.

## SEPARATION MEASUREMENT + PILOT v4 (2026-07-04): **root cause = NESTED HYPOTHESES (textbook)**

sep median 0.619 but **q25 = 0.001**: a quarter of hypothesis pairs are prediction-EQUIVALENT — a
superset hypothesis (adding a lag edge the world lacks) fits coefficient ~0 and becomes empirically
identical to the true structure. No do_value scaling can separate them (v4 at derived c=3.2: active_id
only 0.25). **Unique identification against supersets is ILL-POSED for any prediction-based verifier —
the classical causal-minimality issue.** NEXT-SESSION MECHANISM (frozen principle, not a knob): causal
minimality — collapse surviving prediction-equivalent hypotheses to the minimal-edge representative
before scoring; re-pilot; THEN freeze. T3 pilot lineage now four catches: predictor bug -> verifier
sound -> separation deficit -> NESTING/minimality — four would-be-broken freezes prevented at
calibration cost. The freeze that eventually happens will be earned.

## PILOT v5 (2026-07-04): **causal-minimality collapse makes T3 freeze-input-ready**

Mechanism: after ordinary trajectory pruning, collapse survivors by the classical causal-minimality
principle: if all survivors share one contemporaneous orientation and the minimal lag-subset is unique,
score that minimal representative; otherwise remain unidentified. This does not make a prediction-only
superset empirically separable. It makes the equivalence-class convention explicit before scoring.

Calibration result (`experiments/agde_t3_pilot5.result.json`, families 9000..9005, runs 0..1, tol 0.5):

| config | active_id | random_id | gap |
|---|---:|---:|---:|
| c=2.0, B=4 | 0.333 | 0.083 | 0.250 |
| c=2.0, B=5 | 0.417 | 0.083 | 0.333 |
| c=3.2, B=4 | **0.750** | 0.417 | **0.333** |
| c=3.2, B=5 | **0.750** | 0.417 | **0.333** |

Interpretation: v5 is still **calibration only, not freeze/r-final/verdict**. It clears the prior
apparatus blocker and provides concrete freeze inputs: `do_value=3.2`, `budget=4` is the cheaper
candidate setting; `budget=5` adds no pilot benefit. Next legitimate step is a prereg/freeze packet
using fresh families/seeds, explicit blind-ceiling/random baselines, C7 halt guards, and a result schema
that preserves `calibration_pilot_not_freeze` as non-claim evidence.

## FRESH SCORED GATE (2026-07-04): **NULL**

The freeze/scoring packet (`AGDE-T3.PREREG-2026-07-04.md`) used the v5 inputs on fresh families
`9100..9111` and runs `{40,41}`. Controls passed: fresh-family exclusion, deterministic ACTIVE replay,
budget/gate audit, and C7 halt guard. Mechanical result: ACTIVE `0.5000`, RANDOM `0.2083`,
BLIND_CEILING `0.5000`, capture `1.0000`, ACTIVE > RANDOM on `8/9` decided cases.

Verdict: **NULL**, because ACTIVE misses the absolute identification bar `0.70`. Honest reading:
temporal active choice beats random, but the current temporal verifier/minimality convention only
identifies half the fresh SVAR cases. Do not lower the bar, rescue seeds, reinterpret the pilot as a
win, or promote a temporal-dynamics claim. The next route is failure diagnosis or the queued `5e-2`
knowledge-channel gate.

## PILOT v5 (2026-07-04): **GREEN — minimality collapse works; freeze inputs COMPLETE**

| config | active_id | random_id | gap |
|---|---|---|---|
| c=2.0 B=4/5 | 0.333 / 0.417 | 0.083 | 0.25 / 0.33 |
| **c=3.2 B=4** | **0.750** | 0.417 | **0.333** |
| c=3.2 B=5 | 0.750 | 0.417 | 0.333 (no gain over B=4) |

FROZEN-INPUT SET for next session's gate (all pilot-verified, zero judgment left):
tol=0.5 (truth-survival 1.000) · do_value=3.2 (arithmetic-derived from measured separation, verified) ·
causal-minimality collapse (classical frozen principle; kills the nesting ill-posedness) · B=4 (the
information-feasible point; B=5 adds nothing) · measured reference points active 0.750 / random 0.417.
Five-pilot lineage: predictor bug -> verifier sound -> separation deficit -> nesting root-cause ->
minimality green. Next session: set capture-relative bars from these numbers, freeze, score on fresh
families (9100+), runs fresh.
