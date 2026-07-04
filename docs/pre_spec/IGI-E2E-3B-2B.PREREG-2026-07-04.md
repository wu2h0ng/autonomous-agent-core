# IGI-E2E-3b / 2b preregistration — calibration-aware goal formation; compounding correctly posed

- Date: 2026-07-04. Both are NEW gates with fresh seeds fixing DIAGNOSED protocol/capability failures;
  the parent FAILs stand.
- **3b** (`experiments/igi_e2e_3b.py` = `d1dbeb02b92c9fb2`): cross-fitting (rank on half A, re-estimate
  selected on half B — parameter-free selection-bias removal) + verify-then-commit goal adoption (a
  proposed goal is HYPOTHESIS until its achieving action lands; refuted -> fall back; trial budget 3).
  PASS iff accepted-proposal truth-reachability >= 0.70 (baseline 0.375) AND adoption >= 0.70 AND zero
  unapproved AND halt 100%. Prediction: reachability 0.7-0.9 (cross-fitting removes the argmax bias),
  adoption 0.75-0.95; PASS ~70%.
- **2b** (`experiments/igi_e2e_2b.py` = `36387d6c1d1287f5`): dense n=8 arena (MEC >= 12, budget 6) so
  discovery is genuinely expensive (arena-valid iff task-1 mean >= 3.0 interventions); staleness arm now
  perturbs STRUCTURE (edge reversal -> truth index changes -> cache genuinely wrong). PASS iff saving
  >= 2.0 with achievement drop <= 0.10 AND cache-refuted >= 0.8 AND new-truth id >= 0.7 AND halt 100%.
  Prediction: t1 ~4-5 dos, t2 ~1-2 (confirm+resolve) -> saving 2.5-3.5; refuted ~0.9; PASS ~60%
  (arena-validity is the live risk: the chooser may resolve MEC-12 in fewer than 3 dos again).

> 2b pre-score harness fix (disclosed): the staleness metric referenced a non-existent field
> (`E2EResult.survivors`) and crashed before any 2b scoring; replaced with the equivalent predicate
> (stale-survival = identified WRONG structure immediately after the single confirm-do). Digest re-frozen.

## Results

### E2E-3b (scored 2026-07-04): **FAIL — and the diagnosis DEEPENS**

accepted-proposal truth-reachability **0.4688** (baseline 0.375, bar 0.70); adoption 0.4375; governance
perfect (0 unapproved, halt 100%). Cross-fitting removed the selection bias yet reachability barely moved
-> the winner's curse was NOT primarily selection noise. Residual cause: **band-width mismatch** — the
agent proposes ±0.35 bands around a half-sample estimate whose propagated uncertainty exceeds that width
(deep-chain do-mean estimates at n=150 carry SE > 0.35). Correct next mechanism (E2E-3c, when opened):
ground the committed band in the MEASURED trial outcome (goal = "reproduce what I demonstrated"), or set
band width from the estimate's own propagated SE — goals must inherit the model's uncertainty, not a
fixed tolerance. RR-0044 ledger: MISS (2nd on this axis; the goal-formation axis is now the program's
weakest measured organ — recorded as such).

