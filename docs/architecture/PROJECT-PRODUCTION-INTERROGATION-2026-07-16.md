# Project Production Interrogation

> Status: `ATTACK_QUESTIONS / NO_ACTION_BY_ITSELF`
> Updated: 2026-07-16
> Role: Technical and business interviewer pressure test.
> Scope: Questions that force the project from architecture narrative toward generic production deployment.

## 1. Core thesis pressure

1. If the project is "general", what exact task distribution is it general over, and what is the cheapest baseline that would embarrass it?
2. What hidden cognitive work does the system remove from the operator this week: state maintenance, relevance judgment, next-step generation, verification, or coordination?
3. If the user stops prompting for seven days, what continues, what safely pauses, and what evidence proves the difference from a scheduled workflow?
4. Which part of the system forms new subgoals from Mandate rather than from user prompts? Where is that code path?
5. What is the first production use case where a model-plus-tools baseline clearly fails and Agent OS has a defensible advantage?

## 2. Algorithm and reasoning pressure

1. When does the system choose model planning, data exploration, statistical modeling, causal design, optimization, or human escalation?
2. Is there a `MethodSelector` with typed inputs, deterministic gates and tests, or is this still a prompt convention?
3. How does the system distinguish correlation, causality, missing data, delayed effects and unidentifiable claims?
4. What failure mode proves that a stronger algorithm is needed rather than better context or a stricter contract?
5. Which claims require held-out evaluation, and which are only local engineering assertions?

## 3. Domain adaptation pressure

1. How does the system enter a new domain without a hand-built Domain Pack?
2. What is the data structure for a learned domain model, and what prevents inferred ontology from becoming false authority?
3. How are industry methods compiled into callable `MethodAsset`s rather than stored as documents?
4. What is the difference between optional domain prior, knowledge asset, workflow candidate and product capability?
5. What is the first cross-domain migration test, and what transfer cost is acceptable?

## 4. Knowledge and memory pressure

1. Can the system separate evidence, belief, rule, pattern, procedure, case and method?
2. Which knowledge updates take effect immediately, and which require W3 promotion?
3. Can a bad historical lesson be detected, downgraded, revoked and prevented from influencing future actions?
4. Where is knowledge asset usage measured against outcome quality?
5. Does retrieval merely find text, or does it change planning, evidence requirements and tool choice?

## 5. Training pressure

1. What exact failure class justifies SFT instead of better tools, schemas, RAG or Runtime gates?
2. What trace/outcome data is clean enough to become training data?
3. What prevents RLHF/GRPO from optimizing for convincing reports rather than verified outcomes?
4. What is the offline eval, shadow, canary and rollback path for a trained model?
5. Which safety and authority properties are forbidden from being delegated to training?

## 6. Multimodal pressure

1. What is the modality intermediate representation for image, PDF, audio and video?
2. How are page, timestamp, bounding box and extracted table anchors preserved in evidence?
3. What is the fallback when the selected model cannot process the modality?
4. Which tasks require multimodal semantic understanding rather than OCR/transcription plus text reasoning?
5. How is multimodal hallucination detected before it affects an action or outcome?

## 7. Distributed runtime pressure

1. Is an Agent a process, an actor, a durable workflow, or a persisted responsibility unit?
2. How many active workers are needed for one million dormant agents?
3. What is the idempotency story for external effects?
4. How does lease fencing prevent two workers from mutating the same run?
5. What is the backpressure strategy when model, database or connector capacity collapses?
6. What are the cost ledgers per tenant, task, model, tool and outcome?
7. How do we replay one agent's decision timeline without leaking secrets or unsafe raw payloads?

## 8. Product and business pressure

1. Which user result is delivered today, and which is only architecture?
2. What is the smallest paid or production-adjacent path that does not depend on claiming AGI?
3. How does the system prove value against direct model-plus-tools with equal data, time and cost?
4. Which customer task is frequent, painful, measurable and safe enough for the first deployment?
5. What is the first thing we should delete or park if it does not reduce operator cognitive load?

## 9. Release pressure

1. What exact gate upgrades a local verified slice to controlled pilot?
2. What incident can C7 handle today, and what remains manual?
3. Which secrets, credentials and tenant boundaries are production-grade, and which are local-only?
4. Which tests would fail if a model output bypassed policy, evidence or outcome truth?
5. What is the rollback path for a learned procedure, a policy candidate and a runtime version?

## 10. Use as a standing review

Before any major roadmap expansion, answer:

```text
What current user failure does this close?
What baseline does it beat?
What code path implements it?
What evidence proves it?
What authority boundary protects it?
What cheaper path was rejected?
What would falsify it?
```

## 11. Machine-checkable gate extraction

The following questions are not rhetorical. They must map to verification matrix gates before implementation claims advance:

| Interrogation question | Required gate |
|---|---|
| Which part forms subgoals from Mandate rather than user prompts? | `P-SRL-RUNTIME-M1-plus`: authorized event creates non-executing TaskDraft. |
| Where is the code path? | Completion claim must name source checkout, public entry point and tests. |
| What baseline would embarrass it? | `P-SRL-E2E-FALSIFIER-1`: user-driven prompt and scheduled-workflow arms. |
| How is operator cognitive load measured? | HCW ledger with hidden scorer and drift detection. |
| When does the system plan, explore, run algorithms or ask for help? | `P-SRL-DISPATCH-1` score receipt and method receipt. |
| Can model narration satisfy evidence? | `P-SRL-ADVERSARIAL-1`: model narration cannot satisfy evidence requirement. |
| What prevents inferred ontology from becoming authority? | Domain work stays deferred or prior-ingest only until validated by evaluator. |
| Which knowledge updates require W3 promotion? | `P-KNOWLEDGE-ASSET-TYPES-1`: rule/default behavior changes require W3. |
| What trace/outcome data is clean enough for training? | Training remains deferred until verified outcome traces beat tools/schema/RAG insufficiency falsifier. |
| How are multimodal claims grounded? | Multimodal remains deferred until evidence chain can carry modal anchors. |
| How does lease fencing prevent double mutation? | Distributed runtime remains deferred; local SRL claims cannot cite production-scale lease evidence. |
| Which secrets and tenant boundaries are production-grade? | `P-SECURITY-BOUNDARY-0`: trace redaction, tenant scope and credential ref tests. |
| Which tests fail if policy is bypassed? | `P-SRL-ADVERSARIAL-1` and TaskDraft/TaskActivation boundary tests. |
| What is rollback for policy or mandate changes? | `P-OBSERVABILITY-LEDGER-0`: policy/binding epoch rollback test. |
| What should be parked if it does not reduce operator load? | Any package without E2E falsifier movement remains `DEFERRED` or `PARKED`. |
