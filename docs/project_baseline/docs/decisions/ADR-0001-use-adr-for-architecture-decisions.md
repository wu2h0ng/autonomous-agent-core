# ADR-0001: Use ADRs for Architecture Decisions

> Status: Accepted  
> Date: 2026-06-01  
> Owner: CTO  

## Context

The project will use Code Agents heavily. Without durable decision records, agents and engineers may repeatedly revisit settled decisions, apply stale assumptions, or implement conflicting architecture patterns.

The current package already contains strategy, PRD, CTO management docs, Agent rules, and a code index. It still needs a concise decision log that records architectural choices, tradeoffs, and change conditions.

## Decision

Use Architecture Decision Records (ADRs) for material technical and engineering-process decisions.

ADRs are required when a decision affects:

- OS Core boundaries.
- Contract/schema design.
- SQL Safety.
- EvidenceChain, Eval, or Trace.
- Agent roles, workflow, model routing, or automation level.
- Provider, Action Connector, MCP, deployment, auth, permissions, or secrets.
- Repository scaffold or module ownership.

ADRs live in:

```text
docs/decisions/
```

Naming:

```text
ADR-0001-short-title.md
ADR-0002-short-title.md
```

## Consequences

Benefits:

- Agents have a stable source of truth for architectural decisions.
- CTO approval can reference durable decision records.
- Changes can be audited and reversed with context.
- Future onboarding and code review become easier.

Costs:

- Each material decision needs a short record.
- ADRs must be kept current when decisions are superseded.

## Change Rules

An ADR can be:

- `Proposed`
- `Accepted`
- `Superseded`
- `Rejected`

Accepted ADRs should not be edited to change history. If the decision changes, create a new ADR and mark the old one as superseded.

