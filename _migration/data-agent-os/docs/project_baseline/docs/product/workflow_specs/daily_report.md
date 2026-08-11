# Workflow Spec: Daily Report

> Date: 2026-06-06  
> Owner: Product Manager Agent

## Intent

User asks for today's business overview and priority anomalies.

## Primary User

Operations lead, CEO, or business owner.

## Normal Flow

```text
Question
-> BusinessIntent(type=daily_scan)
-> MetricContract subset
-> ProviderContract subset
-> DataProduct candidate
-> SQL Safety
-> QueryResult summary
-> EvidenceChain
-> ActionProposal(route to diagnosis)
-> Feedback / Trace
-> KnowledgeAsset candidate
```

## Output

- MVP metric summary.
- Priority anomaly.
- Evidence and limitation list.
- Suggested next diagnosis workflow.

## Failure States

| State | Behavior |
|---|---|
| Metric not connected | Mark as staged-out/unsupported |
| Partial data | Show limitations and confidence reduction |
| Empty result | Show empty state |
| Unsafe query | Block answer/action |

## Acceptance

- The report must state what it does not cover.
- It cannot claim inventory/content coverage unless data is connected.
- It routes anomalies to GMV/ROI diagnosis rather than fabricating broad strategy.
