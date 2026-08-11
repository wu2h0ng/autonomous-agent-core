# ADR-0005: Full OS Architecture Is a Staged Target

> Date: 2026-06-01  
> Status: Accepted  
> Owner: CTO  

## Context

The project needs a complete AI Native Business Data OS architecture, but the first implementation stage must remain narrow enough to ship and validate.

Existing documents define the long-term OS vision and the MVP Trusted Loop. Without an explicit decision, future Code Agents may confuse the full OS target architecture with immediate implementation scope.

## Decision

The full OS architecture is accepted as the long-term target architecture and module evolution baseline.

The first implementation stage remains the approved MVP Trusted Loop:

```text
BusinessQuestion
  -> BusinessIntent
  -> MetricContract
  -> SQLTemplate / QueryPlan
  -> SQLSafety
  -> QueryResult
  -> EvidenceChain
  -> Answer
  -> ActionProposal lite
  -> Feedback / Trace
  -> Eval regression
```

Full OS modules such as complete Data Product Compiler, Domain Pack SDK, MCP Gateway, Marketplace, Hybrid deployment, private deployment, and high-risk action execution may only be activated through staged CTO approval.

## Consequences

- Architecture documents may describe the complete OS, but implementation PRs must reference the approved stage.
- `repo_scaffold/README.md` remains the first-stage scaffold until CTO approves a scaffold expansion.
- Every new stage requires Architecture Design Brief, CTO approval, Contract impact analysis, Eval plan, and security review.
- Core must not depend on Domain Pack, concrete Provider implementations, concrete Action Connector implementations, or customer-specific code.
- R4/R5 actions remain proposal-only until OperationContract, PolicyDecision, ApprovalDecision, rollback/compensation, and OperationTrace are implemented and approved.

## References

- `docs/architecture_reviews/AR-20260601-full-os-target-architecture.md`
- `docs/architecture_reviews/AR-20260601-full-os-module-architecture.md`
- `docs/architecture_reviews/AR-20260601-full-os-stage-architecture.md`
- `docs/architecture_reviews/CTO-APPROVAL-20260601-full-os-architecture.md`
- `docs/architecture_reviews/AR-20260601-mvp-trusted-loop-architecture.md`

