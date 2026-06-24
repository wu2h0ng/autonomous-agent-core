# AGENTS.md — ai-native-business-data-agent-os

> Last updated: 2026-06-24
> Role in workspace: **Deployment Layer** (enterprise OS, future downgrade projection of `autonomous-agent-core/`)
> Current next decision: merge/push/release authorization remains pending after reconciling ADR-0003 Agent Runtime v0 trusted substrate with ADR-0002 governed-action outcome-loop v0 and adding a static Frontend Workspace F1 contract surface for DataProduct/KnowledgeAsset candidate visibility. The Stage 1 Status below is historical context — trust `docs/CURRENT_STATE.yaml` for live state.

## Scope

These rules apply to code under `ai-native-business-data-agent-os/`.

For the three-repo role map, see the baseline workspace `.agent` file and `docs/research/RR-0004-artifact-map.md`.

## Stage 1 Status (Complete — 2026-06-11)

PR-01 through PR-06 all merged to `main` (commit `9d2d8d6`). P5 substrate harvest is underway: latest local workspace-F1 verification is 445 tests OK in the primary unittest discover run, 4 skipped, 12 eval subset tests OK, CI dependency preflight clean, OpenAPI contract clean, ruff clean, and format clean; the most recent full local PostgreSQL parity runs remain recorded in `docs/decisions/ADR-0002-governed-action-outcome-loop-v0.VERIFICATION-20260624.md` and `docs/decisions/ADR-0002-connector-execution-audit-contract-v0.VERIFICATION-20260624.md`.

Delivered runtime capabilities: Trusted Loop (full chain), persistence (SQLAlchemy Core + Alembic, 6 OS Core store ports plus the action_record connector ledger and report snapshot table), knowledge retrieval (hybrid scoring + pgvector-ready), observability (RunTrace + trace store + audit surface), typed API/OpenAPI contract surface, unified block contract, SQL Safety hardening, grounding invariant (P5.1b-ii), critical fix hygiene for SQL LIMIT lower bound / CLI env-store parity / knowledge-index atomicity, eval hub, 12-factor env wiring, action governance (state machine + snapshot/rollback), approval-bound action-record intent routing, operator-only approval execution (`X-Operator-Key`, no run-key execution, exact approval context binding, durable postgres-backed approval-context resume, claim/release double-consume guard, stale executing-claim lease recovery, retry after connector dry-run failure, OpenAPI required header contract with runtime 401 behavior preserved), connector-side action_record durable ledger (records, idempotency replay/conflict checks, replay/conflict/ACK-uncertain audit counters, conflict/uncertain fingerprints without raw payloads, restart-safe rollback that preserves later unrelated records), typed connector execution-audit projection (safe connector-reported fields only; no external ACK inference) plus connector-declared execution semantics (`ConnectorExecutionSemantics` defaults on `ActionConnectorContract`), typed user-facing data-agent result artifact with chart-ready dashboard widgets, strongly typed evidence/source report cards, audience-aware read-side redaction with a minimal HTTP principal/scope policy contract for `/runs`, report-read snapshots (same-process on memory; durable across fresh app/runtime instances on postgres), and management surfaces, P5.2a corrigibility pause shell (operator shell + runtime view + hash-chain audit + PAUSED refusal).

Engineering verification gates: selected-`PYTHON` dependency preflight plus OpenAPI snapshot drift gate in `make ci`, observability gate tests for required trace steps/telemetry dimensions, ruff, format check, unittest discovery, eval subset, and `ci-local-full` PostgreSQL parity.

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
| Contracts | `packages/contracts/` | BusinessIntent, MetricContract, EvidenceChain, ActionProposal, OperationContract, KnowledgeAsset, RunTrace, BlockCode, ConnectorExecutionAudit, ConnectorExecutionSemantics, etc. |
| OS Core | `packages/os_core/` | Trusted Loop, Intent Parser, Semantic Runtime, Data Access Plane, Data Product Compiler, SQL Safety, Query Runtime, EvidenceChain, ActionProposal, Action Governance, Approval Lite, Operation Trace, Feedback, Knowledge Memory, Snapshot Store, Trace/Telemetry, Eval Hub, Agent Runtime shell, Model Gateway, Embedding, Knowledge Retrieval |
| Persistence | `packages/persistence/` | SQLAlchemy Core sync adapters for all 6 OS Core store ports + action_record connector ledger + report snapshots + Alembic migrations (0001–0008) |
| API Server | `apps/api_server/` | FastAPI app + typed OpenAPI contract snapshot + CLI (query, record-outcome, trace, search) + 12-factor env wiring + typed `user_result` artifact in `/runs`, side-effect-free `GET /runs/{trace_id}/report` read projection (memory same-process, postgres durable), evidence/source report cards, chart-ready dashboard, audience-aware read-side redaction, minimal principal/scope policy contract, and operator-only approval execution at `/approvals/{approval_id}/execute` with typed `execution_audit` |
| Workspace | `apps/workspace/` | Static prototype with F1 contract surface for EvidenceChain, DataProduct candidate, ActionProposal, feedback, KnowledgeAsset candidate, trace, and mock loaded/blocked/insufficient states; blocked/insufficient states replace stale candidate fields; React/Next.js and live API integration pending CTO review |
| Domain Packs | `domain_packs/` | content_commerce: 4 metrics (gmv, spend, roi, conversion_rate), SQL templates, seed data |
| Action Connectors | `action_connectors/` | manual_review (safe no-op default), action_record (reversible write + snapshot/rollback) |

## Remaining Items (Blocked on User Decisions/Environment)

- PR-07 Frontend live API/React scaffold: pending CTO review
- pgvector pushdown + HNSW: pending pgvector extension install
- OTel bridge: pending real collector target
- Stage 2 / Temporal / DataProduct Compiler v1: needs new ADR + CTO approval
