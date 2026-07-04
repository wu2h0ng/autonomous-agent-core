# IGI-E2E-2 preregistration — cross-domain-class generality + corrigible knowledge compounding

- Date: 2026-07-04 · Hook work-order gaps: single-domain-class limitation + no knowledge compounding.
- ONE loop (`aac/e2e_agent.py` = `1769c4dc0edcc76e`, now with CORRIGIBLE reuse: a cached VERIFIED structure is
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

## Result
_(appended by the scored run)_
