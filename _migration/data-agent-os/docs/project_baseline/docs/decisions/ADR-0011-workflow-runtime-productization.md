# ADR-0011: Workflow Runtime Productization Path (V5)

> Status: Accepted (CTO approved 2026-06-12)  
> Date: 2026-06-11  
> Owner: CTO  

> Note: acceptance locks in the productization *path* (Decisions 1–3). Actual V5
> implementation stays dormant until the trigger condition in Decision 3 is met,
> and its activation additionally requires an architecture review document.

## Context

`ai-agent-engineering-workflow/` has reached its approved automation ceiling A2
(spec §6): init → quality → status → pr → notify are implemented, gate-enforced,
and dogfooded (PR #1/#2 were opened by the tool itself). The orchestration spec
(§0, §10) anticipates the workflow becoming a prototype for an Agent OS product
capability, but explicitly requires a new ADR and architecture review before any
productization. Hard boundaries that constrain the path:

- Workflow code must not be imported by product runtime (workflow.yaml boundary rule).
- Agent OS Core must be 100% self-developed and domain-independent (.agent rules 7, 15).
- Product implementation lives only in `ai-native-business-data-agent-os/` (.agent rule 8).

## Decision

Proposed (not yet effective):

1. The workflow tool stays a standalone development-governance tool. It is never
   imported by product code.
2. Productization, when triggered, means re-implementing the proven state machine
   (Goal Card → gates → artifacts → PR) inside `os_core` as an "AgentRun
   governance" capability, following the normal product flow: Goal Card →
   architecture gate → CTO approval → contract-first TDD implementation.
3. Trigger condition for starting that work: the product roadmap needs governed
   agent-run execution AND at least two concrete internal consumers exist
   (e.g., Trusted Loop operation runs, eval pipeline runs). Until then, V5 stays dormant.

## Consequences

- Benefits: boundary stays clean; the tool keeps iterating at dev speed; product
  capability inherits a battle-tested design rather than experimental code.
- Tradeoffs: re-implementation cost when triggered; two codebases share a design
  but not code, so spec drift must be managed via this ADR and the orchestration spec.
- Risk: premature productization is the main failure mode this ADR guards against.

## Alternatives Considered

- Import the workflow package into the product: rejected — violates workflow.yaml
  boundary rule and .agent rule 8.
- Productize now: rejected — no internal consumer exists; would be speculative
  generality contradicting MVP discipline.
- Never productize: rejected — spec §10 explicitly values the workflow as a
  product capability prototype.

## Change Rules

Revisit when: the trigger condition in Decision #3 is met; or the product needs
run-level governance (operation runs, eval runs) earlier than expected; or
CTO supersedes this ADR. Activation requires CTO approval recorded here
(Status → Accepted) plus an architecture review document.
