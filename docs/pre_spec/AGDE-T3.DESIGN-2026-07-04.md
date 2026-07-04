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
