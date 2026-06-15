# AGENTS.md — ai-native-business-data-agent-os

> Last updated: 2026-06-12  
> Role in workspace: **Deployment Layer** (enterprise OS, future downgrade projection of `autonomous-agent-core/`)

## Scope

These rules apply to code under `ai-native-business-data-agent-os/`.

For the three-repo role map, see the baseline workspace `.agent` file and `docs/research/RR-0004-artifact-map.md`.

## Stage 1 Status (Complete — 2026-06-11)

PR-01 through PR-06 all merged to `main` (commit `9d2d8d6`). P5 substrate harvest is underway: 309 unit tests passing, 2 eval tests passing, OpenAPI contract clean, ruff clean.

Delivered: Trusted Loop (full chain), persistence (SQLAlchemy Core + Alembic, 4 store ports), knowledge retrieval (hybrid scoring + pgvector-ready), observability (RunTrace + trace store + audit surface + gate), OpenAPI contract gate, unified block contract, SQL Safety hardening, grounding invariant (P5.1b-ii), eval hub, 12-factor env wiring, action governance (state machine + snapshot/rollback), P5.2a corrigibility pause shell (operator shell + runtime view + hash-chain audit + PAUSED refusal).

## Hard Boundaries

1. Keep OS Core independent from Customer-0 and domain-specific code.
2. Do not import `domain_packs/`, `examples/`, `providers/`, or `action_connectors/` from `packages/os_core/`.
3. Do not use OpenAI Agents SDK, LangGraph, CrewAI, AutoGen, OpenHands, Goose, Aider, Cline, or OpenCode as product Core runtime dependencies.
4. All formal answers must pass through SQL Safety and EvidenceChain.
5. R4/R5 business actions are proposal-only in MVP.
6. Every behavioral change must include or update tests.
7. Do not submit pseudo implementation: empty shells, hard-coded success, unused adapters, documentation-only behavior, or tests that merely assert fixture values are not complete.
8. A new runtime capability must be reachable from a real entry point and must expose at least one failure path.
9. Write tests before implementation code (test-first discipline).
10. MVP "lite" = functionally limited but real. Not skeleton/stub/constant-return.
11. OpenAPI contract (`apps/api_server/openapi.json`) is the typed API contract. Any API change must regenerate the snapshot and pass the drift gate.
12. Do not import or copy code from `autonomous-agent-core/` or `ai-agent-engineering-workflow/`. Cross-repo integration requires a new ADR.
13. Persistence adapters implement OS Core Ports — OS Core never imports persistence.

## Required Flow

```text
Contract / ADR
  → Tests (test-first, failure must prove implementation absence)
  → Implementation
  → Eval/Test green
  → Review
  → Traceable result (Trace/Evidence/OperationTrace updated)
```

For medium/high-risk work: Goal Card → Context Pack → Architecture Brief → CTO approval → Implementation → Review → Release.

## Completion Gate

Before marking a task complete, state:

- The real entry point that invokes the new code.
- The contract/schema consumed or produced.
- The negative path covered by tests or explicitly documented as pending.
- The regression test or eval that would fail if the code were bypassed.
- The reason OS Core boundaries remain intact.
- Whether the OpenAPI contract surface changed (and if so, snapshot regenerated + drift gate passed).
- Whether observability trace steps and telemetry dimensions are updated.

## Module Inventory (Stage 1 Complete)

| Module | Path | Key Capabilities |
|---|---|---|
| Contracts | `packages/contracts/` | BusinessIntent, MetricContract, EvidenceChain, ActionProposal, OperationContract, KnowledgeAsset, RunTrace, BlockCode, etc. |
| OS Core | `packages/os_core/` | Trusted Loop, Intent Parser, Semantic Runtime, Data Access Plane, Data Product Compiler, SQL Safety, Query Runtime, EvidenceChain, ActionProposal, Action Governance, Approval Lite, Operation Trace, Feedback, Knowledge Memory, Snapshot Store, Trace/Telemetry, Eval Hub, Agent Runtime shell, Model Gateway, Embedding, Knowledge Retrieval |
| Persistence | `packages/persistence/` | SQLAlchemy Core sync adapters for all 5 store ports + Alembic migrations (0001–0005) |
| API Server | `apps/api_server/` | FastAPI app + OpenAPI contract gate + CLI (query, record-outcome, trace, search) + 12-factor env wiring |
| Workspace | `apps/workspace/` | Static prototype (F0 V2 approved); React/Next.js pending CTO review |
| Domain Packs | `domain_packs/` | content_commerce: 4 metrics (gmv, spend, roi, conversion_rate), SQL templates, seed data |
| Action Connectors | `action_connectors/` | manual_review (safe no-op default), action_record (reversible write + snapshot/rollback) |

## Remaining Items (Blocked on User Decisions/Environment)

- PR-07 Frontend F1 blueprint: pending CTO review
- ActionProposal routing to real write connector: pending product decision
- pgvector pushdown + HNSW: pending pgvector extension install
- OTel bridge: pending real collector target
- Stage 2 / Temporal / DataProduct Compiler v1: needs new ADR + CTO approval
