# ADR-0046: Architecture Comparison — pure-B vs pure-A vs hybrid, on confounded causal discovery

- Status: **PREREGISTERED (research prototype; frozen before running)**. 2026-06-30.
- Founder: "do all approaches together, then compare." This empirically tests the layered architecture (CWM core + LLM interface + governance) against the pure variants.

## Question
On a causal-discovery task with a CONFOUND (a decoy that correlates with reward but does not cause it), which architecture predicts interventions correctly AND with the fewest interventions?

## Arms (frozen)
- **STAT** (correlational floor): predict a knob is causal iff its observational reward-correlation is high. (No interventions.)
- **PURE-B (CWM)**: spend the FULL intervention budget; predict causal iff do(knob) changed reward.
- **PURE-A (LLM)**: give Kimi the OBSERVATIONAL statistics in language; it cannot intervene; ask which knobs are causal. (Tests whether the LLM reasons causally from observational data, is fooled by the confound, or hedges.)
- **HYBRID (LLM + CWM, the founder's layered architecture)**: the LLM RANKS which knobs to test first (hypothesis generation, the interface organ); the CWM verifies in that order with a HALF budget, trusting the LLM only for the un-tested tail (governable: the CWM's interventional finding overrides the LLM; the LLM never directly decides). Predict from the CWM's verified findings + the trusted tail.

## Metric (frozen)
- **decoy-prediction accuracy** (the tell: does do(decoy) change reward? truth = NO): per arm, mean over seeds 0..9.
- **interventions used** (sample efficiency): PURE-B vs HYBRID.
- overall causal-mask accuracy.

## Pre-registered expectation (frozen, falsifiable — may come out otherwise)
- STAT: fooled on the decoy (low decoy accuracy).
- PURE-B: correct, but full intervention budget.
- PURE-A: empirical — may be fooled (relies on the confounded observation) or may hedge.
- **HYBRID: matches PURE-B's correctness (the CWM verifies → catches the confound the LLM/observation misses) at FEWER interventions IF the LLM's ranking is useful.** If the LLM's ranking is itself fooled (ranks the decoy first / the cause last), HYBRID's half-budget trust could MISS the cause — that failure mode is the honest risk and will be reported.

## Honesty caps
Abstract symbolic task so the LLM has no domain prior (must reason from the given data) — fair to the causal question, but not a real-domain benchmark. Key via env var, never persisted. The point is to MEASURE the architecture trade-off the founder proposed, not to assume it.

## Result (2026-06-30) — HYBRID WINS
| arm | decoy-correct (knows do(decoy) doesn't matter) | mask-acc | interventions |
|---|---|---|---|
| STAT (correlational) | 0.00 | 0.75 | 0 |
| PURE-A LLM | 0.90 | 0.75 | 0 |
| PURE-B CWM | 1.00 | 1.00 | 200 |
| **HYBRID** | **1.00** | **1.00** | **100** (true cause found 100% of seeds) |

**The founder's layered architecture is empirically best**: HYBRID matches PURE-B's perfect accuracy at HALF the interventions — the LLM's hypothesis-ranking guides the CWM (true cause always in the tested half), the CWM verifies/overrides to reach certainty. Value decomposition: LLM = good-but-noisy PRIORS (decoy 0.90 ≫ STAT 0.00 — it reasons about confounds, NOT a dumb correlation machine — but caps at 0.75 mask-acc because it can't verify); CWM = VERIFICATION/certainty (1.00); governance = CWM overrides LLM (trust). **Sharpens the rationale: the LLM isn't mainly "fooled by correlation" — its limit is it can't reach CERTAINTY without intervention, exactly what the CWM provides.** Honest caveats: abstract toy task; the half-budget win + LLM ranking quality may degrade on harder/real domains (HYBRID could miss the cause if the LLM ranks it in the untested tail — didn't happen here). Next: harder/real domains.
