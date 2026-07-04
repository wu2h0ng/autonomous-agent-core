# IGI-ARBITRARY-BATTERY preregistration — 'arbitrary domain' as a DISTRIBUTION (zero-code)

- Date: 2026-07-04. Directly answers the standing critique 'only 6 hand-picked classes, not arbitrary
  domains'. The EXISTING e2e loop (zero code changes) on 60 RANDOMLY-DRAWN DAG structures (random n 5-9,
  random density, random weights) the code has never seen — each a fresh novel domain sampled from a
  distribution, not curated. `experiments/igi_arbitrary_battery.py` = `114471b5849040cd`.
- PASS iff mean identification >= 0.70 AND achievement|id >= 0.70 AND halt 100% AND no size bucket
  collapses < 0.5. Frozen prediction: id 0.80-0.95, ach ~0.9, halt 100%; MET ~70% (larger random MECs at
  n=9 with fixed budget are the tail). 'Generality at toy scale' becomes a measured DISTRIBUTION result.

## Result
_(appended)_

## Result (scored 2026-07-04): **MET — generality is now a DISTRIBUTION result**

60 random domains, ALL 60 distinct skeletons, MEC range 3-48 (16x span). identification **0.858** /
achievement|id **0.981** / halt **100%** / every size bucket >= 0.727 (n5 1.0, n6 0.90, n7 0.808,
n8 0.882, n9 0.727). Verdict MET.

'通用 on arbitrary novel domains' at toy scale is no longer a curated list of 4-6 shapes — it is a
measured result over a random draw of never-seen causal structures, zero code changes. The n=9 dip
(0.727, fixed budget vs larger random MECs) is the honest scaling tail = the next budget-scaling datum.
Governance held on all 60 (every do gate-approved; paused-C7 halted every probe). RR-0044 ledger: HIT
(id in band, achievement above). Standing honest gaps unchanged: real-world ACTUATION (seam item,
founder-keyed) and cross-domain knowledge compounding (scale work). But the loudest critique — 'only 6
hand-picked classes' — is now answered with a distribution.

## BIG-N DIAGNOSIS (2026-07-04): dip is NOT budget — it is prediction-equivalence (RR-0044 bet MISS,
correctly localized)

+2 vs +3 budget slack on 30 fresh big-n domains (n 8-10, MEC 4-56): BYTE-IDENTICAL results (id 0.633,
id_by_n 8:0.786 / 9:0.60 / 10:0.562, halt 100%). Identical => the loop reaches a fixed point before
using extra budget => the failures are NOT budget-limited. Root cause: at larger n, random MECs contain
structures the e2e loop's clamp-prune leaves prediction-EQUIVALENT (survivors > 1 that no do() splits) —
the SAME nesting/equivalence issue AGDE-T3 diagnosed, which T3 closed with CAUSAL-MINIMALITY COLLAPSE.
The static e2e discovery loop lacks that collapse. NEXT-SESSION MECHANISM (design, not knob): port the
minimality/equivalence collapse from AGDE-T3 into e2e_agent discovery; re-run big-n battery. RR-0044
ledger: budget bet MISS, but the miss localized the true cause (equivalence, not bits) — the ledger
earning its keep as a diagnostic even when the point prediction fails. The n<=8 battery MET stands
(0.858); the >=9 tail now has a named mechanism fix, not a mystery.

## BIG-N ROOT CAUSE — CORRECTED (2026-07-04): fit-bias FALSE-REJECTION of truth (NOT equivalence)

Retraction of the prior 'prediction-equivalence / minimality' label (it was asserted, not verified — the
e2e pool has no lag-nesting, so T3's minimality does not apply here). Two measurements settle it:
- truth-unresolvable-competitors = **0/N for ALL 11 failing domains** — truth IS uniquely separable in
  principle (so NOT equivalence, NOT non-identifiability, NOT budget).
- truth SELF-rejects on 1-5 do-nodes in **11/11** failing domains — truth's own predicted clamp mean
  deviates from its own MEASURED clamp mean beyond tol. **The truth is being FALSELY PRUNED by fit bias:**
  per-node OLS on fixed 400 obs samples over MORE parents at larger n is biased; predict_do_means
  propagates and compounds that bias; the loop prunes the truth against real measured data.
NEXT-SESSION MECHANISM (design): scale n_obs with n (more samples for more parents) OR fit-uncertainty-
aware prune tolerance (tol grows with fitted-coef SE). NOT minimality, NOT budget. This is the SAME
FAMILY as T3's K2 predictor-soundness catch (fit/measurement quality), not T3's nesting catch.
DISCIPLINE NOTE: the day's law applied to my OWN diagnosis — a structure-type claim ('cause = X') asserted
without measurement was wrong; measuring truth-self-survival corrected it. Verify against the world,
including one's own conclusions.
