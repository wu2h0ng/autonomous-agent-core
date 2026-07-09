# IGI-REAL-SACHS preregistration — governed discovery on REAL biology (真实域 first attempt)

- Date: 2026-07-04 (founder cast: scale arena / real domain). Directly attacks 'NOT on real domains'.
- Data: Sachs 2005 protein-signalling (855 obs + 5401 interventional rows; consensus DAG; 5 intervenable
  nodes) — vendored, real. `experiments/igi_real_sachs.py` = `9936cdb7ecbc8ede`.
- The SAME governed active-intervention machinery (gate + budget + halt) chooses which of 5 REAL
  interventions to consult (budget 3) to recover causal ancestry of 6 observable targets. Arms: ACTIVE
  (max real-effect selection) / RANDOM (equal budget) / CORREL (confounded prior, the decoy).
- Decision (mechanical): PASS iff ACTIVE ancestry-F1 >= CORREL + 0.15 (interventions beat confounded
  correlation on real data — the ADR-0049 thesis, now inside the governed budgeted loop) AND ACTIVE >=
  RANDOM AND governance (gate/halt/determinism) all pass. NULL else; INVALID on control failure.
- Frozen prediction: ACTIVE F1 ~0.6-0.8, CORREL ~0.3-0.5 (reverse-causation confounds it), gap >= 0.15;
  MET ~70% (ADR-0049 already showed interventional recall 0.90 vs corr 0.55 on this data — the budgeted
  governed form should preserve the ordering). Honest scope: real DATA, still a benchmark not a live
  deployment; actuation (acting in the world) remains the seam-lane item.

## Result
_(appended by the run)_

## Result (scored 2026-07-04): **NULL — honest first real-domain result, mechanism works where well-posed**

ancestry-F1: active **0.511** / random 0.417 / correl 0.400 (gap to correl 0.111 < 0.15) · governance
ALL PASS (halt 100%, determinism, gate-approved). Frozen NULL; NO rescue.

Diagnosis (labeled post-hoc; verdict untouched):
- On the 4 targets WITH intervenable true ancestors (Raf/Erk/P38/Jnk): active F1 = 0.80/0.67/0.80/0.80
  (mean ~0.77) — the governed intervention selection RECOVERS true causal ancestry on REAL biology.
- On 2 targets with EMPTY consensus-ancestor sets (Plcg/PIP3): F1 = 0.00 because REAL interventions
  have large effects that CONTRADICT the consensus DAG (do(PKC) shifts Plcg 6.74σ; PKC is not a
  consensus ancestor of Plcg). The Sachs consensus is a known-imperfect reference; interventions
  legitimately reveal edges it lacks. The aggregate NULL is dominated by this ground-truth contest,
  not a mechanism failure.
- Full-budget (5) F1 0.467 < budgeted 0.511: budget HELPED (fewer false positives on empty-truth targets).

Honest lesson (the real-domain gap, sharpened): the toy-scale interventional advantage transfers to real
biology ON WELL-POSED TARGETS, but a naive aggregate gate against a CONTESTED ground truth NULLs. Real
domains demand (a) handling ground-truth imperfection and (b) a proper effect-threshold/precision model —
both are real-scale work, exactly the difficulty '任意领域' names. This is the first honest measurement
of that gap on real data — recorded, not rescued. (ADR-0049's 0.90 was full-read ancestry RECALL on a
subset; this budgeted F1 over all 6 targets is a harsher, more honest aggregate.)
