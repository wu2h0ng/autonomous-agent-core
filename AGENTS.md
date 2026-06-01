# AGENTS.md

## Scope

These rules apply to code under `data-agent-os/`.

## Hard Boundaries

1. Keep OS Core independent from Customer-0 and domain-specific code.
2. Do not import `domain_packs/`, `examples/`, `providers/`, or `action_connectors/` from `packages/os_core/`.
3. Do not use OpenAI Agents SDK, LangGraph, CrewAI, AutoGen, OpenHands, Goose, Aider, Cline, or OpenCode as product Core runtime dependencies.
4. All formal answers must pass through SQL Safety and EvidenceChain.
5. R4/R5 business actions are proposal-only in MVP.
6. Every behavioral change must include or update tests.

## Required Flow

```text
Contract
  -> Safety
  -> Eval/Test
  -> Implementation
  -> Review
  -> Traceable result
```

## First Milestone

Make the Trusted Loop runnable and testable before adding API, UI, workflow engines, or external connectors.
