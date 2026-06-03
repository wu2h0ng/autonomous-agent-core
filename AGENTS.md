# AGENTS.md

## Scope

These rules apply to code under `ai-native-business-data-agent-os/`.

## Hard Boundaries

1. Keep OS Core independent from Customer-0 and domain-specific code.
2. Do not import `domain_packs/`, `examples/`, `providers/`, or `action_connectors/` from `packages/os_core/`.
3. Do not use OpenAI Agents SDK, LangGraph, CrewAI, AutoGen, OpenHands, Goose, Aider, Cline, or OpenCode as product Core runtime dependencies.
4. All formal answers must pass through SQL Safety and EvidenceChain.
5. R4/R5 business actions are proposal-only in MVP.
6. Every behavioral change must include or update tests.
7. Do not submit pseudo implementation: empty shells, hard-coded success, unused adapters,
   documentation-only behavior, or tests that merely assert fixture values are not complete.
8. A new runtime capability must be reachable from a real entry point and must expose at
   least one failure path.

## Required Flow

```text
Contract
  -> Safety
  -> Eval/Test
  -> Implementation
  -> Review
  -> Traceable result
```

## Completion Gate

Before marking a task complete, state:

- The real entry point that invokes the new code.
- The contract/schema consumed or produced.
- The negative path covered by tests or explicitly documented as pending.
- The regression test or eval that would fail if the code were bypassed.
- The reason OS Core boundaries remain intact.

## First Milestone

Make the Trusted Loop runnable and testable before adding API, UI, workflow engines, or external connectors.
