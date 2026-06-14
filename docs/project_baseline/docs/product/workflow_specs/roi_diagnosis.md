# Workflow Spec: ROI Diagnosis

> Date: 2026-06-06  
> Owner: Product Manager Agent

## Intent

User asks why ROI dropped and which channel, campaign, or material is dragging performance.

## Primary User

Ad operations specialist, operations manager, or DTC growth owner.

## Normal Flow

```text
Question
-> BusinessIntent(metric=ROI, dimensions=channel/material)
-> MetricContract(ROI)
-> ProviderContract(ads + sales)
-> DataProduct candidate
-> SQL Safety
-> QueryResult
-> EvidenceChain
-> ActionProposal(limit budget / review material)
-> Approval lite
-> Feedback metrics
-> KnowledgeAsset candidate
```

## Output

- ROI trend and decomposition.
- Evidence-backed cause hypothesis.
- Governed action proposal, not direct budget change.
- Feedback metrics: ROI, spend, conversion rate, GMV.

## Failure States

| State | Behavior |
|---|---|
| Missing attribution dimension | Insufficient evidence |
| Unsafe SQL | Block answer/action |
| Low confidence | Mark recommendation as review-only |
| Budget action R4/R5 | Proposal-only; requires approval |

## Acceptance

- ROI formula and owner visible.
- Evidence includes provider and SQL.
- Action risk and approval requirement visible.
