# ADR-0049: Sachs real causal task — governed loop on real biology + #1/#2 closed

- Status: **BUILT + RUN (research prototype)**. 2026-07-01. Closes REF-ARCH gaps #1 (hard budget cap + noisy verifier), #2 (memory re-ranking), #3 (real task).
- The toy slice (ADR-0048, governed_loop) was validated on a synthetic env. This wires it to the canonical REAL causal-discovery benchmark and tests the session's core thesis on real data.

## The task
**Sachs et al. 2005** — flow cytometry of 11 signaling proteins in human T cells, OBSERVATIONAL + INTERVENTIONAL (targeted chemical perturbation of 5 nodes: Mek, PIP2, Akt, PKA, PKC) conditions, known consensus causal DAG (17 edges). Data vendored from bnlearn (`experiments/data/sachs_*.txt`), loaded with stdlib only. Passes the fit gate: intervenable + measurable + confounded + ground truth.

Task per target T: a CONFOUNDED correlation proposer ranks candidate causes; the interventional verifier (do(X) vs baseline, standardized mean difference) confirms causal ancestry; the GovernedLoop decides.

## Result (2026-07-01)
**Headline (target Erk):** correlation ranks **Akt at +0.99** (because Erk→Akt — reverse causation), but **do(Akt) is correctly REJECTED** (Akt is a descendant, not a cause). The real-data version of the confound: correlation is fooled, intervention catches it.

**Aggregate over 7 targets (precision/recall vs GT causal ancestry):**
| | precision | recall |
|---|---|---|
| correlation (top-k) | 0.55 | 0.55 |
| **interventional verification** | **0.64** | **0.90** |

Intervention beats correlation on real data — large recall gain, higher precision. **Governed loop** (driven by the confounded proposer that ranks Akt first) **acts on Mek (a true cause), not Akt (the decoy)** — the verifier catches the confound on real biology.

## Honest imperfections (NOT tuned away)
- Intervention is NOT perfect: on Erk it false-positives PIP2 and misses PKA (effect below threshold). The Sachs GT is itself a consensus *proxy*; perturbations have off-target effects.
- The effect threshold (0.30 standardized mean diff) is a hyperparameter; the recall win is robust to it, precision less so.
- Only 5 of 11 nodes are intervenable → candidates restricted to those; a full system escalates the rest.
- Data is discretized {1,2,3} (bnlearn standard).

## #1/#2 also closed (governed_loop.py)
- **#1 hard budget cap + noisy verifier**: `GovernedLoop.max_interventions` escalates instead of blowing the budget; the Sachs verifier is a noise-aware distributional effect test (not a deterministic toggle).
- **#2 memory re-ranking (real belief-update)**: `ActionMemory` + `MemoryReranker` — the loop remembers what verified-effective and tries it first next time; tested to strictly reduce interventions on a repeat task (the outcome changes future behavior, not just a logged record).

518 tests green. Verdict: **the governed causal loop works on real data, and intervention beats correlation there — honestly, imperfectly, reproducibly.**
