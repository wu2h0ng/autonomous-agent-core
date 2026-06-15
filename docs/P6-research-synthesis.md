# P6 Research Synthesis And Publication Package

> Date: 2026-06-15  
> Status: founder-approved P6 synthesis package, docs-only  
> Scope: autonomous-agent-core research results through ADR-0033  
> Authority: this document summarizes accepted ADR/RR results; it does not move gates, add mechanisms, or reopen parked routes.

## 1. Executive Thesis

The program has one robust positive mechanism result at this prototype scale:

**Subject-side belief-to-action coupling, implemented as the frozen P0 confidence-gated policy, decisively beats cheap reset baselines while preserving C6/C7.**

The result is narrow but real. It is not a claim that autonomy is solved, and it is not a claim that richer world models, LLM organs, decentralized coordination, endogenous drives, survival pressure, or stationary risk calibration have been established as independent autonomy axes. Most of those lines were tested and returned negative or partial results.

The main scientific contribution is therefore two-sided:

- A positive localization result: in this prototype family, the first decisive win lives in the subject-side commitment channel, not in belief-only organs.
- A falsification record: repeated "clever" belief-side or coordination mechanisms failed against cheap or strong fixed baselines, with staleness and slow recoupling as the recurring failure mode.

This is a good stopping point for P6: consolidate, publish/review, and only open new mechanism work under a fresh founder-level ADR with a genuinely new axis or structured-environment gate.

## 2. Claim Ledger

| Claim or route | Current judgment | Evidence | Publication posture |
|---|---|---|---|
| Claim 1: stake / viability matters | Supported by mechanism and ablation evidence | ADR-0012/P2: interoception ablation repeatedly reduced survival; value-supply removal killed the agent by resource dynamics | State as supported in this prototype, not as a universal theory of agency |
| Claim 2: relevance / correlation realization | Partially supported, not established in its original organ form | G1/G1'/G2 and related routes did not clear preregistered gates; G10 later found a different subject-side route | Do not claim the original relevance organ was validated |
| Claim 3: corrigibility | Strong architectural result | Shell separation, audit chain, ISO-1 default view, ISO-2 cross-process reference, C7 tests through later gates | State as a maintained invariant and engineering contribution |
| Claim 4: organs are not subjects | Strong structural result | Belief-only organ boundary, no organ action/policy/shell control, G10 win is subject-side without organ authority | State as a core safety invariant |
| G10/P0 subject-side gate | Confirmed positive result | ADR-0024: P0 759.8 vs A1 1268.6 on seeds 800..829, 30/30, 40.1% reduction; ADR-0030 completeness traps passed | Make this the central empirical result |
| RR-0019 channel decomposition | Strengthened but not proven as theorem | ADR-0031: residual calibrator failed to beat P0; PRED1-HOLDS | Present as active theory supported by local evidence |
| C5/RAP decentralized coordination | Not established | ADR-0014/G4 NOT MET; routing/staleness failure | Historical negative result; do not revive as core axis without reset ADR |
| P4 learned prior / O2 | Not established | ADR-0016/G5 NOT MET; deterministic reset O1 was enough | Negative result; useful as boundary for future organs |
| Structured reusable regimes | Supported in limited scope | ADR-0017/G6a MET; richer prior helped where reusable structure exists | Use as motivation for future structured-environment work, not as general LLM-organ proof |
| LLM / semantic organ | Offline de-risk only | ADR-0019/G6b semantic oracle positive; live LLM spend/key not approved | Keep as P4.x, never runtime subject |
| G11 system-level multi-axis signature | Parked/closed for current route | ADR-0027, ADR-0028, ADR-0029: no second independent winning axis after endogeny/survival/risk | Do not claim G11 is ready |

## 3. Gate And Negative-Result Map

| Phase/gate | Verdict | What survived | What failed |
|---|---|---|---|
| P0/G0 | NOT MET for relevance v0 | Viability core, shell, audit, first loop | RelevanceField v0 |
| P1/G1 family | NOT MET | Some partial metabolic/survival effects | Attention/relevance did not clear recovery gates |
| P1.5/G1'/G2 | NOT MET | ISO hardening, contextual/causal instrumentation | Contextual/causal relevance did not become decisive |
| P2/G3 | Mixed | Stake/interoception ablation support | IdleDrives did not reliably beat cheap alternatives |
| P3/G4 | NOT MET | Auditability of RAP settlement | RAP routing did not beat strong fixed/central baselines |
| P4/G5 | NOT MET | O1 deterministic reset scaffold | O2 learning prior did not beat O1 |
| P4.x/G6a | MET | Structured reusable regimes make richer prior useful | Scope is structured environments only |
| P4.x/G6b | de-risk only | Semantic oracle shows exploitable structure | Live LLM organ not run/approved |
| P4.x/G7 | NOT MET | O4 beats O1 significantly | O4 did not beat O2 at required 90% dominance |
| P4.x/G8 | NOT MET | O4 ceiling clarified | O5 ensemble did not improve over O4 |
| P4.x/G9 | Formal NOT MET; positive discovery | P0 gate-alone decisive signal | Preregistered P4 = gate + organ was the wrong candidate |
| P6/G10 | MET | P0 fresh-seed confirmation | None for P0 under G10 |
| ADR-0030 | COMPLETENESS PASS | P0 survives flip-the-conclusion traps | Trap explanations rejected |
| ADR-0031 | PRED1-HOLDS | Channel-decomposition prediction survived powered attack | Residual belief calibration is not a second axis |
| ADR-0026/C3 | RED | Endogeny is not a G11 axis | Directed idle productivity signal |
| ADR-0028 | RED | Survival is useful as observation | Survival is not an independent performance axis |
| ADR-0029 | RED | Cheap broad exploration is strong in stationary risk | Gated policy has no independent stationary risk advantage |

The negative results are not cleanup material. They are part of the contribution: they explain why the positive G10 result is interesting and why "add a smarter organ" is not the next default move.

## 4. Mechanism Lineage

1. **Safety substrate first.** The earliest durable artifacts are viability, operator shell sovereignty, forbidden-action dominance, and hash-chained audit.
2. **Belief-side cleverness repeatedly hit a ceiling.** Attention fields, contextual action models, causal relevance, adaptive priors, latent-regime organs, and ensembles produced partial signals or local wins but did not reliably beat cheap baselines at preregistered strength.
3. **Coordination inherited the same staleness problem.** RAP did not fail because audit was absent; it failed because reputation/confidence routing was stale after drift and sometimes routed to the wrong or dropped node.
4. **Structured environments matter.** G6a showed richer priors can beat cheap reset when transferable structure really exists. That does not license arbitrary world models; it points to structured-environment gates.
5. **The decisive result moved from belief to coupling.** G10 did not improve the organ. It changed how the subject uses its own confidence to set commitment/exploration temperature.
6. **Frontier systems are now bounded imports.** ADR-0032 and ADR-0033 allow external candidate generation, bounded belief organs, and product/deployment projection; they forbid runtime self-modification and organ control of policy/shell.

## 5. Reproducibility Appendix

Current full-suite truth:

```text
PYTHONPATH=src python -m unittest discover -s tests -v
388 tests OK
```

Key scripts and guards:

| File | Purpose |
|---|---|
| `experiments/confidence_gated_g10.py` | G10 fresh-seed confirmation of P0 |
| `tests/test_confidence_gated_g10.py` | G10 determinism and C6/C7 guards |
| `experiments/completeness_g10.py` | ADR-0030 trap/completeness checks |
| `tests/test_completeness_g10.py` | Temperature/baseline wiring guards |
| `experiments/prediction1_residual_calibrator.py` | ADR-0031 powered attack on RR-0019 Prediction 1 |
| `tests/test_residual_calibrator.py` | Residual calibrator math and default-off C6/C7 guards |
| `experiments/idle_productivity_c3.py` | C3 endogeny de-risk |
| `experiments/survival_axis_c1.py` | Survival-axis de-risk |
| `experiments/risk_calibration_c1.py` | Stationary risk-axis de-risk |
| `experiments/structured_g6a.py` | Structured reusable-regime positive scope |
| `experiments/rap_g4.py` | RAP negative result |

Known seed sets:

| Result | Seeds |
|---|---|
| G10 | 800..829 |
| C3 | 900..929 |
| ADR-0028 survival de-risk | 1010..1039 |
| ADR-0029 risk de-risk | 1100..1129 |
| ADR-0031 calibration | 1200..1219 |
| ADR-0031 r-final | 1300..1329 |

Method discipline to preserve:

- Preregister gates before r-final.
- Use fresh seeds for post-hoc winner confirmation.
- Record negative results as first-class outputs.
- Do not retune failed mechanisms to rescue a gate.
- Keep C6/C7 guards in every mechanism path.
- Keep frontier or self-recursive systems outside runtime control unless a future ADR explicitly proves a safe bounded lane.

## 6. Publication Package

### Working Titles

1. **Where Autonomy Emerged: Subject-Side Coupling Beats Directed Organs in a Falsification-First Agent Prototype**
2. **When Cheap Baselines Win, and When They Stop**
3. **Belief Quality Was Not Enough: A Channel-Decomposition Result From a Corrigible Agent Prototype**

### Recommended Paper Thesis

In a falsification-first autonomous-agent prototype, richer belief organs and decentralized coordination repeatedly failed to beat cheap baselines under preregistered gates. The first decisive positive result emerged only when the subject changed how confidence controlled action commitment, suggesting that the relevant local lever was the belief-to-action coupling channel rather than belief quality alone.

### Contributions To Claim

- A reproducible gate ledger of positive, partial, and negative autonomy-mechanism results.
- A C6/C7-preserving architecture that separates subject policy from bounded organs and operator shell authority.
- A decisive fresh-seed confirmation of the P0 confidence-gated policy.
- A channel-decomposition interpretation separating belief estimates `B = (mu, u)` from subject commitment `K = (tau, w_e)`.
- A negative-result taxonomy: belief-only organs, endogenous drives, RAP routing, survival, and stationary risk did not provide independent axes at this scale.
- A safe frontier-intake boundary for LLM/world-model/self-recursive systems.

### Figures And Tables

- Gate timeline from G0 through ADR-0033.
- Claim ledger: established, partial, rejected, parked.
- Channel diagram: belief `B` vs subject commitment `K`.
- G10 result table and trap-completeness table.
- Negative-result map grouped by failure mode: staleness, cheap reset dominance, weak axis validity, and organ/subject boundary.
- C6/C7 architecture boundary diagram.

### Must Not Claim

- General autonomy has been solved.
- G11/C1 is ready.
- LLM organs should enter runtime action selection.
- RAP/IdleDrives/survival/risk are independent winning axes.
- Better belief calibration alone explains G10.
- Product deployment guarantees inherit core autonomy results without downgrade and separate enterprise governance.

### External-Readiness Checklist

- Revise `../docs/research/paper-cheap-baselines-win-safety-substrate-holds.md` with G9/G10/ADR-0030/ADR-0031.
- Convert the gate ledger into a compact table suitable for a paper appendix.
- Export or snapshot r-final outputs for G10, ADR-0030, ADR-0031, C3, survival, and risk.
- Add citations and related-work positioning from `../docs/research/RR-0020-frontier-agent-architectures-radar.md`.
- Decide target venue/audience before changing tone: academic workshop, arXiv technical report, or founder-facing whitepaper.
- Keep limitations prominent: toy environments, deterministic prototype, no live LLM runtime, single decisive lever, scoped generality.

## 7. Next Decisions

P6 synthesis is now the current core state. The next actions are documentation and publication work unless the founder opens a new ADR.

Allowed next work:

- Paper/whitepaper revision around this synthesis.
- Reproducibility artifact packaging.
- P5 enterprise deployment projection under the enterprise repo's own ADR/AR.
- ADR-0034/T-P6.5 relevance-aware G10 theory test, now frozen as a theory-attribution experiment. It tests whether P0's margin remains after a strong `RelevanceField`-aware non-gated control, not whether G11/C1 should be reopened.
- ADR-0035/P7 ecological environment axis, now accepted as a blocked next axis after ADR-0034. It freezes the G12 2x2 environment gate and the internal-reset vs external-rollback distinction.
- Other structured-environment experiment design only after a fresh gate is written and frozen.

Not allowed without a new founder-level ADR:

- Reopening G11/C1.
- Retuning failed belief organs, RAP, IdleDrives, survival, or risk axes.
- Importing HyperAgents/DGM-style self-recursion into runtime.
- Letting LLM/world-model organs select actions or mutate policy/shell.
