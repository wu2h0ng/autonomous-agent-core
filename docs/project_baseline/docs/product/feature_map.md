# MVP Feature Map

> Date: 2026-06-06  
> Owner: Product Manager Agent  
> Scope: Stage 1 Trusted Business Production Loop

## 1. Priority Rule

P0 features must directly strengthen the minimum business production loop:

```text
BusinessIntent -> DataProduct candidate -> EvidenceChain -> ActionProposal
-> Approval lite -> Feedback / Trace -> KnowledgeAsset candidate
```

Anything that only improves platform breadth, connector breadth, dashboard polish, or future marketplace motion is P1/P2 unless CTO-approved.

## 2. Feature Tree

| Priority | Feature | Purpose | Dependencies |
|---|---|---|---|
| P0 | BusinessIntent intake | Structure business questions | contracts, intent parser |
| P0 | SemanticObject lite binding | Prevent raw prompt-to-SQL ambiguity | semantic runtime |
| P0 | MetricContract binding | Lock metric owner/version/formula | contracts, domain pack |
| P0 | ProviderContract lite selection | Keep data plane pluggable and governed | data access plane |
| P0 | DataProduct candidate | Make answer reusable/reviewable, not one-off | data product compiler |
| P0 | SQL Safety | Block unsafe or unbounded SQL | sql safety |
| P0 | Query Runtime | Execute approved query path | provider/query runtime |
| P0 | EvidenceChain | Make formal answers auditable | evidence builder |
| P0 | ActionProposal | Convert evidence to governed next step | action proposal |
| P0 | Approval lite | Stop high-risk actions before execution | approval lite / operation trace |
| P0 | Feedback capture | Close the learning loop | feedback runtime |
| P0 | KnowledgeAsset candidate | Turn loop output into reviewable asset | knowledge memory |
| P0 | Trace / OperationTrace | Replay trust/action path | trace / operation trace |
| P0 | Intent Workspace F0/F1 | Human control surface | frontend contract-shaped state |
| P1 | Empty/loading UI states | Product robustness | frontend scaffold |
| P1 | Typed API integration | Connect UI to live trusted loop | API contract stability |
| P1 | Persistent stores | Cross-process feedback/knowledge continuity | persistence ADR |
| P1 | Eval threshold report | Release confidence | eval harness |
| P1 | Action connector routing policy | Decide when real write connectors can be used | product + CTO decision |
| P2 | KnowledgeAsset registry UI | Review/publish reusable assets | knowledge workflow |
| P2 | Telemetry dashboard | Business/quality/cost visibility | observability pipeline |
| P2 | Multi-provider expansion | Broader customer data planes | provider contracts |
| P2 | Mobile operational workflow | Field use cases | validated mobile need |

## 3. Staged-Out Items

- Full Data Fabric / NoETL / distributed query engine.
- Broad connector marketplace.
- Full BPM/approval workflow.
- R4/R5 automatic execution.
- Production deployment and tenant-scale RLS.
- External Agent framework runtime adoption.

## 4. Dependency Notes

- Frontend must consume public API contracts only.
- OS Core must not import domain packs, providers, examples, or action connectors.
- `action_record` connector may prove real governed write/rollback mechanics, but product default routing remains gated.
- SQLite provider path is acceptable for real local smoke/eval, not production data plane.
