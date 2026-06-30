# REF-ARCH-02: Model Organ Contract

> Every model (LLM, CWM, forecaster, reranker, classifier, SQL drafter…) plugs in as an **advisory organ**, never as the subject. Status: the contract **already exists** in `prior_organ.py` (`PriorOrgan`, `OrganAdvice`, `merge_organ_advice`, `snapshot_belief`, `_validated_delta`) and `prior_organ_llm.py` (`LLMPriorOrgan`, `LLMBackend`, `DeterministicStubBackend`). This document formalizes it and the discipline this session validated.

## 1. The interface (grounded in real types)
```
Organ.advise(context: BeliefSnapshot, task) -> OrganAdvice
  OrganAdvice = bounded belief delta            (validated by _validated_delta)
              + uncertainty                       (required)
              + evidence_refs                     (or a refusal_reason)
              + confidence
```
- **Input**: a *bounded* context (a `BeliefSnapshot`, not raw global state) + a typed task. An organ never sees more than its task needs.
- **Output**: a *typed candidate* — a **bounded** belief delta (`_validated_delta` clamps it so no single organ can dominate), with **uncertainty**, **evidence refs**, and a **refusal_reason** when it can't answer. Multiple organs are combined by `merge_organ_advice` — advice is *merged under validation*, not executed.

## 2. The organ catalogue (status)
| Organ | Job (candidate generation only) | Module | Status |
|---|---|---|---|
| **LLM** | propose/explain/translate; draft hypotheses, summaries, SQL drafts, action-proposal drafts | `prior_organ_llm.py:LLMPriorOrgan` (+ `LLMBackend`, `DeterministicStubBackend`) | ✅ exists |
| **Causal World Model** | predict do(·) effects; flag confounds the LLM/correlation miss | ADR-0045 core + `causal_relevance.py` | ✅ hallmark / 🟡 to be promoted into `src/aac/` as a `PriorOrgan` |
| **Consequence prior** | bounded prior over action outcomes | `consequence_prior.py:BoundedConsequencePriorOrgan` | ✅ exists |
| **Ensemble / latent / library** | regime-aware priors | `prior_organ_ensemble/latent/library.py` | ✅ exists |
| forecaster / reranker / classifier / embedding | predict / rank / classify | — | ❌ future organs, same contract |

## 3. What an organ MAY do
Generate candidate explanations, semantic parses, SQL drafts, anomaly flags, forecasts, evidence summaries, action-proposal **drafts**, ranked hypotheses.

## 4. What an organ may NEVER do (C6 + constitution)
- ❌ Execute an action / call a tool that mutates state directly.
- ❌ Bypass SQL Safety, EvidenceChain, or any safety boundary.
- ❌ Write policy, modify the Corrigibility Shell, or set its own risk ceiling.
- ❌ Decide approval, or self-authorize an R4/R5 action.
- ❌ Modify the safety substrate (that is **SD4 — permanently forbidden**).
- ❌ Have natural-language confidence treated as evidence. **NL ≠ evidence.**

An organ's output is **advisory and bounded** (`_validated_delta`): a wrong or adversarial organ perturbs belief within a clamp, it cannot seize the loop. This is the C6 discipline — *the estimate stays out of the control path.*

## 5. The discipline this session ADDED to the contract (load-bearing)
1. **Organ reliability is CALIBRATED, not assumed** (ADR-0047/0048). The loop estimates how much an organ's output has been verifying as correct, and trusts it accordingly. An LLM that has been wrong on its most-confident picks earns *distrust* → escalate.
2. **The policy acts only on VERIFIED findings** (ADR-0047). Organ advice (especially the LLM's) is a candidate to *verify by intervention*, not a finding to act on. Silently trusting unverified LLM output is the documented failure mode.
3. **The LLM is good-but-noisy, not a dumb correlation machine** (ADR-0046): it reasons about confounds (0.90 vs correlation's 0.00) but **cannot reach certainty without intervention** (caps ~0.75). Hence: LLM proposes, CWM verifies. Neither alone.
4. **Operational fragility is part of the contract** (ADR-0047): an organ (esp. a remote LLM) can be slow or hang. The loop **must not block** on an organ — hard timeout + graceful degrade to CWM-verify + escalation. (Empirically: a kimi call hung 1h22m; `LLMPriorOrgan` backends must enforce a hard wall-clock cap and return a refusal, not hang.)

## 6. The candidate→action pipeline (every organ candidate passes this)
```
Organ candidate (OrganAdvice)
  -> bounded-delta validation (_validated_delta)
  -> [if SQL] SQL Safety            (OS-side at the seam)
  -> verification (intervention / OutcomeJudge)   ← turns candidate into a verified finding
  -> EvidenceChain binding          (OS-side at the seam)
  -> policy / risk gate (PolicySelector + stakes)
  -> ActionProposal
  -> approval if risk tier requires  (C7 / OS Approval)
```
No organ output reaches execution without passing verification + the gate. The LLM is the consultant; the loop is the decision-maker.
