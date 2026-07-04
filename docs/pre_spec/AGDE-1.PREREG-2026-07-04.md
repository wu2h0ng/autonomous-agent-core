# AGDE-1 preregistration — Choice-vs-Random under budget scarcity (Active Governed Discovery Engine, gate 1)

- **Date:** 2026-07-04 · **Design:** `AGDE-1.DESIGN-PACKET-2026-07-04.md` (paradigm-loop output) ·
  **Theory frame:** RR-0044 (typed routing: do() enters as discrete prune; min-max chooser = max
  worst-case bits). **Builder:** Claude (CTO-cast GO under founder delegation 2026-07-04). **Adjudication:**
  frozen mechanical rule; raw preserved; founder audit/override standing.
- **Bounded claim** (vocabulary bans per packet: no "autonomy", no "extracts more", no unbounded locus):
  under budget scarcity, the deterministic contentless min-max chooser captures **≥50% of the measured
  oracle−random identification gap** on observation-unidentified families, attributable to choice of data
  alone. Nulls live: H0-CHOOSER (active ≤ random), H0-SCHEDULE (round-robin ties), H0-PASSIVE-TIE
  (integrity-armed: replays MUST tie their donors).

## Calibration chain (all pre-freeze, disjoint seeds; kills protocol honored)

1. **K3 FIRED on the packet's implicit arena** (n=5 random skeletons): 0/400 families satisfy MEC≥4 ∧
   informative-fraction≤1/3 — measured impossible, not assumed. **Redesign (disclosed):** explicit scarcity
   construction — pinned block (3 colliders, 9 nodes, all edges v-structure-pinned → do()s uninformative)
   + free 4-node path (MEC exactly 4), n=13, labels permuted per family. Favourable-to-active BY DESIGN
   and disclosed: if active loses here it loses everywhere.
2. **Rerun: all kills clear** (`agde_1_calibration.result.json`): 25 valid families; tol=0.6/n_int=100 →
   truth-survival 1.000, wrong-kill 0.308; gaps oracle−random = 0.68/0.60/0.50 at B=1/2/3.
3. **Frozen:** tol=0.6, n_int=100, c=2.0, **B_primary=1** (max gap), B_secondary=2 (report-only), scored
   families = first 30 valid from family-seed 100 (recorded in result), run seeds {10,11,12} (calibration
   used families 1000+, runs 0–2 — disjoint).

## Frozen digests (drift ⇒ INVALID)

| artifact | sha256[:16] |
|---|---|
| `experiments/intervention_scm.py` | `a4ede530fa69c0e2` |
| `src/aac/hypothesis_pool.py` | `46f66a71562d34cf` |
| `src/aac/structure_consistency.py` | `ad7aefdc6b2a91be` |
| `src/aac/intervention_chooser.py` | `1dfc434cb15aced9` |
| `src/aac/discovery_loop.py` | `c8e5c112119948c9` |
| `experiments/agde_1.py` | `cd01f477b039f669` |
| `tests/test_agde_1.py` (11 green) | `4e1ee8b4e64b989e` |

## Decision rule (frozen, mechanical)

`capture = (mean ID_A − mean ID_R)/(mean ID_O − mean ID_R)` at B=1 over 30 families × 3 runs;
ID = 1/|survivors| if truth survives else 0. **MET** iff capture ≥ 0.5 AND A>R on ≥2/3 of decided
families AND controls pass: byte-determinism of A; gate-trace approvals == interventions ≤ B; **E==A and
D==R exactly** (one-shot replays of collected datasets through the identical verifier — the loop must add
nothing beyond data choice); C-PERM null-intervention collapse (correct-unique-ID rate ≤ 1/|MEC|); OBS/OBS+
floor structural (verifier consumes only do-regime data — disclosed as by-construction, not re-derived).
**NULL** iff controls pass but capture < 0.5 or sign fails. **INVALID** iff any control fails.

## Frozen prediction (RR-0044 ledger applied, before scored run)

Calibration preview (calib families only): capture ≈ 0.59. Bit account: B=1 buys ≤2 bits (best split of a
4-member MEC into ≥2 blocks); random spends it on an informative node w.p. ≈0.31 → expected capture well
above 0.5 if the chooser reliably finds the split node. **Prediction: MET ~70%; capture 0.5–0.7.** NULL
tail: fresh-family tie structure / per-family variance pushing the sign test under 2/3. If NULL: H0-CHOOSER
stands, the locus claim dies at gate 1, recorded as boundary — no rescue, no re-cut of B or tol.

## Result

_(appended by the scored run; mechanical verdict; founder may audit/override)_
