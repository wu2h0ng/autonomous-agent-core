# ADR-0002: First Stage Scope Is Trusted Loop, Not Full OS

> Status: Accepted  
> Date: 2026-06-01  
> Owner: CTO  

## Context

The long-term product direction is AI Native Business Data OS. The full vision includes BusinessIntent, Data Agent, DataProduct Compiler, EvidenceChain, Business Agent, governed actions, deployment profiles, marketplace, and knowledge assets.

Building the full OS in the first stage would create excessive platform work before proving customer-visible value.

## Decision

The first engineering stage will only target the trusted loop:

```text
BusinessIntent
  -> MetricContract
  -> SQL Safety / Eval
  -> EvidenceChain
  -> ActionProposal
  -> Approval lite
  -> Feedback / Trace
```

The first stage will not implement:

- Full marketplace.
- Full private or air-gapped deployment.
- Full Business Agent autonomous execution.
- R4/R5 automatic business actions.
- Full MCP Gateway.
- Full Domain Pack SDK.
- Full data platform replacement.

## Consequences

Benefits:

- Engineering scope is measurable.
- Agent development can be gated by eval and trace.
- The team can validate business value before platform expansion.

Tradeoffs:

- Some long-term architecture surfaces are represented as interfaces or docs before full implementation.
- Sales messaging must avoid overclaiming full OS capabilities during MVP.

## Acceptance Criteria

The first stage is successful only if:

- Formal answers have EvidenceChain coverage.
- SQL Safety blocks unsafe query paths.
- Golden query and metric eval meet phase thresholds.
- ActionProposal references evidence and includes risk level.
- Failures become regression cases.

