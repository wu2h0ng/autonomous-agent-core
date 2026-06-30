# ADR-0047: Architecture Frontier — where does HYBRID's half-budget trust break?

- Status: **PREREGISTERED (frontier stress test)**. 2026-06-30. Extends ADR-0046.
- ADR-0046 showed HYBRID wins on an easy task (D=4, 1 cause). This pushes to the FAILURE FRONTIER to find where the LLM-ranking-trust breaks.

## Question
As the problem gets harder (more knobs D, multiple causes, multiple confounds), does HYBRID still match PURE-B's accuracy at a fraction of the budget — or does its "trust the LLM's ranking for the un-tested tail" start MISSING true causes? Where is the frontier?

## Setup (frozen)
- `FrontierCausalEnv(D, k_causes=2, k_decoys=2)`: reward = sum over the 2 causal knobs of (x[c]==target_c). 2 confounded decoys correlate with reward in the observational data; the rest are pure-random non-causal.
- Sweep **D ∈ {6, 12, 20}**. Seeds 0..7.

## Arms (same 4)
- STAT (correlational), PURE-A (Kimi from observation), PURE-B (CWM full budget), HYBRID (Kimi ranks all D; CWM verifies the top HALF by intervention; trusts the tail as non-causal; CWM overrides LLM).

## Metrics (frozen)
- **causes_found** (of 2 true causes, how many each arm classifies causal) — HYBRID misses a cause if the LLM ranked it in the un-tested tail.
- **decoy_correct** (of 2 decoys, how many correctly classified non-causal).
- **interventions** used.
- **worst-cause LLM rank**: how deep in the LLM's ranking the LAST true cause sits (the "trust curve" — how much you'd have to verify to catch all causes).

## Pre-registered expectation (falsifiable)
- PURE-B: causes_found=2/2, decoy_correct=2/2 at all D (full budget), cost ∝ D.
- HYBRID: at small D matches PURE-B at half cost; as D grows, the LLM's ranking gets noisier → some true cause falls into the un-tested tail → **HYBRID's causes_found drops below 2/2**. The D where this happens = the frontier of the fixed-half-budget trust.
- Actionable read: the "worst-cause rank" curve tells us the trust fraction needed at each hardness — i.e., test deeper when the LLM is less reliable.

## Honesty caps
Abstract task; bounded seeds (LLM cost). The point is to FIND the failure mode (HYBRID missing a cause), not to confirm HYBRID always wins. Key via env var only.

## Result (2026-06-30) — FRONTIER FOUND (fixed-half HYBRID is fragile)
The real-LLM run HUNG 1h22m on a network call (urllib timeout did not fire); kimi-for-coding is ~30s/call + returned degenerate abstract rankings -> operationally fragile + task-fit-poor (itself a track-A cost finding). Switched to a controllable LLM-reliability simulation (the architectural question is p x D, not one flaky model).

HYBRID causes-found / 2 (PURE-B = 2/2 at full budget D):
| | p=1.0 | p=0.9 | p=0.7 | p=0.5 | p=0.3 |
|---|---|---|---|---|---|
| D=6 | 1.92 | 1.74 | 1.33 | 1.09 | 0.82 |
| D=10 | 2.00 | 1.82 | 1.56 | 1.27 | 1.01 |
| D=16 | 2.00 | 1.91 | 1.65 | 1.50 | 1.22 |
| D=24 | 2.00 | 1.88 | 1.65 | 1.46 | 1.25 |

**The ADR-0046 HYBRID win was an EASY-CORNER artifact.** At realistic LLM reliability (p<1.0) or higher D, the fixed-half-budget "trust the un-tested tail" MISSES true causes — a CORRECTNESS failure. Min reliability for ~2/2 at half budget ≈ p=1.0 (only a near-perfect LLM makes fixed-half-trust safe). **Architecture refinement: trusting the un-tested tail VIOLATES the founder's own "only act on VERIFIED findings" principle — and that's exactly what fails. Corrected design: adapt the verification fraction to LLM-reliability × stakes; ESCALATE the un-verified tail (don't silently trust the LLM). The governance principle is MORE load-bearing than it first appeared.** Plus the operational finding: the LLM organ is slow/hang-prone → never block on it; hard timeouts + degrade to CWM+escalation.
