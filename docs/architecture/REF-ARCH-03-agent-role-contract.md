# REF-ARCH-03: Agent Role Contract

> Roles are **cognitive functions inside ONE governed loop**, not sovereign agents. `Agent role ≠ sovereign agent; Agent role = governed worker inside the Trusted Loop.` All roles route through the same runtime gate (REF-ARCH-04).

## 1. The prototype's cognitive roles (research subject)
| Role | Responsibility | Input | Output | May use | Failure path |
|---|---|---|---|---|---|
| **Perceive** | attend to the relevant slice of state | raw state | attended context (`BeliefSnapshot`) | `relevance.py`, `causal_relevance.py` | empty/over-broad → flag low-confidence |
| **Model** | maintain causal mechanism + belief ledger | context, outcomes | updated world model | CWM organ, `world_model.py` | shift detected → mark stale, re-probe |
| **Propose** | generate candidate hypotheses/actions | context + task | `OrganAdvice` (bounded) | LLM + other organs (REF-ARCH-02) | organ slow/refuse → degrade, don't block |
| **Verify** | turn candidates into verified findings by intervention | candidate | verdict + evidence | intervention, `outcome_judge.py` | can't verify → ESCALATE (don't trust) |
| **Decide** | choose action under stakes (verify/escalate/trust) | verified findings + self model | decision | `policy.py:PolicySelector` + ADR-0048 trilemma | low confidence / high risk → escalate |
| **Govern** | enforce the boundary the agent can't overwrite | decision | allow / block / require-approval | `shell.py:CorrigibilityShell` (C7) | violation → block + audit |
| **Learn** | update beliefs/organs from outcomes | outcome/feedback | belief/organ delta | `_validated_delta`, `OutcomeJudge` | bad update → bounded, reversible |
| **Self-monitor** ❌ | know own capability/risk/boundary | run context | `AgentSelfModel` | (to build) | over-reach → refuse/escalate |

**The missing one (❌): a consolidated `AgentSelfModel`.** Today self-knowledge is scattered across `ViabilityCore` (self-state), `PolicySelector` (choice), and the shell (risk boundary). REF-ARCH-01 §6 lists this as the #1 gap. Proposed shape (design only, not yet built):
```
AgentSelfModel:
  allowed_tools / denied_tools
  risk_ceiling
  approval_required_actions
  evidence_requirements
  confidence_thresholds
  budget_limits
  escalation_policy
```
It answers: *does the agent know what it may not do, and when to stop?* It is what turns "can call a tool" into "knows when not to."

## 2. The non-negotiable rule
```
multi-role reasoning INSIDE one governed loop     ✅
many autonomous agents loosely coordinated        ❌
```
Otherwise: role A says yes, role B executes, role C had no evidence, the runtime only logged it, and **no one owns the outcome.** One subject loop = one accountable boundary.

## 3. The OS seam — prototype roles ↔ enterprise business roles
The enterprise OS business roles (Intent / Semantic / Data / Evidence / Decision / Risk / Action / Feedback / Memory) are **consumers** of the prototype's governed brain, not separate sovereign agents:
| OS business role | backed by prototype role(s) | at the seam |
|---|---|---|
| Intent / Semantic | Perceive + Propose (LLM organ) | OS feeds bounded intent → prototype returns parsed candidates |
| Data / Evidence | Propose + Verify | prototype proposes query/plan, OS runs SQL Safety + EvidenceChain |
| **Decision / Risk** | **Decide + Govern (CWM + adaptive policy + C7)** | the core seam: prototype returns verified proposal + confidence + escalation |
| Action | (proposal only) | prototype never executes; OS Approval + connectors do |
| Feedback / Memory | Learn | OS outcome/adoption → prototype belief update; OS KnowledgeAsset |

The prototype supplies **Decide–Verify–Govern**; the OS supplies the **business contracts, SQL Safety, EvidenceChain, Approval, connectors**. Cross-repo wiring needs the founder/CTO ADR (Hard Boundary #19).

## 4. The minimal vertical slice (build this, not 9 roles)
Prove the loop end-to-end with **2–3 roles**, on a task that passes the fit gate (intervenable + measurable + has confounds):
```
task/intent
  -> Propose (LLM organ: candidate levers/hypotheses, ranked)
  -> Verify (intervention/CWM: which candidate actually causes the outcome)
  -> Decide (adaptive verify-or-escalate by stakes)
  -> proposal OR escalation
  -> outcome -> Learn (belief update)
        [Govern (C7) wraps the whole slice; AuditLog records it]
```
This is the smallest thing that exercises every layer of REF-ARCH-01. Expand role count only after this slice is green with a test that fails if verification/escalation is bypassed (Hard Boundary #13/16).
