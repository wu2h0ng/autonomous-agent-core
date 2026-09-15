# AR-20260707: Workspace freeze & review split — ADR-0013 productization convergence

- Status: **Freeze recorded; review packages defined; no commit/push authorized**
- Review identity: `builder-id: cursor-agent`, `reviewed-by: cursor-agent (analysis-only freeze)`
- Parent: `docs/decisions/ADR-0013-master-implementation-roadmap-concurrent.md`, `docs/architecture_reviews/AR-20260707-staged-out-capabilities-cde.md`
- Scope: **Documentation and inventory only.** This AR does not modify runtime behavior, turn on feature flags, or authorize push/release.

## 1. Freeze evidence

| Field | Value |
|---|---|
| HEAD | `b5512a3` (`feat: PostgreSQL executor, Email/Webhook connectors, Docker deployment`) |
| Workspace delta | **197 paths** — 64 modified/deleted tracked + 133 untracked |
| CI command | `make ci PYTHON=.venv/bin/python` |
| CI result | **PASS** — `Ran 1176 tests` / 4 skipped; eval `Ran 12 tests` OK; lint, format-check, anti-stub-lint, eval-threshold-report (all 11 dimensions 1.0), OpenAPI drift gate pass |
| Feature flags | All default **off**: `AGENT_OS_MCP_GATEWAY`, `AGENT_OS_FULL_BPM_WORKFLOW`, `AGENT_OS_R4_R5_AUTO_EXECUTION` |
| R4/R5 posture | Proposal-only by default; auto-execution requires tenant policy + explicit flag (ADR-0012) |

> **Note.** `make ci` does not include `current-state-verification-check` or `ci-local-full`. Those remain separate release gates before any push claim.

## 2. What changed since M6 pilot baseline

The uncommitted workspace spans ADR-0013 concurrent workstreams **A–F** plus Phase 2–5 product surfaces already described in `docs/CURRENT_STATE.yaml`. Since the C/D/E engine review (AR-20260707-staged-out-capabilities-cde), the following **productization layer** landed locally (still uncommitted):

- **D persistence:** `WorkflowStorePort`, `InMemoryWorkflowStore`, `SqlWorkflowStore`, Alembic `0014_staged_out_stores` (`approval_workflows`, `workflow_instances`, `auto_execution_policies`).
- **E persistence + HTTP:** `AutoExecutionPolicyStorePort` / `AutoExecutionPolicyStore`, `PUT/GET /tenants/{tenant_id}/auto-execution-policy`.
- **CDE management plane:** `staged_out_service.py` — workflow registration, MCP server/tool registration, policy bootstrap helpers.
- **C composition transport:** `mcp_transport.py` — noop/in_process handlers; fail-closed stdio (disabled by default, allowlist, no shell).
- **D instance HTTP:** `POST /workflows/{id}/instances`, `GET /workflow-instances/{id}`, approve/reject/delegate/timeout-check (gated by `AGENT_OS_FULL_BPM_WORKFLOW`).
- **Factory wiring:** `runtime_factory.py` builds approval router, policy engine, workflow runtime/store, MCP gateway, agent-runtime adapter with optional MCP attach.

OS Core boundaries remain intact: no imports of `domain_packs/`, `providers/`, `action_connectors/`, or persistence from `packages/os_core/`.

## 3. Review packages (scoped PR split)

Each path is assigned to **one primary package** for review. Tests for a package travel with that package. Cross-package dependencies are noted in §4.

### PKG-01 — Contracts (`packages/contracts/`)

New/modified typed seams: `configuration`, `domain_pack`, `mcp_gateway`, `usage`, `workflow`, `causal_discovery_seam`; extensions to `architecture`, `trusted_loop`.

**Review focus:** backward compatibility, flag defaults, OperationState / ActionProposal fields, no domain leakage.

### PKG-02 — Persistence & migrations (`packages/persistence/`)

Alembic `0010`–`0014`; `repositories`, `schema`, `mappers`; adapters for usage, tenant, dashboard, policy approval records, staged-out stores.

**Review focus:** migration ordering, PG/SQLite parity, port boundaries (OS Core never imports persistence).

### PKG-03 — Data Fabric / federated query (workstream **A**)

OS Core: `data_product_compiler/` (federation, provider_planner, query_planner), `query_runtime/csv_executor`, `metric_contract_loader`, `_metric_aliases`.

Composition: `executor_factory.py`, `clickhouse_executor.py`, `mysql_executor.py`, `feishu_executor.py`.

Domain pack: `metrics.json`, `metrics/gmv.yaml`, `sql_templates.json`.

**Review focus:** ProviderContract routing, SQL Safety path unchanged, no hard-coded SQL ratio regression.

### PKG-04 — Domain Pack SDK (workstream **B**)

`packages/sdk/domain_pack.py`, `packages/contracts/domain_pack.py`, `domain_packs/content_commerce/manifest.yaml`, `semantic_objects.json`, related tests.

**Review focus:** SDK boundary vs OS Core; pack-as-config not pack-as-code in Core.

### PKG-05 — Semantic graph & lineage

`semantic_runtime/` graph wiring, evidence semantic lineage contracts/builders, `domain_packs/content_commerce/semantic_objects.json`, E2E lineage tests.

**Review focus:** EvidenceChain population, no bypass of SQL Safety / EvidenceChain on formal answers.

### PKG-06 — MCP Gateway (workstream **C**)

OS Core: `mcp_gateway/`. Composition: `mcp_transport.py`, staged-out MCP registration, factory `build_mcp_gateway`, agent-runtime MCP attach.

**Review focus:** fail-closed stdio, audit decision semantics (F3 fixed per prior AR), trace_sink when flag on.

### PKG-07 — Full BPM / workflow (workstream **D**)

OS Core: `workflow.py`, `workflow_store.py`. HTTP instance lifecycle + staged-out workflow registration. Migration 0014 workflow tables.

**Review focus:** terminal-state guarding, tenant isolation, passive timeout scheduler requirement (O1 from prior AR).

### PKG-08 — Policy / R4–R5 auto-execution (workstream **E**)

OS Core: `policy_engine.py`, `approval_router.py`. Persistence: policy approval records (0013), auto-execution policies (0014). HTTP tenant policy API. TrustedLoop pre-approved execution path.

**Review focus:** F1/F2 consume-time recheck + idempotent mint (fixed per prior AR), default proposal-only, C7 pause supremacy.

### PKG-09 — CDE integration & API surface

`runtime_factory.py`, `http_app.py`, `staged_out_service.py`, `outcome_service.py`, `openapi.json`.

**Review focus:** factory injectability, flag gating on new routes, OpenAPI drift, principal/scope unchanged for existing surfaces.

### PKG-10 — Phase 2–5 product surfaces (usability / trust / commercialization / pilot)

NL query, conversation, alert agent, tenant, usage, quota, dashboard, report, deploy scripts (`migrate.sh`, `smoke-test.sh`, `start-local.sh`), Docker/Makefile, tenant HTTP, health/metrics.

**Review focus:** tenant_id threading, RBAC scopes, quota 429 paths, no secrets in repo.

### PKG-11 — Frontend F3+ (`apps/workspace/frontend/`)

Live API pages: runs, approvals, outcomes, workspace, knowledge; shared components (EvidenceChain, ActionProposal, ApprovalList/Detail, DataProductCard, OutcomeForm); `api.ts` / OpenAPI types.

**Review focus:** blocked/insufficient states, operator-key separation, no mock success on production paths.

### PKG-12 — Tests & eval

`tests/unit/*` (80+ new/updated), `tests/redteam/`, eval golden/threshold updates. Deleted `test_persistence.py` → split into focused store tests.

**Review focus:** tests fail if logic bypassed; no fixture-only green.

### PKG-13 — Docs & governance

`AGENTS.md`, ADR-0012/0013, ADR-20260705 SQL safety, pilot readiness report, competitive grounding research, `docs/CURRENT_STATE.yaml`, this AR.

**Review focus:** product vs process boundary; no overstated release claims.

## 4. Recommended merge order

Serial dependency order for scoped commits (each commit should keep `make ci` green):

```text
1. PKG-01 Contracts
2. PKG-02 Persistence & migrations (0010 → 0014 in order)
3. PKG-03 Data Fabric (+ domain pack metric templates in same or follow-on commit)
4. PKG-04 Domain Pack SDK
5. PKG-05 Semantic graph & lineage
6. PKG-06 MCP Gateway (Core) → PKG-09 partial (transport + registration wiring)
7. PKG-07 BPM (Core + store)
8. PKG-08 Policy / auto-execution (Core + stores)
9. PKG-09 CDE integration remainder (factory, http_app, openapi.json)
10. PKG-10 Phase 2–5 surfaces & infra scripts
11. PKG-11 Frontend
12. PKG-12 Tests (any tests not already committed with their package)
13. PKG-13 Docs & governance
```

Parallel review is allowed **across packages** once PKG-01 and PKG-02 land; implementation merges should respect the serial order above to avoid migration/contract skew.

## 5. Out of scope for this freeze

- **Workstream G** (Temporal / OPA / Trino): not present in workspace; on-demand per ADR-0013.
- **Enabling feature flags** in any deployed environment.
- **Push / release / RC tag** — founder/CTO gates unchanged.
- **Real MCP stdio/SSE production transport** — composition-layer stub/fail-closed only; full transport is a follow-on slice.

## 6. Next slices (post-freeze)

1. ~~**Parallel hardening:** C/D/E trace lineage in RunTrace for management-plane ops; workflow instance E2E through postgres backend.~~ **Done locally (2026-07-07):** `staged_out_trace.build_staged_out_trace_sink`, factory singleton `TraceStore`, SDK manifest validation, `test_runtime_factory_hardening`.
2. ~~**A/B SDK convergence:** domain pack loader paths unified with SDK entry points.~~ **Done locally:** `ContentCommerceRuntimeFactory.load_domain_pack_manifest()` + `_validate_metrics_against_manifest()`.
3. **Frontend F3+ closure:** E2E against live API in smoke/pilot pack (pages exist; browser E2E not automated in CI).
4. ~~**Pilot observability:** extend `scripts/smoke-test.sh` for staged-out routes (flag-on test profile only).~~ **Done locally:** default-off 503 check + optional `AGENT_OS_SMOKE_STAGED_OUT=true`.
5. **Scoped commits** per §4 after founder/CTO authorization.

## 7. Decision

- Workspace at `main@b5512a3` is **frozen for review** at **1176 unit tests / 4 skipped + 12 eval OK**.
- Thirteen review packages (PKG-01–PKG-13) are defined for split PRs.
- **No runtime or flag changes** are authorized by this AR.
- Uncommitted work **must not** be described as released until scoped commits, CI-local-full, and push gates pass.
