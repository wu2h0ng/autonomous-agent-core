# AGDE-T2 preregistration — interventions-in-time: the WHEN coordinate

- Date: 2026-07-04 · Composition gate unlocked by AGDE-2 MET (CTO sequencing interpretation disclosed).
- Scope disclosure (CTO): T2-minimal = WHEN-discrimination over 2 regime segments with the contemporaneous
  MEC pool (regime-dependent free-path weights: regime 0 scaled to 0.15 = sub-tolerance ≈ 0 bits; regime 1
  full). SSM lag-map hypothesis class deferred to T3. Structure/pool/truth shared across regimes = the
  invariant; only WHEN carries extra bits.
- Claim (bounded): choosing WHEN adds identification value beyond choosing WHAT: A_tw (active over
  node×segment) beats A_wr (active node GIVEN random segment) by ≥ 0.15 mean ID at equal do()-budget,
  with A_tw ≥ 0.90 absolute, under the identical frozen verifier.
- Frozen: families first-30-valid from seed 300 (fresh; gate-1: 100s, gate-2: 200s, calib: 1000s), runs
  {30,31,32}, B=2, tol=0.6, n_int=100, c=2.0. Mechanism files byte-unchanged from AGDE-1/2 freeze;
  `experiments/agde_t2.py` = `63479f0d40010a58`.
- Decision (mechanical): MET iff mean ID A_tw ≥ 0.90 AND (A_tw − A_wr) ≥ 0.15 AND A_tw>A_wr on ≥2/3
  decided families AND controls (byte-determinism of A_tw, gate audit ≤B approvals). NULL else; INVALID
  on control failure. No rescue.
- Frozen prediction (RR-0044 ledger): regime-0 do() ≈ 0 bits ⇒ A_wr wastes ~half its budget ⇒ expected
  A_tw ≈ 0.95, A_wr ≈ 0.55–0.70, WHEN-gap ≈ 0.25–0.40. **MET ~75%.** Calibration smoke (1 family):
  A_tw 1.0 / A_wr 0.5 / R_tw 0.33 — consistent. NULL tails: fresh-family variance; regime-0 weak weights
  leaking above tolerance on some families (would shrink the gap).

## Result
_(appended by the scored run)_
