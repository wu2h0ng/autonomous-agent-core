# AGDE-2 preregistration — full identification at the information-feasible budget

- **Date:** 2026-07-04 · **Relation to AGDE-1:** AGDE-1 = **NULL as frozen and stays NULL** (capture 0.4895
  < 0.50 vs a truth-informed oracle at B=1). AGDE-2 is a **NEW, better-posed claim on FRESH families** —
  not a re-cut: the gate-1 diagnosis (labeled post-hoc) showed the gate-1 referee was structurally
  unreachable for ANY truth-blind policy at B=1 (one do() partitions a 4-MEC into ≤3 blocks ⇒ blind
  expected-ID ceiling = 3/4; measured exactly 0.750), and B=2 supplies exactly the log₂4 = 2 bits full
  identification needs (RR-0044 ledger, a-priori arithmetic — which also exactly explained the gate-1
  numbers, partial redemption after its capture-prediction MISS).
- **Claim (bounded):** at the information-feasible budget B=2, the deterministic contentless min-max
  chooser **closes the whole gap**: absolute ID ≥ 0.90 and capture ≥ 0.90 of the truth-informed-oracle
  gap, on families/runs never touched by gate 1 or calibration.

## Frozen

- Families: first 30 valid from family-seed **200** (gate-1 used 100–129, calibration 1000+); run seeds
  **{20,21,22}**. tol=0.6, n_int=100, c=2.0 unchanged (digests of all five mechanism/env files unchanged
  from the AGDE-1 freeze — byte-identical mechanisms; only the harness is new).
- `experiments/agde_2.py` = `3412ed217e1ea498`. Mechanism digests as in AGDE-1 prereg (no drift).
- **Decision (mechanical):** MET iff mean ID_A ≥ 0.90 AND capture ≥ 0.90 AND A>R on ≥2/3 decided families
  AND controls pass (byte-determinism, gate-trace audit, E==A / D==R replays, perm collapse ≤ 1/|MEC|).
  NULL otherwise (controls clean). INVALID on any control failure. No rescue, no re-cut.
- **Secondary (report-only):** B=1 active capture vs the **a-priori** blind ceiling 0.75.

## Frozen prediction (RR-0044 ledger, before the run)

Diagnosis preview on gate-1 families gave A=0.967 / O=0.956 at B=2 — but those families are now seen;
fresh-family generalization drop of ~0.03–0.1 is the live risk (it is exactly what NULLed gate 1).
**Prediction: MET ~70%; mean ID_A 0.90–0.97, capture ≥ 0.95.** If NULL again on the sign of a fresh-family
drop, the honest reading is that the chooser's edge is real but family-variance dominates at this scale —
then the next move is MORE families (power), not a lower bar, and the ledger takes its second miss.

## Result

_(appended by the scored run; mechanical verdict; founder may audit/override)_

## Result (scored 2026-07-04, fresh families 200-229 × runs 20-22, digests no-drift): **MET**

| quantity | value | frozen bar |
|---|---|---|
| mean ID: A / R / O | **0.9556** / 0.4009 / 0.9222 | A ≥ 0.90 ✓ |
| capture vs truth-informed oracle | **1.0641** (A exceeds the greedy oracle) | ≥ 0.90 ✓ |
| sign test A>R | **30/30 families** | ≥ 2/3 ✓ |
| controls | ALL PASS (determinism, gate audit, E==A, D==R, perm 0.0) | ✓ |
| secondary B=1: capture vs a-priori blind ceiling 0.75 | **0.9204** | report-only |

Earned bounded sentence (packet vocabulary; no autonomy, no unbounded locus): *at the information-feasible
budget (B = log₂|MEC| bits), the deterministic, contentless, disposer-compatible intervention chooser inside
the governed loop — LLM absent, C7 untouched — fully identifies causal structure on fresh observation-
unidentified families (0.956), matches/exceeds the truth-informed oracle, and beats random choice on 30/30
families at equal total sample budget, attributable to choice of data alone (E==A, D==R replays exact).*
Gate-1's claim AS POSED remains failed; gate-2 is the well-posed referee. RR-0044 ledger: prediction
("MET ~70%; ID 0.90–0.97; capture ≥0.95") = **HIT**. Running tally: AGDE-1 capture MISS / blind-ceiling
exact / 5e HIT / AGDE-2 HIT.
