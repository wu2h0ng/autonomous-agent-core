# IGI-E2E-3b / 2b preregistration — calibration-aware goal formation; compounding correctly posed

- Date: 2026-07-04. Both are NEW gates with fresh seeds fixing DIAGNOSED protocol/capability failures;
  the parent FAILs stand.
- **3b** (`experiments/igi_e2e_3b.py` = `d1dbeb02b92c9fb2`): cross-fitting (rank on half A, re-estimate
  selected on half B — parameter-free selection-bias removal) + verify-then-commit goal adoption (a
  proposed goal is HYPOTHESIS until its achieving action lands; refuted -> fall back; trial budget 3).
  PASS iff accepted-proposal truth-reachability >= 0.70 (baseline 0.375) AND adoption >= 0.70 AND zero
  unapproved AND halt 100%. Prediction: reachability 0.7-0.9 (cross-fitting removes the argmax bias),
  adoption 0.75-0.95; PASS ~70%.
- **2b** (`experiments/igi_e2e_2b.py` = `2c0cca8050cec1e3`): dense n=8 arena (MEC >= 12, budget 6) so
  discovery is genuinely expensive (arena-valid iff task-1 mean >= 3.0 interventions); staleness arm now
  perturbs STRUCTURE (edge reversal -> truth index changes -> cache genuinely wrong). PASS iff saving
  >= 2.0 with achievement drop <= 0.10 AND cache-refuted >= 0.8 AND new-truth id >= 0.7 AND halt 100%.
  Prediction: t1 ~4-5 dos, t2 ~1-2 (confirm+resolve) -> saving 2.5-3.5; refuted ~0.9; PASS ~60%
  (arena-validity is the live risk: the chooser may resolve MEC-12 in fewer than 3 dos again).

## Results
_(appended)_
