# PRD-MVP: Trusted Business Production Loop

> Date: 2026-06-06  
> Owner: Product Manager Agent  
> Status: Draft for CTO review  
> Source of truth inputs: `MEMORY.md`, `docs/product/product-blueprint-and-prototype.md`, `.agent`, `ai-native-business-data-agent-os/README.md`, `00_对话总结与阅读指南/项目定义与价值叙事基线.md`

## 1. Product Definition

AI Native Business Data Agent OS is the enterprise business production operating system for the AI Agent era. The MVP must not collapse into trusted Q&A, a control-plane shell, or middleware. It must prove a minimum but real loop:

```text
BusinessIntent
  -> SemanticObject lite
  -> MetricContract
  -> ProviderContract lite
  -> DataProduct candidate
  -> SQL Safety / Eval
  -> EvidenceChain
  -> ActionProposal
  -> Approval lite
  -> Feedback / Trace
  -> KnowledgeAsset candidate
```

The MVP product promise is:

```text
Ask a business question, get trusted evidence, receive a governed action proposal,
capture outcome feedback, and turn the loop into reusable business knowledge.
```

## 2. Target Users

| User | Primary Need | MVP Value |
|---|---|---|
| Operations manager | Diagnose GMV / ROI / daily business anomalies | Faster answer with evidence and proposed next action |
| Business owner | Decide whether to approve a recommended action | See risk, approval requirement, evidence id, and observation window |
| Data owner | Keep metric definitions and source use auditable | MetricContract, ProviderContract, SQL Safety, Eval |
| CTO / security reviewer | Verify that AI data work is controlled | Trace, SQL Safety, no R4/R5 auto execution, no domain logic in Core |

## 3. MVP Scenarios

| Scenario | Golden Loop | P0 Outcome |
|---|---|---|
| GMV anomaly diagnosis | GMV abnormality | Identify anomaly, cite evidence, propose governed action |
| ROI optimization | 投放效率诊断 | Explain channel/material drag, propose budget or review action |
| Daily business scan | 日报全景扫描 | Summarize key metrics, flag priority anomaly, route to diagnosis |

## 4. P0 Functional Scope

### P0-1 Business Intent Intake

The system accepts a business question and resolves it into a structured BusinessIntent with role, metric, time window, constraints, and trace id.

### P0-2 Semantic and Metric Binding

The system binds intent to a SemanticObject lite and MetricContract. It must expose owner, version, formula or verified template reference, and limitations.

### P0-3 Provider and DataProduct Candidate

The system selects a ProviderContract lite and creates a DataProduct candidate with DataRequirement, lineage/metadata snapshot, query plan, and reuse/review status.

### P0-4 SQL Safety and Query Result

Every formal answer must pass SQL Safety. Unsafe SQL is blocked and produces no formal business answer or action proposal.

### P0-5 EvidenceChain

Every formal answer must include EvidenceChain: question, intent, metric, provider, SQL evidence, result summary, limitations, confidence, and trace linkage.

### P0-6 ActionProposal and Approval Lite

The system creates an ActionProposal that references EvidenceChain, carries R1-R5 risk, recommended action, approval requirement, observation window, rollback/compensation note if applicable, and feedback metrics. R4/R5 are proposal-only.

### P0-7 Feedback / Trace / KnowledgeAsset Candidate

The system captures explicit feedback or observed outcome, updates trace/operation trace, and creates or versions a KnowledgeAsset candidate for human review.

### P0-8 Intent Workspace F0/F1

The workspace must show Business Context, Trusted Answer, EvidenceChain, DataProduct candidate, ActionProposal, Approval state, Feedback, and Trace. It must not hide trust details behind a generic AI answer.

## 5. Non-Goals

- No full Data Fabric, NoETL, or distributed data plane.
- No broad connector marketplace.
- No production-data connection by default.
- No R4/R5 automatic execution.
- No external Agent framework as Core runtime.
- No domain-specific content-commerce logic in OS Core.
- No live UI API integration until contracts and tests are stable.
- No customer-facing claim that the prototype is production capability.

## 6. Success Metrics

| Metric | MVP Target |
|---|---|
| Golden loop pass count | At least 3 scenarios runnable or mocked with contract-shaped state |
| EvidenceChain rate | 100% for formal answers |
| SQL safety pass/block correctness | 100% for covered golden and negative cases |
| ActionProposal evidence reference | 100% |
| Feedback/KnowledgeAsset candidate creation | At least one real path from accepted entry point |
| North star learning metric | Weekly user-initiated business questions tracked, target >= 10/week in pilot |

## 7. Quality Gates

- Tests before implementation.
- No pseudo implementation: no unused shell, constant-return success, or fixture-only test.
- Every P0 behavior has a failure path.
- Every trust/action behavior updates Trace, Evidence, OperationTrace, Feedback, or KnowledgeAsset as appropriate.
- CTO review required for contract, SQL Safety, EvidenceChain, Eval, Trace, Provider, ActionConnector, model routing, auth, deployment, or R4/R5 risk changes.

## 8. Open Product Decisions

| Decision | Current Position | Owner |
|---|---|---|
| When to promote `product-blueprint-and-prototype.md` from draft to source of truth | Needs CTO approval | CTO |
| Whether F1 prototype ships inside PR-07 or separate PR | Prefer separate if API contract work is not stable | CTO + PM |
| When ActionProposal routes to `action_record` connector by default | Not until approval and rollback expectations are explicit | Product + CTO |
| Whether internal contracts migrate from dataclass to Pydantic | Requires ADR | CTO + Contract Agent |
