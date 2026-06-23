# AI Native Business Data Agent OS

> Independent product implementation — the **deployment layer** of the three-repo project.  
> Future role: downgrade projection of the general autonomous core (`autonomous-agent-core/`)  
> with `autonomy→0` + business domain pack + strong evidence governance.  
> Git: canonical branch `main`, remote `origin` at `git@github.com:wu2h0ng/data-agent-os.git`; read `docs/CURRENT_STATE.yaml` for the active local branch and gate status.

## Current State

Read `docs/CURRENT_STATE.yaml` first. It is the live handoff anchor for the enterprise deployment layer: branch, stage, test status, current P5 scope, blocked decisions, and source-of-truth records.

**Current feature-branch implementation slice (2026-06-24):** **ADR-0003 — Agent Runtime v0 Trusted Substrate** is accepted and implemented on branch `codex/agent-runtime-v0-trusted-substrate`. Pre-merge review at `58f3a5f` blocked merge on H1-H3; those blockers are now remediated locally, but the branch still requires a second review gate before merging to `main`. It turns the self-developed `agent_runtime` shell into a narrow trusted substrate: typed run/tool/result/policy contracts, pre-execution `RuntimePolicyGate`, validation-before-tool-body, trace-visible failure paths with safe runtime trace projection, pause-shell denial through `ShellView`, minimal checkpoint/replay boundary, `TrustedLoopRuntime.evaluate()` adapter, and import-boundary tests blocking external agent-framework runtime dependencies. The remediation closes the `run_tool()` policy bypass, requires `approval_id` for R4/R5 and side-effecting tools, and removes raw args/output from runtime trace events. This does not replace `TrustedLoopRuntime`, does not expose a workflow engine, does not approve automatic R4/R5 execution, and does not claim autonomous-core evidence. See `docs/decisions/ADR-0003-agent-runtime-v0-trusted-substrate.md`, `docs/decisions/ADR-0003-agent-runtime-v0-trusted-substrate.REVIEW-20260624.md`, and `docs/decisions/ADR-0003-agent-runtime-v0-trusted-substrate.CODEX-REMEDIATION-20260624.md`.

**Current implementation slice (2026-06-24):** **ADR-0002 — governed-action outcome-loop v0** is **Accepted**, merged to `main`, and pushed to `origin/main`. Lower-half contracts are implemented (causal attribution/result_weight, ActionRecord dry-run/idempotency, contract/OpenAPI wiring), and the scoped upper-half is implemented locally: CLI `adopt`, approval-resume governed execution, approval-bound operation/action/evidence checks, D6 red eval, and rollback demonstration. Explicit grounded follow-up/action-record user intent now routes to the reversible `action_record` connector and remains approval-bound until approval-resume execution. `POST /runs` / `run_service` return a typed `user_result` artifact for direct data-agent clients: evidence-bound analysis, report sections, strongly typed evidence/source cards, chart-ready dashboard widgets, audience-aware read-side redaction, decision recommendation, and approval-bound business-action metadata. Dashboard chart fields are derived from MetricContract dimensions plus grounded query rows, and non-chartable rows do not fabricate a chart. Report evidence cards are discriminated `metric_contract` / `sql_safety` / `query_result` cards derived from MetricContract, QueryPlan, SQLSafetyResult, and QueryResult metadata; internal projections include SQL fingerprints and parameter names, but never raw SQL or parameter values. `POST /runs` accepts `audience=internal|external`; external non-public projections hide physical sources, metric dimensions, SQL metadata, columns, preview rows, chart fields, and KPI values while preserving row counts and explicit redaction metadata; external public projections may show public metric data but still hide physical schemas/tables, bound parameter names, limit metadata, and SQL fingerprints. The HTTP auth layer now has a minimal tested `ApiPrincipal`/scope matrix: `internal` can run internal/external projections plus outcome/adoption/search/trace surfaces, `external_report` can only run external projections through `POST /runs`, and `operator` can only execute approvals through `X-Operator-Key`; missing/wrong keys return 401, recognized principals without scope return 403, unconfigured auth returns 503, and configured key values must be distinct. This is not full RBAC, tenant isolation, field/row-level authorization, full DLP, or a production external release. `POST /approvals/{approval_id}/execute` is operator-key-only, executes the exact approval-bound context, returns a typed `ConnectorExecutionAudit` / OpenAPI `ApprovalExecutionAudit` projection, and rejects run API keys, rejected approvals, unknown/replayed approvals, and R4/R5 automatic execution; connector contracts now declare `ConnectorExecutionSemantics` so runtime audit defaults come from the registered connector contract, while connector payloads may only add whitelisted safe fields such as external request id, record id, and ACK status. The postgres store backend now persists both approval-bound operation/evidence/action context in `approval_operation_contexts` and the `action_record` connector's side-effect ledger in `action_records`; later runtime instances can execute by `approval_id` without client replay, recover stale executing approval-context claims after the configured lease, reject double stale-reclaim wins via observed claim-token CAS, observe prior connector records, replay same-idempotency operations without double append, audit replay/conflict counts plus conflict fingerprints without raw conflicting payloads, audit connector-local post-write ACK-uncertain attempts without raw audit parameters, recover those local ledger writes through idempotent replay without double append, and roll back one action without deleting later unrelated records. This still does not claim external release, external-system exactly-once, external ACK confirmation, durable arbitrary external connector recovery, or automatic R4/R5 execution. See `docs/decisions/ADR-0002-governed-action-outcome-loop-v0.md`.

## Project Position (2026-06-12 repositioning)

This repository is one of three sibling repos in the workspace:

| Repository | Role |
|---|---|
| `autonomous-agent-core/` | **Primary artifact** — general autonomous agent prototype (object layer) |
| `ai-native-business-data-agent-os/` | **Deployment layer** — enterprise OS, future downgrade projection of the general core |
| `ai-agent-engineering-workflow/` | **Meta layer** — dev-process governance tooling |

This repo is the **product implementation root** for the enterprise Business Data Agent OS. FaSoLa is only Customer-0, Reference Domain Pack, and Connector source material. OS Core must not import FaSoLa monorepo modules or content-commerce-specific logic.

## Stage 1 Status (Complete — 2026-06-11)

Stage 1 (Trusted Business Loop MVP) engineering is **complete**. All PR-01 through PR-06 merged to `main`. P5 substrate harvest is underway; latest ADR-0003 feature-branch verification after syncing current `main` is 429 tests OK in the primary unittest discover run, 4 skipped, and 12 eval subset tests OK, with OpenAPI contract drift check included in `make ci`; `ci-local-full` also passed against a disposable local PostgreSQL test container.

### Delivered Capabilities

**Trusted Loop** (full chain):
```text
BusinessIntent → SemanticObject → MetricContract → ProviderContract
→ DataProduct candidate → SQL Safety → QueryResult → EvidenceChain
→ ActionProposal → Approval/OperationTrace → Feedback → KnowledgeAsset candidate
```

**Persistence** (SQLAlchemy Core + Alembic):
- FeedbackStore, KnowledgeStore, SnapshotStore, ApprovalStore, ApprovalContextStore, TraceStore — all Port-based
- action_record connector-side durable ledger (`SqlActionRecordStore`) for records, idempotency replay/conflict checks, replay/conflict/ACK-uncertain audit counters, conflict and uncertain-execution fingerprints without raw audit payloads, and restart-safe rollback
- Postgres JSONB + pgvector-ready migrations (0001–0007)
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
- Runtime trace events include required governance steps and telemetry dimensions

**API Contract / HTTP Surface**:
- `apps/api_server/openapi.json` = typed API contract
- 422 block contract declared in schema
- `POST /runs`, `POST /outcomes`, `GET /knowledge/search`, `GET /traces/{id}`
- `POST /runs` returns typed `user_result` for direct client rendering: analysis, report with strongly typed evidence/source cards, chart-ready dashboard, audience-aware read-side redaction, decision, and approval-bound business action; the minimal HTTP principal/scope contract caps `external_report` to external projection and blocks non-run management surfaces with 403
- `POST /approvals/{approval_id}/execute` is operator-only (`X-Operator-Key`), advertises `X-Operator-Key` as a required string in OpenAPI while preserving runtime 401 for missing/wrong keys, executes only the original approval-bound context, can resume that context and the action_record ledger across runtime instances on the postgres backend, returns typed 404/409 error shapes plus a typed `execution_audit` projection derived from connector-declared `ConnectorExecutionSemantics` plus whitelisted connector-reported fields, records connector-local ACK-uncertain recovery through idempotent replay, and keeps R4/R5 proposal-only in MVP

**SQL Safety**: SELECT-star hardening (distinct/all/qualified), schema allowlist, forbidden SQL, limit policy

**Eval Hub**: EvalThresholdReporter with golden-loop dimension checks

**Action Governance**: OperationState machine, snapshot/rollback, approval-required guard

**Corrigibility Pause Shell (P5.2a)**: operator-held `CorrigibilityShell`, runtime-held read-only `ShellView`, hash-chain audit, and `BlockCode.PAUSED` refusal path

**Grounding Invariant (P5.1b-ii)**: formal answers/proposals/executions cannot bypass SQL Safety plus a complete `EvidenceChain`; violations raise `GroundingInvariantViolation`

**Agent Runtime v0 Trusted Substrate (ADR-0003)**: self-developed runtime envelope with typed tool calls/results, mandatory policy gate, fail-closed R4/R5 and side-effect approval checks, pause denial, validation-before-tool-body, safe runtime trace projection without raw args/output, minimal checkpoint/replay boundary, Trusted Loop adapter, and import-boundary tests against LangGraph/CrewAI/LangChain/OpenAI Agents runtime dependencies

**Critical Fix Hygiene (2026-06-15)**: SQL Safety rejects non-positive LIMIT values, CLI query/outcome uses the same 12-factor store wiring as HTTP, and durable knowledge writes keep canonical assets, retrieval index rows, and version bumps transactionally consistent

**12-Factor Env Wiring**: `RuntimeFactoryConfig.from_env()` — switch backends via environment variables

### Unified Block Contract

`BlockCode` / `TrustedLoopBlock` / `TrustedLoopOutcome` / `TrustedLoopBlocked`:
distinguishes "expected business block" from "wiring error". `evaluate()` returns unified outcome without throwing.

### Engineering Verification Gates

- OpenAPI snapshot drift gate is enforced by unit test and CI `--check`.
- Observability gate tests verify required trace steps and telemetry dimensions.
- `make ci` runs ruff, format check, unittest discovery, eval subset, and OpenAPI drift check.
- `ci-local-full` covers the disposable PostgreSQL parity path.

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

# Fast local suite: lint, format, unit, eval, and OpenAPI contract drift check.
make ci

# Full local CI parity: also checks the local dev environment and requires a
# disposable database URL for Postgres-backed integration tests. OpenAPI drift is already
# included in make ci. This does not publish, release, or push anything.
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
- pgvector pushdown + HNSW: pending pgvector extension install
- OTel bridge: pending real collector target
- Stage 2 / Temporal / DataProduct Compiler v1: needs new ADR + CTO approval

## Core Rule

Agent OS Core and Agent Runtime are self-developed. Open-source Agent frameworks may be studied as references only and must not become product Core runtime dependencies.
