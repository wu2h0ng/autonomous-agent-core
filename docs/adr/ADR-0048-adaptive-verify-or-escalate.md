# ADR-0048: Adaptive verify-or-escalate — the corrected architecture (fixes the ADR-0047 hole)

- Status: **BUILT + RUN (research prototype)**. 2026-06-30. Fixes the ADR-0047 frontier hole.
- The fixed-half HYBRID silently TRUSTED the un-verified tail → missed true causes when the LLM was unreliable. This builds the corrected policy — the logical consequence of the founder's own governance principle ("policy acts only on VERIFIED findings; never trust the LLM directly").

## Arms
- **FIXED** (the broken HYBRID): verify the LLM's top half, TRUST the tail as non-causal.
- **ADAPT**: verify in ranked order with a patience-stop; ESCALATE the un-verified tail to a human (never trust it).
- **CALIB**: estimate THIS run's LLM reliability from whether the LLM's MOST-CONFIDENT top picks verify as causal; escalate the tail ONLY when the top is miscalibrated (a decoy ranked above a cause, or the probe finds nothing). Reliable → trust the tail (low interaction).
- **PURE-B** (reference): verify everything (cost ∝ D).

## Result (2026-06-30) — the TRILEMMA made concrete
Simulated LLM reliability p × D (seeds 0..199). causes-found / 2; CALIB escal = human touches/task.

D=24:
| p | FIXED | ADAPT | CALIB | CALIB escal |
|---|---|---|---|---|
| 1.0 | 2.00 | 2.00 | 2.00 | 0.30 |
| 0.9 | 1.88 | 2.00 | 1.86 | 0.39 |
| 0.7 | 1.65 | 2.00 | 1.73 | 0.43 |
| 0.5 | 1.46 | 2.00 | 1.62 | 0.47 |
| 0.3 | 1.25 | 2.00 | 1.67 | 0.58 |

**Findings:**
- **ADAPT restores correctness to 2.00 at ALL p** — it escalates the un-verified tail instead of trusting it. Cost: ~1 human touch every task (low autonomy) + a few verifications. This is the founder's governance principle made operational.
- **CALIB makes escalation ADAPTIVE** (0.30 → 0.58 as the LLM degrades → real autonomy when the LLM earns trust). But it is **NOT a clean 2.00**: it trades interaction for a residual miss, **WORST in the MARGINAL zone** (p≈0.5 dips below p=0.3) — *"looks reliable but isn't"* is the danger band. CALIB beats FIXED everywhere, never reaches ADAPT's guarantee.
- **First CALIB attempt FAILED honestly** (escal=0.00 everywhere): it read "a quick run of decoys" as *reliable*, when at low p that run is precisely the LLM being fooled by the confounds. The corrected signal: trust only when the LLM's TOP picks verify as causal.

## Design guidance (the architecture's policy is stakes-dependent)
The "trust only verified, C7 overrides" principle has a SPECTRUM of implementations:
- **High-stakes (R4/R5-like): ADAPT or PURE-B** — never silently trust the LLM; escalate or verify-all. Correctness guaranteed; pay interaction/verification.
- **Low-stakes: CALIB** — buy autonomy by trusting a calibrated LLM, at a bounded, quantified miss risk (worst in the marginal band).
- **FIXED is never acceptable** — it trusts unverified LLM judgment and silently fails.

## Honesty caps
Simulated LLM reliability (the architectural question is p × D, not one flaky model; the real-kimi run hung — ADR-0047). The trilemma {correctness, autonomy, efficiency} is the real result; CALIB is a useful-but-imperfect navigator, not a free lunch.
