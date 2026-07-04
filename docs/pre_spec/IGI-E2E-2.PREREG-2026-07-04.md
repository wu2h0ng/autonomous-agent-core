# IGI-E2E-2 preregistration — cross-domain-class generality + corrigible knowledge compounding

- Date: 2026-07-04 · Hook work-order gaps: single-domain-class limitation + no knowledge compounding.
- ONE loop (`aac/e2e_agent.py` = `b6e3ae3582f74f3b`, now with CORRIGIBLE reuse: a cached VERIFIED structure is
  re-confirmed with ONE do() before trust; refuted caches fall back to full discovery — stale knowledge
  cannot survive). Harness `experiments/igi_e2e_2.py` = `64dced70f3393c4e`. Zero per-class code.
- Four structurally different classes: tree6 / chain8 / dense7 / star7 (8 envs × 2 runs each, seeds
  500+, runs {50,51} — all fresh). Compounding: task-2 = new preference in the same env with cache;
  robustness: perturbed-world arm (edge weight sign-flipped) must REFUTE the cache and re-identify.
- Decision (mechanical): PASS iff all four classes id>=0.70 & ach|id>=0.70 AND compounding saving
  >=1.0 intervention with achievement drop <=0.10 AND perturbed cache-refuted >=0.8 with post-refute
  id >=0.7 AND halt probes 100%. FAIL else. No rescue.
- Frozen prediction (ledger): per-class id 0.85-1.0 (chooser validated; MECs 6-12 vs budget 3 — dense7
  is the risk class, MEC 12 may exceed 3-do resolution on some envs); compounding saving ~2.0 (3->1);
  refuted rate high (sign-flip moves do-means far beyond tol). PASS ~65% (dense7 is the live risk).

> Pre-score crash fix (disclosed): the perturbed-arm confirmation could refute the ENTIRE pool
> (Exhausted) and the empty survivor set crashed the discovery loop; fixed FAIL-CLOSED (returns honest
> UNIDENTIFIED). No scored result existed before the fix; digest re-frozen.

## Result
_(appended by the scored run)_

## Result (scored 2026-07-04 after disclosed crash-fix; digests no-drift): **FAIL — frozen rule stands**

- **Cross-class generality LANDED (measured fact):** identification **1.000 on all four classes**
  (tree6/chain8/dense7/star7), achievement 0.938/0.938/0.938/1.000, halt probes 100%, zero per-class code.
- **Compounding criterion failed by mis-pose:** task-1 discovery floor is already **1.5 interventions**
  (the chooser resolves MECs 6-12 in 1-2 do()s) — the >=1.0-saving bar assumed ~3-do discovery; there was
  no room to save (0.062). Protocol error, not a loop failure.
- **Staleness arm tested the wrong object:** the perturbation flipped an edge WEIGHT, leaving STRUCTURE
  unchanged — so the structure-cache was legitimately still true (refuted-rate 0.516 vs bar 0.8 reflects a
  wrong expectation; post-refute identification 0.906 shows recovery works when it does refute).
- Disposition: FAIL recorded, no rescue. **E2E-2b** (next, fresh seeds) fixes the protocol: compounding
  measured on expensive-discovery envs (task-1 cost >= 3), staleness arm perturbs STRUCTURE (edge reversal
  within skeleton -> truth index changes -> the cache is genuinely wrong and MUST be refuted).
- RR-0044 ledger: bet ("PASS ~65%, per-class id 0.85-1.0") = verdict-MISS (FAIL), id-band edge (1.0).
