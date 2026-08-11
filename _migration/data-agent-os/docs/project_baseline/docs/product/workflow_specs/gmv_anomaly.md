# Workflow Spec: GMV Anomaly

> Date: 2026-06-06  
> Owner: Product Manager Agent

## Intent

User asks whether GMV is abnormal and what should be done.

## Primary User

Operations manager or business owner.

## Normal Flow

```text
Question
-> BusinessIntent(metric=GMV, window)
-> MetricContract(GMV)
-> ProviderContract(sales)
-> DataProduct candidate
-> SQL Safety
-> QueryResult
-> EvidenceChain
-> ActionProposal
-> Approval lite
-> Feedback / Trace
-> KnowledgeAsset candidate
```

## Output

- Business conclusion with confidence and limitations.
- EvidenceChain with metric, provider, SQL, result, trace.
- ActionProposal with risk, approval, observation window, feedback metrics.
- KnowledgeAsset candidate if feedback/outcome is recorded.

## Failure States

| State | Behavior |
|---|---|
| SQL blocked | No formal answer; no ActionProposal |
| Missing metric owner | Insufficient evidence; ask for owner/definition |
| Empty query result | Empty state; no fabricated anomaly |
| Approval required | Stop at awaiting approval; no side-effect execution |

## Acceptance

- Formal answer cannot render without EvidenceChain.
- ActionProposal must reference EvidenceChain.
- R4/R5 action remains proposal-only.
