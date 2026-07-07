# M6 Pilot Readiness Report

> Date: 2026-07-06
> Repo: `ai-native-business-data-agent-os`
> Local HEAD: `b5512a3` (`main` working tree)
> Origin/main: behind local; push/release remain separate gates
> Report owner: Agent (M6 Pilot Readiness Review)

## Executive Summary

`ai-native-business-data-agent-os` has completed Phase 1 through Phase 6 on the local `main` working tree. The Stage 1 trusted business production loop is demonstrable, testable, and auditable:

- 20 golden business intents pass end-to-end through the Trusted Loop.
- All 11 eval dimensions (intent, metric, nl_intent, data_product, evidence, evidence_typed, sql_safety, action, feedback, provider, trace) meet the 1.0 threshold.
- Approval-before-execution, SQL Safety, EvidenceChain completeness, and FeedbackEvent→KnowledgeAsset paths are covered by deterministic tests.
- The frontend `/workspace` page provides a natural-language dashboard builder; `/approval`, `/outcomes`, `/knowledge`, and `/trace` pages expose governance surfaces.
- `make ci` and `make ci-local-full` pass.

**Readiness verdict: CONDITIONAL GO** for internal pilot/POC, provided the release-gate and deployment-configuration blockers below are accepted or resolved by founder/CTO.

## 90-Day Roadmap Acceptance Criteria

| Criterion | Status | Evidence |
|---|---|---|
| At least 3 golden business loops covered | ✅ Pass | 20 golden intents in `tests/eval/golden_queries.json` (gmv, roi, conversion_rate, spend, orders) |
| EvidenceChain rate 1.0 for formal answers | ✅ Pass | Eval dimension `evidence` 20/20 = 1.0 |
| SQL Safety pass/block correctness 1.0 | ✅ Pass | Eval dimension `sql_safety` 20/20 = 1.0; red-team suite `tests/redteam/test_sql_safety_bypass.py` covers 14 bypass categories |
| At least one governed action path proves approval before side effects | ✅ Pass | `tests/integration/test_s2_governed_real_action_local_disposer.py`, `tests/unit/test_trusted_loop_snapshot_rollback.py`, `scripts/smoke-test.sh` |
| At least one FeedbackEvent→KnowledgeAsset candidate/version path is real | ✅ Pass | `tests/unit/test_trusted_loop.py`, `tests/unit/test_adoption_channel.py`, `tests/integration/test_s4_outcome_learning_moat.py` |
| UI communicates the loop without hiding evidence or action governance | ✅ Pass | Frontend shows EvidenceCardList, GovernancePanel, ActionProposal, approval detail/execute pages; `tests/unit/test_workspace_prototype.py` guards read-only/projection behavior |

## Stop Conditions Check

| Stop Condition | Status | Notes |
|---|---|---|
| Any P0 depends on hard-coded demo-only behavior | ✅ No | Anti-stub linter passes; static executor is a configurable default, not hardcoded product logic |
| SQL Safety or EvidenceChain can be bypassed | ✅ No | Red-team and eval gates fail closed |
| Action execution happens before approval when approval is required | ✅ No | Runtime policy gate + approval-resume path tested |
| OS Core imports domain packs/providers/action connectors | ✅ No | `test_agent_runtime_import_boundaries.py` passes; concrete connectors live in `apps/api_server` or `action_connectors/` packages |
| Product scope drifts into full Data Fabric or connector marketplace | ✅ No | Scope remains semantic-action contract spine + governed loop |

## Phase 1-6 Capability Inventory

| Phase | Capability | Verification |
|---|---|---|
| M1 Contract Spine | MetricContract, SQLTemplate, SQL Safety AST gate, DataProductCompiler | `test_sql_safety.py`, `test_data_product_compiler.py`, `test_provider_planner.py`, `test_query_planner.py` |
| M2 Governed Operation | ActionProposal, ApprovalLite, OperationTrace, action_record connector, snapshot/rollback | `test_trusted_loop.py`, `test_action_record_connector.py`, integration tests |
| M3 Feedback/Knowledge | record_outcome, FeedbackEvent, KnowledgeAsset candidate/version, adoption-driven promotion | `test_adoption_channel.py`, `test_trusted_loop.py`, `test_evidence_chain.py` |
| M4 API/CLI Surface | `/runs`, `/outcomes`, `/adoptions`, `/approvals`, CLI run/record-outcome | `test_http_app.py`, `test_cli_record_outcome.py` |
| M5 Workspace F1 | Query page, approval list/detail, outcomes page, report projection | `test_workspace_prototype.py`, `npm run build` |
| M6 NL Workspace | `POST /nl-build`, `GET /metrics`, dashboard CRUD, `/workspace` page | `test_nl_query_engine.py`, `test_dashboard.py`, `test_http_app.py`, `npm run build` |
| Production Pilot | `/health`, `scripts/migrate.sh`, tenant API, smoke test, structured logs, `/metrics` | `test_http_app.py`, `test_tenant.py`, `test_migrate_script.py`, `test_smoke_test_script.py` |

## Test & CI Results

```text
make ci                        : PASS
  - ruff check                 : PASS
  - ruff format --check        : PASS
  - anti_stub_linter.py        : PASS
  - unit tests                 : 945 OK / 4 skipped
  - eval tests                 : 12 OK
  - threshold report           : 20/20, all dimensions 1.0
  - openapi-contract --check   : PASS

make ci-local-full (PostgreSQL): PASS
  - unit tests                 : 945 OK / 4 skipped
  - eval tests                 : 12 OK
  - threshold report           : 20/20, all dimensions 1.0
  - openapi-contract --check   : PASS

frontend npm run build         : PASS
frontend npm run lint          : PASS
```

## Known Risks / Blockers for Pilot

| # | Risk / Blocker | Severity | Owner | Mitigation / Next Action |
|---|---|---|---|---|
| 1 | **Push authorization gate mismatch**: `make controlled-pilot-readiness-check` fails because PR-11 records `DEPLOYMENT_PUSH: AUTHORIZED` for candidate_head `de2f93a9...`, while current local HEAD is `b5512a3...` and origin/main is behind. The gate treats this as unauthorized promotion risk. | High (release process) | Founder/CTO | Refresh the deployment push authorization record (PR-11 or new PR) to either (a) HOLD with updated boundary language, or (b) AUTHORIZE the new candidate_head after review. Do not change without explicit business authorization. |
| 2 | **Mixed uncommitted working tree**: `git status` shows many pre-existing modifications alongside Phase 6 changes. It is hard to isolate the M6 candidate from unrelated work. | Medium (release hygiene) | Engineering/CTO | Before any origin/main push, stage only the M6-relevant files or create a clean feature branch from origin/main and cherry-pick the M6 commits. |
| 3 | **Default in-memory/static backend**: `AGENT_OS_EXECUTOR` defaults to `static` and `AGENT_OS_STORE_BACKEND` defaults to `memory` when env vars are absent. A POC deployment that forgets to set these will run demo-mode (fixture rows, no persistence). | Medium (operational) | DevOps/CTO | Document production `.env` template; add startup warning log when running with in-memory/static defaults; enforce `AGENT_OS_DATABASE_URL` for `store_backend=postgres`. |
| 4 | **Container smoke test not exercised locally**: `scripts/smoke-test.sh` requires Docker; local Docker daemon was unavailable during this review, so the containerized path was not run end-to-end. | Low (verification gap) | Engineering | Run `scripts/smoke-test.sh` on a machine with Docker before customer POC; it is covered by `test_smoke_test_script.py` parsing checks only. |
| 5 | **Frontend has no automated test runner**: `/workspace` page is verified by build/lint only; no unit/e2e tests exist. | Low (regression risk) | Engineering | Add Playwright or Vitest frontend tests as a follow-up slice. |

## Recommendations

1. **Accept internal pilot readiness** for a controlled POC, with the five risks above tracked and accepted by CTO.
2. **Do not push to `origin/main` or create a release tag** until the push authorization gate is refreshed by founder/CTO.
3. **Before customer-facing deployment**, switch from default in-memory/static backends to PostgreSQL + SQLite executor or real ProviderContract data plane, and rotate all default API keys.
4. **Continue to forbid R4/R5 automatic execution** in MVP; current implementation correctly keeps them proposal-only.

## Git State

- Local branch: `main`
- Local HEAD: `b5512a3 feat: PostgreSQL executor, Email/Webhook connectors, Docker deployment`
- Origin/main: `b5512a3` (as observed during finalization), but `make controlled-pilot-readiness-check` still fails because PR-11 records `DEPLOYMENT_PUSH: AUTHORIZED` for candidate_head `de2f93a9...` and expects origin/main to be `dba87bc35ae2c7be3dfbcc022c64c0a04cbf9171` (per PR-25). The gate therefore treats the current state as an unauthorized promotion. This is recorded as a release-process blocker, not overridden by this agent.
- Working tree: extensive uncommitted changes; M6-relevant files are mixed with prior work
- Push/merge: **not performed by this review**; await founder/CTO refresh of PR-11 / push authorization before any release

## Sign-Off

This report is an engineering input to the founder/CTO pilot-go/no-go decision. It does not authorize push, release, or customer commitments.
