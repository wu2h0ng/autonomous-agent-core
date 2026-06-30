# REF-ARCH-01: System Reference Architecture

> Subject: the research prototype as the governed agent loop. Status tags: ✅ exists/validated · 🟡 toy/partial · ❌ missing.

## 0. The thesis (what the Agent IS and ISN'T)
```
LLM            ≠ Agent      (LLM is an organ)
World Model    ≠ Agent      (a map of action→consequence)
Agent Runtime  ≠ Agent      (an execution/safety envelope)
Agent          = the governed closed loop:
                 perceive → model → propose → verify → decide → act → be-corrected → learn
```
The Agent is a **subject (a loop)**, not a model. Capability comes from the organs (incl. the LLM's trained prior + the CWM's learned causal structure); **governance comes from the loop** (policy + corrigibility + trace). This is the session's settled result: *governed model intelligence* — there is no separable autonomy axis, so "autonomy" here means a real, bounded, governed loop, not a magic property.

## 1. The layers (and the real modules behind them)

| Layer | Role | `src/aac/` module(s) | Status |
|---|---|---|---|
| **Model Organ Layer** | many models as advisory organs (LLM, CWM, consequence prior, ensembles, …) | `prior_organ.py` (`PriorOrgan`, `OrganAdvice`, `merge_organ_advice`), `prior_organ_llm.py` (`LLMPriorOrgan`, `LLMBackend`), `consequence_prior.py` (`BoundedConsequencePriorOrgan`), `prior_organ_ensemble/latent/library.py` | ✅ pattern exists |
| **World Model** | (a) causal mechanism + (b) belief/state ledger | (a) `causal_relevance.py` (`CausalRelevanceField`) + the CWM core (ADR-0045, currently `experiments/`); (b) `world_model.py`, `prior_organ.py:BeliefSnapshot` | (a) ✅ hallmark / 🟡 toy scope · (b) 🟡 toy |
| **Agent Self Model** | own capability / risk / boundary self-knowledge | DISTRIBUTED across `viability.py:ViabilityCore`, `policy.py:PolicySelector`, `shell.py` risk boundary | ❌ not a named consolidated module |
| **Policy / Decision** | choose action; adaptive verify-or-escalate by stakes | `policy.py:PolicySelector`, `rap_coordinator.py:RAPCoordinator`; trilemma policy ADR-0048 | ✅ trilemma validated / 🟡 not wired into one selector |
| **Corrigibility Shell (C7)** | top override the agent cannot overwrite | `shell.py:CorrigibilityShell`, `shell_ipc.py` | ✅ exists |
| **Verify / Outcome** | judge whether an action did what was claimed | `outcome_judge.py:OutcomeJudge`, `residual_calibrator.py:ResidualCalibrator` | ✅ exists / 🟡 toy |
| **Feedback / Learning** | update beliefs/organs from outcomes | organ belief updates (`_validated_delta`), `OutcomeJudge` | 🟡 partial |
| **Trace / Audit** | tamper-evident record of every step | `audit.py:AuditLog`, `AuditEntry` | ✅ exists |

## 2. The subject loop (one loop, real modules)
```
            ┌──────────────── Corrigibility Shell (C7, shell.py) ───────────────┐  ← always overrides
            │                                                                    │
 perceive → RelevanceField/CausalRelevanceField                                  │
   → MODEL: World Model (causal mechanism + belief ledger)                       │
   → PROPOSE: organs (LLMPriorOrgan + others) → OrganAdvice (bounded, advisory)  │  ← C6: organs out of control path
   → VERIFY: intervention / OutcomeJudge (turn advice into verified findings)    │
   → DECIDE: PolicySelector + adaptive verify-or-escalate (stakes → trust/verify/escalate)
   → ACT or ESCALATE  (never act on unverified organ output for high stakes)     │
   → OUTCOME → Feedback → belief/organ update                                    │
            │                                                                    │
            └──────────────── AuditLog (audit.py) records every step ───────────┘
```
`agent.py:Agent` = `ViabilityCore + WorldModel + RelevanceField + organs + PolicySelector + CorrigibilityShell + OutcomeJudge + AuditLog`, run as this loop.

## 3. The two "world models" (do not conflate — this is a common error)
- **Causal World Model** = the *mechanism/brain*: learns, by intervention, which inputs cause the outcome; predicts do(·) effects; robust to surface shift. ✅ hallmark validated (ADR-0045), 🟡 toy scope (binary, free interventions). **It does not transfer across domains — it re-learns each by experiment.**
- **Belief / State ledger** = the *memory*: "what I currently believe, how strong the evidence, which actions worked." 🟡 toy (`world_model.py` + `BeliefSnapshot`).
The CWM gives the ledger *causal teeth* only where you can intervene; elsewhere the ledger holds correlational beliefs flagged as such.

## 4. Generalization (the honest envelope, from this session)
- The **method** (do→measure→structure) is domain-general; the **learned model** is environment-specific (no transfer).
- Cross-domain breadth comes from the **LLM's trained prior** (organ), not from the CWM. The system adapts to a new domain = LLM prior gives a fast start + CWM verifies/corrects it locally.
- **Fit gate**: applies only where you can *enumerate candidate variables*, *intervene*, and *measure outcomes*, in a domain with *confounds* and *shift*. Outside that (observational-only, catastrophic interventions, unmeasurable latents) → it cannot learn there → escalate / stay observational. (See ADR-0045 fit notes.)

## 5. The OS injection seam (contract, not import — requires a separate ADR)
The prototype exposes a **governed decision organ** to the enterprise OS Trusted Loop:
```
OS (BusinessIntent → Contract/Semantic/DataProduct) 
   --[bounded task context + stakes/risk tier]-->  PROTOTYPE governed loop
   <--[verified proposal + confidence + evidence refs + escalation decision]--  
OS (EvidenceChain → ActionProposal → Approval → Feedback → KnowledgeAsset)
```
- The OS keeps its own SQL Safety / EvidenceChain / Approval. The prototype supplies the **decide–verify–escalate brain** (CWM + adaptive policy + C7), never direct execution.
- The OS's `BusinessWorldModelLite` (belief ledger, product-side) is the OS analogue of the prototype's belief ledger; the OS's `AgentSelfModel` is the product-side capability/risk map. The seam maps prototype↔OS, it does not merge codebases.
- **Hard Boundary #19**: this wiring needs a founder/CTO-approved cross-repo ADR. This document defines the seam; it does not authorize the integration.

## 6. Status summary / gaps to close (in order)
1. ✅ **Consolidated `AgentSelfModel`** (`src/aac/self_model.py`) — built + tested (capability/risk/boundary self-knowledge). 🟡 not yet wired into the `agent.py` loop (the scattered `ViabilityCore`/`PolicySelector`/shell sources still exist; this is the single consolidated source going forward). → REF-ARCH-03.
2. ✅ **`GovernedDecisionGate`** (`src/aac/governed_gate.py`) — the ADR-0048 stakes-keyed verify-or-escalate trilemma as a first-class component, built + tested (11 tests), respects the C7 shell view. 🟡 not yet the single live decision point inside the loop. → REF-ARCH-04.
3. 🟡 **Promote the CWM core from `experiments/` into `src/aac/` as a first-class organ** behind the `PriorOrgan` contract. → REF-ARCH-02.
4. ❌ **Cross-repo injection ADR** for the OS seam (founder/CTO).
5. 🟡 **One real vertical slice** exercising the full loop end-to-end on a fit-gate-passing task. → REF-ARCH-03 §slice.
