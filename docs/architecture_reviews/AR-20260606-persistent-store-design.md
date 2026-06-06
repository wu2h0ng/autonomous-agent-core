# AR-20260606 Persistent store design (in-memory → PostgreSQL)

> Status: **Proposed (design only — not implemented).** Prepared during review of
> `feat/pr0-governance-gate`; to be implemented after that PR merges. May be promoted to an
> ADR once the backend/tooling choices below are ratified.
> Scope: durable persistence for the loop's stateful stores. Out of scope: pgvector semantic
> search, multi-tenant RLS, full audit tables (staged later).

## 1. Problem

The Trusted Loop's stateful collaborators are all in-memory, so all state is lost on process
restart and is invisible across processes. This caps the product at exactly the capabilities that
are supposed to be the moat:

| Store | Today | Consequence of being in-memory |
|---|---|---|
| `FeedbackStore` (`feedback/`) | dict keyed by trace_id | feedback observed later (another process/session) cannot attach to a prior run |
| `KnowledgeStore` (`knowledge_memory/`) | dict keyed by source_trace_id + version map | no durable, accumulating **enterprise knowledge asset** — the core long-term value |
| `SnapshotStore` (`snapshot_store/`, ABC + `InMemorySnapshotStore`) | dict keyed by snapshot_id | L3 rollback only possible within the same process; a snapshot can't be rolled back after restart |
| `ApprovalLiteRuntime` (`approval_lite/`, `_records` dict) | dict keyed by approval_id | a pending approval created now cannot be approved later by another process — breaks async "propose now / approve later" |

Concretely, three product promises currently work only within a single process lifetime:
**(a)** Feedback → KnowledgeAsset learning across sessions; **(b)** durable rollback; **(c)** the
governance gate's human-responsibility entry point (approve a halted R4/R5 operation later).

Persistence is the prerequisite for all three. The CLI already documents this limitation
(`record-outcome` can't find a prior CLI run's trace); the FastAPI server only holds state for its
lifetime.

## 2. Guiding constraints (from existing architecture)

- **OS Core boundary**: `packages/os_core/` must not import infra drivers (psycopg/SQLAlchemy), the
  same way it must not import `domain_packs`/`providers`/`action_connectors`. OS Core owns the
  **Port** (abstraction); concrete DB adapters live outside it.
- **Tech stack** (MEMORY §4): PostgreSQL + JSONB + pgvector. Use JSONB to store the frozen-dataclass
  contracts with a few promoted, indexed columns for lookup keys.
- **Established DI pattern**: mirror `query_executor` (`static|sqlite`) — select the store backend by
  config (`memory|postgres`); keep in-memory as the default for fast, DB-less unit tests.
- **Contracts are the serialization source of truth**: `FeedbackEvent`, `KnowledgeAsset`,
  `StateSnapshot`, `ApprovalRecord` are frozen dataclasses — round-trip (de)serialization must be exact.

## 3. Design

### 3.1 Ports (in OS Core)

`SnapshotStore` is already an ABC. Promote the other three to ABCs with the same method surface they
expose today, so the runtime depends only on the Port:

- `FeedbackStorePort`: `record(event)`, `get_by_trace(trace_id)`, `all_events()`, `outcome_counts()`
- `KnowledgeStorePort`: `register(asset)` (dedup on source_trace_id), `register_version(asset)`,
  `get_by_trace(trace_id)`, `version_of(trace_id)`, `all_assets()`
- `ApprovalStorePort`: `create_pending(...)`, `approve(id)`, `reject(id)`, `get(id)`
  (refactor `ApprovalLiteRuntime` to depend on this port; lifecycle logic stays, storage moves behind it)
- `SnapshotStore` (exists): `save`, `get`, `list_for_operation`

The current in-memory classes become the `InMemory*` implementations of these ports (no behavior
change; existing tests stay green).

### 3.2 Adapters (outside OS Core)

A new package, e.g. `packages/persistence/` (`agent_os_persistence`) — NOT in os_core — provides
`Postgres*` implementations of each port. OS Core never imports it; the composition layer
(`apps/api_server/runtime_factory`) wires the chosen backend, exactly like connectors today.

### 3.3 Schema (PostgreSQL + JSONB)

One table per store; payload in JSONB, lookup keys promoted to indexed columns:

| Table | Indexed columns | JSONB payload |
|---|---|---|
| `feedback_events` | feedback_id (pk), trace_id (idx) | full FeedbackEvent |
| `knowledge_assets` | source_trace_id (pk/unique), version (int) | full KnowledgeAsset |
| `state_snapshots` | snapshot_id (pk), operation_id (idx) | full StateSnapshot |
| `approval_records` | approval_id (pk), proposal_id (idx), status | full ApprovalRecord |

Semantics mapping:
- `KnowledgeStore.register` → `INSERT ... ON CONFLICT (source_trace_id) DO NOTHING` (dedup).
- `KnowledgeStore.register_version` → upsert that overwrites payload and increments `version`.
- `SnapshotStore.list_for_operation` → `SELECT ... WHERE operation_id = $1`.

### 3.4 Serialization

Add a small, explicit mapper per contract (dataclass ⇄ dict) rather than reflective magic, so schema
evolution is visible and testable. `metrics`/`state_payload`/`details` are already dict/tuple and map
to JSON naturally (tuples → arrays on write, arrays → tuples on read to preserve frozen-dataclass types).

### 3.5 Transactions (consistency)

`record_outcome()` currently calls `feedback_store.record()` then `knowledge_store.register_version()`
as two independent steps. Against a DB these must be **one transaction** (a unit-of-work) so the
feedback and its superseding knowledge version commit atomically. Introduce a minimal
`UnitOfWork`/transaction context owned by the adapter layer; the in-memory backend implements it as a
no-op. The runtime calls `record_outcome` within the unit of work.

## 4. Rollout plan (phased, each phase shippable)

1. **Ports + refactor (no DB):** add the three ABCs, make `ApprovalLiteRuntime` use a port, confirm
   in-memory implementations satisfy them. Pure refactor; existing 220 tests stay green.
2. **PG adapter:** `packages/persistence/` with schema, migrations, mappers, `Postgres*` stores.
3. **Config wiring:** `RuntimeFactoryConfig.store_backend = "memory"|"postgres"` (mirror executor).
4. **Unit of work:** transactional `record_outcome`.
5. **Integration tests:** against a real Postgres (testcontainers or a CI service), guarded by
   `skipUnless` so the canonical bare-env `make ci` stays green (same pattern as the FastAPI tests).

## 5. Open decisions to ratify (before/at implementation)

- **DB access**: raw SQL via `psycopg` vs SQLAlchemy Core. (Lean: psycopg + hand-written SQL — fewer
  deps, matches the "self-developed core, thin infra" posture; revisit if query complexity grows.)
- **Migrations**: hand-rolled SQL migration files + a tiny runner vs Alembic.
- **Adapter location**: `packages/persistence/` vs under `apps/`. (Lean: `packages/persistence/` so
  the SDK/other apps can reuse it.)
- **Sync vs async**: the runtime is synchronous; start with sync psycopg. Async only if/when the
  FastAPI surface needs it.

## 6. Boundary & verification (for the implementation PR)

- **Boundary check**: `grep` proves `os_core` imports neither psycopg nor the persistence package; the
  factory is the only wiring point.
- **Verification**: contract round-trip equality (serialize → store → load → `==`); dedup/version
  semantics preserved **across a fresh store instance** pointed at the same DB (simulated restart);
  rollback works after a new `SnapshotStore` instance loads the snapshot; an approval created by one
  store instance is approved by a separate instance; transactional `record_outcome` rolls back both
  writes on failure.

## 7. Risks

- Serialization drift vs frozen dataclasses → mitigated by explicit mappers + round-trip tests.
- PG test infra could break bare-env CI → mitigated by optional/guarded integration tests.
- Transaction boundary correctness in `record_outcome` → covered by a failure-injection test.
