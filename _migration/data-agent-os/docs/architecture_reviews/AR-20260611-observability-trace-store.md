# AR-20260611: Observability v1 — queryable run traces, auditable blocks, telemetry gate

- **Status**: Accepted
- **Date**: 2026-06-11
- **Scope**: PR-06 (Observability Gate) first real slice
- **Related**: AR-20260606-unified-block-outcome (blocks become auditable),
  AR-20260611-api-contract-openapi-stabilization (snapshot regenerated here)

## Problem

1. **Run traces are not queryable after the fact.** `TraceRecorder` collects trace +
   telemetry events, but they only live on the returned `TrustedLoopResult`. There is no
   way to audit a past run by `trace_id` — yet `record_outcome` and approvals reference
   runs by `trace_id` hours or days later. "Evidence-backed and traceable" currently
   means "traceable if you kept the in-process return value".
2. **Blocked runs lose their trace entirely.** `run()` raises `TrustedLoopBlocked`
   before any result exists, discarding everything recorded up to the block. Refusals
   are exactly the runs an auditor most wants to inspect.
3. **No gate guarantees observability coverage.** Nothing fails if a loop stage stops
   emitting its trace step or telemetry dimension.

## Decision

### 1. `TraceStorePort` (OS Core) + persisted run traces

- New contract `RunTrace` (`trace_id`, `status: "ok" | "blocked"`, `events`,
  `telemetry_events`). New OS Core port `TraceStorePort`
  (`save(run_trace)` / `get(trace_id) -> RunTrace | None`) with `InMemoryTraceStore`
  as the default — every runtime persists traces out of the box.
- `run()` persists the trace on BOTH exits: on success (`status="ok"`) and on a
  business block (`status="blocked"`, with a final `blocked` trace step recording
  code/stage/message) before re-raising. Programming errors still propagate unpersisted
  — they are bugs, not auditable outcomes.
- Persistence adapter `SqlTraceStore` (`run_traces` table, JSON payloads, keyed by
  unique `trace_id`) + Alembic `0005_run_traces`; factory wires it for the postgres
  backend (the migrations-cover-schema guard enforces the migration's presence).

### 2. Blocks carry their trace_id

`TrustedLoopBlock.trace_id` (new optional contract field) is populated by `run()`, so
`evaluate()`, the CLI, and HTTP 422 responses reference the persisted trace of the
refusal — closing the audit chain for the negative path.

### 3. Trace query surface

`GET /traces/{trace_id}` (same `X-API-Key` boundary) returns the persisted `RunTrace`
or 404. Framework-agnostic `trace_service` in `outcome_service.py`. OpenAPI snapshot
regenerated in the same PR.

### 4. Observability gate (test-enforced)

A gate test pins the REQUIRED trace steps of a successful run (intent,
semantic_resolution, knowledge_recall*, query_plan, sql_safety, query_result,
data_product_candidate, evidence_chain, action_proposal, operation_contract,
knowledge_asset_candidate — *recall only when a retriever is wired) and requires all
three telemetry dimensions (business/quality/system). Removing a stage's emission turns
CI red. Blocked runs must persist `status="blocked"` with the `blocked` step.

## Non-goals (later slices)

- OTel span/metric bridge (`[observability]` extra exists; bridge when an OTel collector
  target is real). Retention/compaction policy. Multi-tenant trace ACLs.

## Boundaries

- OS Core: `RunTrace`/`TraceStorePort`/`InMemoryTraceStore` are pure; no new deps.
- Composition layer wires `SqlTraceStore`; OS Core never imports persistence.

## Completion gate mapping

- **Entry point**: `GET /traces/{trace_id}`; every `run()` writes through the port.
- **Contract**: `RunTrace`, `TrustedLoopBlock.trace_id`; regenerated `openapi.json`;
  `run_traces` schema + migration 0005.
- **Negative paths**: blocked runs persist with `status="blocked"` + carry trace_id to
  the 422 response; unknown trace_id → 404.
- **Bypass-detection**: gate test fails if any required stage stops emitting; round-trip
  tests fail if persistence is bypassed; migrations-cover-schema guards 0005.
