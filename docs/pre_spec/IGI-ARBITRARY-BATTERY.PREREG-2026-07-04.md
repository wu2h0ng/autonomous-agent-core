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
