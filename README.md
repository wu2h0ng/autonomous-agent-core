# AI Native Business Data Agent OS

> Primary enterprise OS product implementation — the **deployment layer** of the three-repo project.
> It turns business intent into trusted data products, evidence-backed decisions,
> governed actions, and feedback learning under explicit risk gates.
> Git: canonical branch `main`, remote `origin` at `git@github.com:wu2h0ng/data-agent-os.git`; read `docs/CURRENT_STATE.yaml` for the active local branch and gate status.

## Current State

Read `docs/CURRENT_STATE.yaml` first. It is the live handoff anchor for the enterprise deployment layer: branch, stage, test status, current P5 scope, blocked decisions, and source-of-truth records.

**Current runtime implementation slice (2026-06-27):** **ADR-0003 — Agent Runtime v0 Trusted Substrate** is accepted and on deployment local `main` after the reviewed runtime stack was fast-forward merged in order: reviewed-slices consolidation, checkpoint-factory selection, then budget guard, followed by report-read/workspace landing and the founder/CTO-authorized correction-channel merge. The self-developed `agent_runtime` shell now has typed run/tool/result/policy contracts, pre-execution `RuntimePolicyGate`, validation-before-tool-body, context-level tool risk ceiling, R4/R5 proposal-only enforcement, trace-visible failure paths with safe runtime trace projection, pause-shell denial through `ShellView`, minimal checkpoint/replay boundary with fingerprint-bound resume, durable checkpoint-store port/adapter, `TrustedLoopRuntime.evaluate()` adapter with fake-loop and real-loop integration coverage, and import-boundary tests blocking external agent-framework runtime dependencies. `POST /outcomes` and `POST /adoptions` now traverse local-main correction-channel runtime-envelope wiring: request-scoped `AgentRunContext`/`AgentTraceWriter`, narrow `trusted_loop.record_outcome` and `trusted_loop.attest_adoption` tools, pause/missing-permission denial before writes, safe `agent_runtime.*` trace projection, factory-selected checkpoint-store injection, explicit preserve-result-on-checkpoint-failure for completed correction writes, and checkpoint replay mismatch coverage so self-report feedback cannot replay as realized adoption. The adoption writer remains in the API composition/operator layer; neither `AgentRuntime` nor `TrustedLoopRuntime` owns it. This local main merge is not pushed and not an external release claim. This does not replace `TrustedLoopRuntime`, does not expose a workflow engine, does not implement wall-clock preemption, does not approve automatic R4/R5 execution, and does not claim autonomous-core evidence. See `docs/decisions/ADR-0003-agent-runtime-v0-trusted-substrate.md`, `docs/decisions/ADR-0003-agent-runtime-v0-trusted-substrate.REVIEW-20260624.md`, `docs/decisions/ADR-0003-agent-runtime-v0-trusted-substrate.CODEX-REMEDIATION-20260624.md`, `docs/decisions/ADR-0003-agent-runtime-v0-trusted-substrate.SECOND-REVIEW-20260624.md`, `docs/decisions/ADR-0003-agent-runtime-checkpoint-trace-security.REVIEW-20260625.md`, `docs/decisions/ADR-0003-agent-runtime-live-wiring.REVIEW-20260625.md`, `docs/decisions/ADR-0003-agent-runtime-diagnostics-boundary.IMPLEMENTATION-20260625.md`, `docs/decisions/ADR-0003-agent-runtime-success-trace-bridge.IMPLEMENTATION-20260626.md`, `docs/decisions/ADR-0003-agent-runtime-approval-execute-envelope.IMPLEMENTATION-20260626.md`, `docs/decisions/ADR-0003-agent-runtime-reviewed-slices-consolidation.REVIEW-20260626.md`, `docs/decisions/ADR-0003-agent-runtime-checkpoint-factory-selection.IMPLEMENTATION-20260626.md`, `docs/decisions/ADR-0003-agent-runtime-checkpoint-factory-selection.REVIEW-20260626.md`, `docs/decisions/ADR-0003-agent-runtime-budget-guard.IMPLEMENTATION-20260626.md`, `docs/decisions/ADR-0003-agent-runtime-budget-guard.REVIEW-20260626.md`, `docs/decisions/ADR-0003-agent-runtime-correction-channel-scope-20260626.md`, and `docs/decisions/ADR-0003-agent-runtime-correction-channel.POST-MERGE-VERIFY-20260627.md`.

**Local-main runtime follow-up (merged locally 2026-07-01):** `codex/agent-runtime-public-resume-api` was fast-forward merged into deployment local `main@31d8ea7` after founder authorization and post-merge verification. The merged slice adds an internal-only public resume surface for the existing checkpoint/replay boundary. Internal `POST /runs` responses carry a safe `runtime_checkpoint_ref` only when a matching checkpoint is actually persisted; external report-key projections receive `null`. `POST /agent-runtime/runs/{runtime_run_id}/resume` requires the new internal `runtime:resume` scope, verifies the original call/context/tool fingerprints before rerunning `RuntimePolicyGate`, appends safe resume trace events, declares typed `RuntimeResumeErrorResponse` schemas for 404/409/500/503 failures, and returns only a safe `RuntimeResumeResponse`/`output_ref` without raw args, raw SQL, raw tool output, connector payloads, or automatic Trusted Loop re-execution. A 2026-06-29 order fix keeps checkpoint mismatches visible as `CHECKPOINT_MISMATCH` even when the shell is paused, while matching paused resumes still fail with `DENY_PAUSED`. A 2026-06-30 hardening fixes checkpoint backend read failures so both the HTTP resume route and `AgentRuntime.resume_from_checkpoint(...)` return typed `CHECKPOINT_READ_FAILED` failures without DSNs, credentials, raw args, or plain-text 500 responses. The local-main merge was verified on 2026-07-01: `make ci` 505 OK / 4 skipped plus 12 eval OK, and PostgreSQL `ci-local-full` 505 OK plus 12 eval OK. This local main is not pushed or released. See `docs/decisions/ADR-0003-agent-runtime-public-resume-api.IMPLEMENTATION-20260627.md`, `docs/decisions/ADR-0003-agent-runtime-public-resume-api.REFRESH-VERIFY-20260629.md`, `docs/decisions/ADR-0003-agent-runtime-public-resume-api.RESUME-ORDER-FIX-20260629.md`, `docs/decisions/ADR-0003-agent-runtime-public-resume-api.CHECKPOINT-READ-FAILURE-FIX-20260630.md`, `docs/decisions/ADR-0003-agent-runtime-public-resume-api.FRESH-VERIFY-20260701.md`, and `docs/decisions/ADR-0003-agent-runtime-public-resume-api.POST-MERGE-VERIFY-20260701.md`.

**Branch-local governed-decision seam follow-up (rebased/reviewed 2026-07-02):** `feature/governance-decision-seam-2026-07-01` implements ADR-0004 / RR-0032 as an optional R0-R3 RPC boundary inside `TrustedLoopRuntime`: the OS builds and verifies candidate actions locally, then an injected governed-decision client may only tighten the proposal by denying or forcing approval. Default `None` preserves the Trusted Loop path. The branch includes a native versioned `1.1.0` seam contract, remote-client stub with injected transport, response validation for task/version/verdict/audit_ref, HTTP transport helper, never-block fallback wrapper, local reference client for tests, fail-closed unknown-verdict handling, safe reason projection, `governed_decision` trace events bound to OS `trace_id` / `evidence_chain_id`, and `BlockCode.GOVERNANCE_DENIED`. It does not import `autonomous-agent-core`, does not wire a deployed remote service, does not bypass SQL Safety/EvidenceChain/Approval/connectors, does not auto-execute R4/R5, and does not claim autonomous-core evidence as product validation. The branch was rebased onto deployment local `main@91ae01c`, independently reviewed/remediated, formatted, and verified on 2026-07-02: seam suite 29 OK; targeted seam/TrustedLoop/adapter suite 50 OK; `make ci` 534 OK / 4 skipped plus 12 eval OK; and PostgreSQL `ci-local-full` 534 OK / 4 skipped plus 12 eval OK. M3 merge-readiness is recorded, but the branch is not merged, not pushed after rebase, and not released. See `docs/decisions/ADR-0004-governed-decision-seam.md`, `docs/decisions/ADR-0004-governed-decision-seam.REVIEW-20260702.md`, and `docs/decisions/ADR-0004-governed-decision-seam.MERGE-READINESS-20260702.md`.

**Current implementation slice (2026-06-24):** **ADR-0002 — governed-action outcome-loop v0** is **Accepted**, merged to `main`, and pushed to `origin/main`. Lower-half contracts are implemented (causal attribution/result_weight, ActionRecord dry-run/idempotency, contract/OpenAPI wiring), and the scoped upper-half is implemented locally: CLI `adopt`, approval-resume governed execution, approval-bound operation/action/evidence checks, D6 red eval, and rollback demonstration. Explicit grounded follow-up/action-record user intent now routes to the reversible `action_record` connector and remains approval-bound until approval-resume execution. `POST /runs` / `run_service` return a typed `user_result` artifact for direct data-agent clients: evidence-bound analysis, report sections, strongly typed evidence/source cards, chart-ready dashboard widgets, audience-aware read-side redaction, decision recommendation, and approval-bound business-action metadata. Dashboard chart fields are derived from MetricContract dimensions plus grounded query rows, and non-chartable rows do not fabricate a chart. Report evidence cards are discriminated `metric_contract` / `sql_safety` / `query_result` cards derived from MetricContract, QueryPlan, SQLSafetyResult, and QueryResult metadata; internal projections include SQL fingerprints and parameter names, but never raw SQL or parameter values. `POST /runs` accepts `audience=internal|external`; external non-public projections hide physical sources, metric dimensions, SQL metadata, columns, preview rows, chart fields, and KPI values while preserving row counts and explicit redaction metadata; external public projections may show public metric data but still hide physical schemas/tables, bound parameter names, limit metadata, and SQL fingerprints. The HTTP auth layer now has a minimal tested `ApiPrincipal`/scope matrix: `internal` can run internal/external projections plus outcome/adoption/search/trace surfaces, `external_report` can only run external projections through `POST /runs`, and `operator` can only execute approvals through `X-Operator-Key`; missing/wrong keys return 401, recognized principals without scope return 403, unconfigured auth returns 503, and configured key values must be distinct. This is not full RBAC, tenant isolation, field/row-level authorization, full DLP, or a production external release. `POST /approvals/{approval_id}/execute` is operator-key-only, executes the exact approval-bound context, returns a typed `ConnectorExecutionAudit` / OpenAPI `ApprovalExecutionAudit` projection, and rejects run API keys, rejected approvals, unknown/replayed approvals, and R4/R5 automatic execution; connector contracts now declare `ConnectorExecutionSemantics` so runtime audit defaults come from the registered connector contract, while connector payloads may only add whitelisted safe fields such as external request id, record id, and ACK status. The postgres store backend now persists both approval-bound operation/evidence/action context in `approval_operation_contexts` and the `action_record` connector's side-effect ledger in `action_records`; later runtime instances can execute by `approval_id` without client replay, recover stale executing approval-context claims after the configured lease, reject double stale-reclaim wins via observed claim-token CAS, observe prior connector records, replay same-idempotency operations without double append, audit replay/conflict counts plus conflict fingerprints without raw conflicting payloads, audit connector-local post-write ACK-uncertain attempts without raw audit parameters, recover those local ledger writes through idempotent replay without double append, and roll back one action without deleting later unrelated records. This still does not claim external release, external-system exactly-once, external ACK confirmation, durable arbitrary external connector recovery, or automatic R4/R5 execution. See `docs/decisions/ADR-0002-governed-action-outcome-loop-v0.md`.

## Project Position (2026-06-12 repositioning)

This repository is one of three sibling repos in the workspace:

| Repository | Role |
|---|---|
| `autonomous-agent-core/` | Supplementary, currently parked object-layer research supply for stronger decision mechanisms |
| `ai-native-business-data-agent-os/` | **Primary product** — enterprise Business Data & Agentic Operations OS |
| `ai-agent-engineering-workflow/` | **Meta layer** — dev-process governance tooling |

This repo is the **product implementation root** for the enterprise Business Data Agent OS. FaSoLa is only Customer-0, Reference Domain Pack, and Connector source material. OS Core must not import FaSoLa monorepo modules or content-commerce-specific logic.

## Stage 1 Status (Complete — 2026-06-11)

Stage 1 (Trusted Business Loop MVP) engineering is **complete**. All PR-01 through PR-06 merged to `main`. P5 substrate harvest is underway; the reviewed ADR-0003 runtime stack is on local `main`, including success trace persistence, approval-execute runtime envelope, checkpoint-factory selection, pre-execution budget guard, correction-channel runtime envelope, and the internal-only public resume API follow-up. The local `main` runtime stack is not pushed or released.

### Delivered Capabilities

**Trusted Loop** (full chain):
```text
BusinessIntent → SemanticObject → MetricContract → ProviderContract
→ DataProduct candidate → SQL Safety → QueryResult → EvidenceChain
→ ActionProposal → Approval/OperationTrace → Feedback → KnowledgeAsset candidate
```

**Persistence** (SQLAlchemy Core + Alembic):
- FeedbackStore, KnowledgeStore, SnapshotStore, ApprovalStore, ApprovalContextStore, TraceStore — all Port-based
- Agent Runtime checkpoint store (`SqlAgentCheckpointStore`) persists fingerprint-bound `RunStateSnapshot` records across runtime instances without importing persistence into OS Core; product factories now select memory vs SQL checkpoint stores and inject them into request-scoped `/runs`, `/outcomes`, `/adoptions`, and approval-execute runtime adapters
- action_record connector-side durable ledger (`SqlActionRecordStore`) for records, idempotency replay/conflict checks, replay/conflict/ACK-uncertain audit counters, conflict and uncertain-execution fingerprints without raw audit payloads, and restart-safe rollback
- Postgres JSONB + pgvector-ready migrations (0001–0008)
- In-memory default for tests; Postgres via env var

**Knowledge Retrieval** (hybrid scoring):
- Embedder / KnowledgeRetriever ports in OS Core
- InMemoryKnowledgeRetriever + SqlKnowledgeRetriever (SQL index-column filtering, not JSON scan)
- HybridScorer: vector + lexical RRF + outcome/recency weighted tiebreaker
- `run()` recalls related_knowledge (advisory, trace-visible)
- `GET /knowledge/search` (API key boundary, 503 when no retriever)
- uow-transactional re-embed on record_outcome

**KnowledgeAsset Review Surfaces**:
- Internal-only review queue, review decisions, lifecycle audit trail, publish/deprecate gates, catalog, detail, usage events, decision-quality summary, and quality-summary triage surfaces
- Catalog/detail responses expose safe review-state fields plus `lifecycle_event_count` and nullable `latest_lifecycle_event` summaries for review/publish/deprecate transitions
- Detail responses expose nullable `latest_usage_event` summaries for safe proposal/correction reuse visibility
- Safe projections exclude raw lifecycle reasons, reviewer identity on detail summaries, raw trace payloads, related knowledge content, correction payloads, metric deltas, and secret-like fields

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
- `POST /approvals/{approval_id}/execute` is operator-only (`X-Operator-Key`), advertises `X-Operator-Key` as a required string in OpenAPI while preserving runtime 401 for missing/wrong keys, traverses a narrow Agent Runtime envelope on the current consolidation branch, executes only the original approval-bound context, can resume that context and the action_record ledger across runtime instances on the postgres backend, returns typed 404/409 error shapes plus a typed `execution_audit` projection derived from connector-declared `ConnectorExecutionSemantics` plus whitelisted connector-reported fields, records connector-local ACK-uncertain recovery through idempotent replay, and keeps R4/R5 proposal-only in MVP

**SQL Safety**: SELECT-star hardening (distinct/all/qualified), schema allowlist, forbidden SQL, limit policy

**Eval Hub**: EvalThresholdReporter with golden-loop dimension checks

**Action Governance**: OperationState machine, snapshot/rollback, approval-required guard

**Corrigibility Pause Shell (P5.2a)**: operator-held `CorrigibilityShell`, runtime-held read-only `ShellView`, hash-chain audit, and `BlockCode.PAUSED` refusal path

**Grounding Invariant (P5.1b-ii)**: formal answers/proposals/executions cannot bypass SQL Safety plus a complete `EvidenceChain`; violations raise `GroundingInvariantViolation`

**Agent Runtime v0 Trusted Substrate (ADR-0003)**: self-developed runtime envelope with typed tool calls/results, mandatory policy gate, context-level risk ceiling, R4/R5 proposal-only enforcement, lower-risk side-effect approval checks, pause denial, validation-before-tool-body, pre-execution budget guard for tool-call count / declared timeout ceiling / declared cost units, safe runtime trace projection without raw args/output, case-insensitive sensitive-key redaction for explicit custom trace events, trace-visible checkpoint resume success/failure without raw args/output, minimal checkpoint/replay boundary with fingerprint-bound resume, product-factory checkpoint backend selection, SQLAlchemy-backed durable checkpoint adapter with allowlisted Trusted Loop checkpoint summaries, Trusted Loop adapter with real `TrustedLoopRuntime.evaluate()` integration coverage, successful `/runs` runtime-envelope persistence into safe queryable `RunTrace`, consolidation-verified approval-execute adapter coverage, local-main correction-channel runtime envelope for `/outcomes` and `/adoptions` with explicit completed-write checkpoint-failure semantics, and import-boundary tests against LangGraph/CrewAI/LangChain/OpenAI Agents runtime dependencies

**Agent Runtime public resume API (local-main ADR-0003 follow-up)**: internal-only resume route for checkpointed `/runs` execution, with persisted-checkpoint ref projection, `runtime:resume` scope, fingerprint-bound replay validation before pause/policy recheck, safe response projection, typed non-200 OpenAPI error schemas, safe trace append, external-report-key denial, and OpenAPI contract coverage; merged to deployment local `main`, not pushed or released

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

- PR-07 product-integration stack: do not merge old F3 rehearsal `d46bd45`; rerun integration rehearsal from current local `main` `c404e1e`, then run CI/browser QA and record a fresh verification before founder/CTO merge decision
- pgvector pushdown + HNSW: pending pgvector extension install
- OTel bridge: pending real collector target
- Stage 2 / Temporal / DataProduct Compiler v1: needs new ADR + CTO approval

## Core Rule

Agent OS Core and Agent Runtime are self-developed. Open-source Agent frameworks may be studied as references only and must not become product Core runtime dependencies.
