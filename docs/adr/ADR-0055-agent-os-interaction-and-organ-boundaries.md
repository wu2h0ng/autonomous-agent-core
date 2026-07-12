# ADR-0055: Agent OS Interaction and Organ Boundaries

> Status: **Accepted**
> Date: 2026-07-11
> Owner: Founder / Product Architecture
> Scope: Product definition and canonical terminology only

## Context

The product definition had three recurring ambiguities: whether every request must become
a persistent task, whether `Skill` is a core intelligence primitive, and whether every
agent contains one CWM as its universal planning brain. These ambiguities would create a
heavy default experience, reintroduce prompt/skill glue as architecture, and overclaim a
research mechanism as delivered product capability.

## Decision

1. Agent OS remains the product; one coherent agent is its primary user-facing surface.
   Workflow orchestration is an internal executable representation, not the product identity.
2. The surface exposes `Ask` for ephemeral low-risk interaction and `Work` for durable,
   consequential or outcome-verified activity. Runtime routing is explainable and may
   escalate but cannot silently bypass an authority requirement.
3. Provider-neutral LLMs are probabilistic language/reasoning organs. Their untyped output
   never holds final execution authority.
4. World models are plural. CWM is an optional planning/verification organ for tasks with
   identifiable variables, interventions and outcomes, not a universal default.
5. `Skill` is not a canonical kernel object. External skill packages are compatibility
   inputs and must compile into typed capabilities, workflow/procedure candidates,
   knowledge dependencies and policy requirements.
6. Repeated successful work may produce a `LearnedProcedure` candidate, but publication
   requires versioning, held-out evaluation, permission review and rollback.
7. `CapabilityBroker`, deterministic policy/disposer and non-writable, non-bypassable C7
   retain final authority over consequential action.
8. Evidence is canonical at the Agent OS level, but Data Agent evidence terms are not.
   Data Agent `EvidenceChain` is a domain-specific projection of the generic Agent OS
   evidence contract. Metric, SQL, query-result and DataProduct semantics remain in
   `domain_packs/data_agent` adapters and may not enter OS Core contracts.

## Canonical Product Vocabulary

`InteractionDecision`, `CapabilitySpec`, `ToolPlugin`, `WorkflowTemplate`, `ScenePreset`,
`DomainPack`, `WorldModelPort`, `EvidenceChain` and `LearnedProcedure` are the canonical
product terms. User-facing copy may say "skill" only as an ecosystem compatibility label.

## Consequences

- Simple questions do not pay the persistence, workflow or learning cost of a durable task.
- Task Workspace remains mandatory for consequential or long-running work.
- Scene presets improve cold start without becoming fixed intelligence modules.
- Evidence surfaces can be shared across developer, personal and enterprise workflows
  without importing Data Agent SQL/metric vocabulary into the generic spine.
- CWM promotion still requires a named product consumer and fair real-workflow comparison.
- No research verdict, gate, runtime capability or migration authorization changes.

## Non-Goals

- This ADR does not implement the interaction router, preset compiler or `WorldModelPort`.
- It does not implement a new generic `EvidenceChain` schema beyond existing SPINE-0
  evidence primitives.
- It does not authorize third-party skill execution, CWM product claims or SPINE-1 migration.
- It does not weaken typed capability, approval, audit or correction boundaries.
