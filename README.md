# AI Native Business Data Agent OS

> Independent product implementation — the **deployment layer** of the three-repo project.  
> Future role: downgrade projection of the general autonomous core (`autonomous-agent-core/`)  
> with `autonomy→0` + business domain pack + strong evidence governance.  
> Git: branch `main`, remote `origin` at `git@github.com:wu2h0ng/data-agent-os.git`.

## Current State

Read `docs/CURRENT_STATE.yaml` first. It is the live handoff anchor for the enterprise deployment layer: branch, stage, test status, current P5 scope, blocked decisions, and source-of-truth records.

**Current implementation slice (2026-06-23):** **ADR-0002 — governed-action outcome-loop v0** is **Accepted**. Lower-half contracts are implemented (causal attribution/result_weight, ActionRecord dry-run/idempotency, contract/OpenAPI wiring), and the scoped upper-half is pushed on `main`: CLI `adopt`, approval-resume governed execution, approval-bound operation/action/evidence checks, D6 red eval, and one rollback demonstration. This remains pending release authorization and does not add automatic R4/R5 execution. See `docs/decisions/ADR-0002-governed-action-outcome-loop-v0.md`.

## Project Position (2026-06-12 repositioning)

This repository is one of three sibling repos in the workspace:

| Repository | Role |
|---|---|
| `autonomous-agent-core/` | **Primary artifact** — general autonomous agent prototype (object layer) |
| `ai-native-business-data-agent-os/` | **Deployment layer** — enterprise OS, future downgrade projection of the general core |
| `ai-agent-engineering-workflow/` | **Meta layer** — dev-process governance tooling |

This repo is the **product implementation root** for the enterprise Business Data Agent OS. FaSoLa is only Customer-0, Reference Domain Pack, and Connector source material. OS Core must not import FaSoLa monorepo modules or content-commerce-specific logic.

## Stage 1 Status (Complete — 2026-06-11)

Stage 1 (Trusted Business Loop MVP) engineering is **complete**. All PR-01 through PR-06 merged to `main`. P5 substrate harvest is underway; latest local verification is 353 unit tests OK, 4 skipped, and 12 eval tests OK, with OpenAPI contract tests executing under installed FastAPI/httpx dependencies.

### Delivered Capabilities

**Trusted Loop** (full chain):
```text
BusinessIntent → SemanticObject → MetricContract → ProviderContract
→ DataProduct candidate → SQL Safety → QueryResult → EvidenceChain
→ ActionProposal → Approval/OperationTrace → Feedback → KnowledgeAsset candidate
```

**Persistence** (SQLAlchemy Core + Alembic):
- FeedbackStore, KnowledgeStore, SnapshotStore, ApprovalStore — all Port-based
- Postgres JSONB + pgvector-ready migrations (0001–0005)
- In-memory default for tests; Postgres via env var

**Knowledge Retrieval** (hybrid scoring):
- Embedder / KnowledgeRetriever ports in OS Core
- InMemoryKnowledgeRetriever + SqlKnowledgeRetriever (SQL index-column filtering, not JSON scan)
- HybridScorer: vector + lexical RRF + outcome/recency weighted tiebreaker
- `run()` recalls related_knowledge (advisory, trace-visible)
- `GET /knowledge/search` (API key boundary, 503 when no retriever)
- uow-transactional re-embed on record_outcome

**Observability** (RunTrace):
- TraceStorePort (InMemory default / SqlTraceStore + Alembic 0005)
- `run()` dual-exit persistence (answers AND refusals equally auditable)
- `GET /traces/{trace_id}` audit surface + CLI `trace` subcommand
- Observability gate test (required trace steps and telemetry dimensions)

**API Contract** (OpenAPI snapshot gate):
- `apps/api_server/openapi.json` = typed API contract
- Drift-gated by unit test + CI `--check` step
- 422 block contract declared in schema
- `POST /runs`, `POST /outcomes`, `GET /knowledge/search`, `GET /traces/{id}`

**SQL Safety**: SELECT-star hardening (distinct/all/qualified), schema allowlist, forbidden SQL, limit policy

**Eval Hub**: EvalThresholdReporter with golden-loop dimension checks

**Action Governance**: OperationState machine, snapshot/rollback, approval-required guard

**Corrigibility Pause Shell (P5.2a)**: operator-held `CorrigibilityShell`, runtime-held read-only `ShellView`, hash-chain audit, and `BlockCode.PAUSED` refusal path

**Grounding Invariant (P5.1b-ii)**: formal answers/proposals/executions cannot bypass SQL Safety plus a complete `EvidenceChain`; violations raise `GroundingInvariantViolation`

**Critical Fix Hygiene (2026-06-15)**: SQL Safety rejects non-positive LIMIT values, CLI query/outcome uses the same 12-factor store wiring as HTTP, and durable knowledge writes keep canonical assets, retrieval index rows, and version bumps transactionally consistent

**12-Factor Env Wiring**: `RuntimeFactoryConfig.from_env()` — switch backends via environment variables

### Unified Block Contract

`BlockCode` / `TrustedLoopBlock` / `TrustedLoopOutcome` / `TrustedLoopBlocked`:
distinguishes "expected business block" from "wiring error". `evaluate()` returns unified outcome without throwing.

## Layout

```text
packages/os_core/       self-developed OS Core and Agent Runtime
packages/contracts/     public contracts and shared data objects
packages/persistence/   SQLAlchemy Core adapters (sync, Port-based)
packages/sdk/           external SDK boundary
apps/api_server/        FastAPI application + OpenAPI contract + CLI
apps/workspace/         future user workspace UI
domain_packs/           domain-specific packs (content_commerce)
providers/              data providers behind ProviderContract
action_connectors/      governed action connectors (manual_review, action_record)
examples/               Customer-0 and integration examples
tests/                  unit, integration, eval, smoke
docs/                   architecture reviews, decisions, scope
scripts/                agent runner scripts
```

## Commands

```bash
# Install local development dependencies used by CI.
make bootstrap-dev

# Fast local suite: lint, format, unit, and eval.
make ci

# Full local CI parity: also requires Postgres-backed integration tests and
# the OpenAPI contract drift gate. Use a disposable test database; this
# does not publish, release, or push anything.
export AGENT_OS_DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/agent_os_test"
make ci-local-full

# Or directly:
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  python -m unittest discover -s tests -v

# CLI query
python -m agent_os_api.cli --question "GMV" --start-date 2026-05-25 --end-date 2026-06-01

# CLI trace
python -m agent_os_api.cli trace <trace_id>

# CLI search
python -m agent_os_api.cli search --query "ROI decline"

# OpenAPI contract check
python -m agent_os_api.openapi_contract --check
```

## Remaining Items (Blocked on Decisions/Environment)

- PR-07 Frontend F1 blueprint: pending CTO review
- ActionProposal routing to real write connector: pending product decision
- pgvector pushdown + HNSW: pending pgvector extension install
- OTel bridge: pending real collector target
- Stage 2 / Temporal / DataProduct Compiler v1: needs new ADR + CTO approval

## Core Rule

Agent OS Core and Agent Runtime are self-developed. Open-source Agent frameworks may be studied as references only and must not become product Core runtime dependencies.
