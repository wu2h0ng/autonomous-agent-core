# CWM-LEARN-5a/5b preregistration — enhancement routes (multi-env curriculum; interventional anchors)

- **Date:** 2026-07-04 · **Program:** RR-0041 (LEARN-5 series, founder-opened 2026-07-04 "启动以上研发,
  不要做已被验证失败的重复工作"). · **Author:** Claude; **Adjudicator:** founder.
- **Type:** engineering-iteration experiments (quantitative placement on our stack), NOT novelty gates — the
  qualitative direction of both routes is industry-known; the open question is the quantitative placement on
  OUR stdlib stack relative to the LEARN-4 anchors (chance 0.495 / supplied ceiling 0.894).
- **Verified-failed exclusions honored:** the failed configuration (3 extreme envs, direct full-strength
  V-REx) is CITED from LEARN-4, not re-run; no NOTEARS; no pure end-to-end discovery.
- **Verdict bands are measured-ceiling-relative** (LEARN-2/3 lesson); frozen in the experiment files.

## Frozen digests (rechecked at run; drift ⇒ INVALID)

| artifact | sha256[:16] |
|---|---|
| `experiments/synthetic_scm_transfer_ext.py` | `94ab79a8290dfa89` |
| `experiments/cwm_learn_5a.py` | `5cf651c01ce73f06` |
| `experiments/cwm_learn_5b.py` | `6e1addf384263aff` |
| `EXT_PARAMS` (canonical JSON) | `bf2d61b95e048695` |

Mechanism file `src/aac/transfer_cwm.py` intentionally **unchanged** from its LEARN-4 freeze (`2d6eebd1…`) —
curriculum is orchestrated in the experiment (warm-start via repeated `fit`, tested), so the LEARN-4
comparison is mechanism-identical.

## 5a — multi-env augmentation + curriculum (arms: direct8 / curriculum8 / erm8; NOVEL-A primary, NOVEL-C strict)

Isolation honesty (frozen): training now includes tanh-slot3 envs ⇒ LEARN-4's NOVEL-B is NOT isolated for 5a;
NOVEL-C (linear flipped proxy on slot 4, never nuisanced in training) carries strict isolation. Weak-coupling
envs approach the NOVEL-A limit (coupling→0) — caveat carried into interpretation.

**Frozen prediction:** curriculum8 > direct8 > LEARN-4's 0.495; best arm lands ~0.60–0.75 on NOVEL-A
(明显提升 but below oracle 0.881 — the founder's own calibrated expectation); erm8 improves less or rides
the pooled-majority spurious. Verdict bands: IMPROVED (≥0.65 and ≥ +0.10 over 0.495) / MARGINAL / FLAT /
DEGRADED; curriculum-specific claim only at ≥ +0.05 with ≥8/10 signs vs direct8.

## 5b — few interventional anchors (arms: vrex/erm × N∈{16,64,256}; NOVEL-B primary strict, NOVEL-A secondary)

Anchors = do(slot2) ~ Uniform(−3,3) (A/B analog; marginal ≠ NOVEL-A's N(0,1) ⇒ no test-family leakage),
added as a 4th environment (equal per-env gradient weight — frozen implicit upweighting, symmetric across
arms). N=0 cited from LEARN-4 (vrex 0.473 / erm 0.675 on NOVEL-B).

**Frozen prediction:** steep gains with N (founder: "数量级提升"); by N=256 the best arm reaches ≥0.80 on
NOVEL-B (ANCHORS-WORK); plausibly PENALTY-SUPERFLUOUS (|vrex−erm|<0.03 at best N — anchors replace the
invariance penalty; itself the industry-consistent finding worth recording). Verdict bands: ANCHORS-WORK
(≥0.80) / ANCHORS-PARTIAL (0.60–0.80) / ANCHORS-FLAT (<0.60).

**No-tuning pledge:** couplings, epochs, λ schedule, anchor range/counts, and bands are frozen herein; I will
not adjust them to move a verdict after any scored output. Author ≠ adjudicator; founder casts final.

## Results

_(appended by the scored runs)_
