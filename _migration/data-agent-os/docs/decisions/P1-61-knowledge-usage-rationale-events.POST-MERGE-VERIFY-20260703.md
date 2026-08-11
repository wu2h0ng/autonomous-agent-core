# P1-61 Knowledge Usage Rationale Events Post-Merge Verification

Date: 2026-07-03
Branch: `main`
Merged branch: `codex/p1-61-knowledge-usage-rationale-events-20260703`
Merge type: local `git merge --ff-only`
Implementation merge head: `55da9a7`
Status: locally merged and post-merge verified; not pushed or released.

## Merge Evidence

Commands:

```bash
git switch main
git merge --ff-only codex/p1-61-knowledge-usage-rationale-events-20260703
```

Result:

- Fast-forward from `9d7003e` to `55da9a7`.
- Deployment `main` became ahead of `origin/main` by 172 commits.
- `main` and `codex/p1-61-knowledge-usage-rationale-events-20260703` now point
  to the same `HEAD`.
- Tracked worktree remained clean after merge; only untracked `.agent_runs/`
  remained.

## Post-Merge Verification

Focused regressions:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python -m unittest tests.unit.test_outcome_service.KnowledgeAssetUsageEventsServiceTest.test_returns_safe_usage_events_without_asset_content_or_mutation tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_usage_events_are_safe_and_guarded tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_usage_events_contract_is_declared tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

Result: 4 tests OK.

Related regressions:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python -m unittest tests.unit.test_outcome_service.KnowledgeAssetUsageEventsServiceTest tests.unit.test_outcome_service.KnowledgeAssetDecisionQualityServiceTest tests.unit.test_outcome_service.KnowledgeAssetQualitySummaryServiceTest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_usage_events_are_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_decision_quality_is_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_is_safe_and_guarded tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_usage_events_contract_is_declared tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

Result: 14 tests OK.

Full post-merge CI:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

- `ruff check .`: passed.
- `ruff format --check .`: 120 files already formatted.
- Primary unittest discovery: 609 tests OK / 4 skipped.
- Eval suite: 12 tests OK.
- Threshold report: 5 golden cases across 8 dimensions passed at 1.0
  thresholds.
- OpenAPI contract check: up to date.
- PostgreSQL `ci-local-full`: full local CI parity checks passed.

## Product Boundary

P1-61 adds safe usage-event rationale projection only:

- Internal `GET /knowledge/assets/{asset_id}/usage-events` now returns
  `knowledge_context_rationale` on correction-context events.
- Rationale is derived from persisted `action_proposal` and
  `knowledge_recall` metadata for the same trace.
- It exposes only `asset_id`, `score`, `context_quality_boost`, and
  allowlisted `reason_code`.
- Proposal-context usage events keep an empty rationale list.
- Catalog/detail/quality-summary `latest_usage_event` surfaces do not expand.

Non-claims:

- No KnowledgeAsset content/title exposure.
- No raw trace payloads, tool outputs, raw run parameters, related knowledge
  bodies, metric deltas, score-breakdown internals, secret-like fields, or
  external report projection exposure.
- No lifecycle/review/retrieval/feedback/adoption mutation from this
  projection.
- No SQL Safety, EvidenceChain, Approval, connector routing, R4/R5, G10,
  autonomous-core, AGI, or release claim.
