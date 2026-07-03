# P1-50 Knowledge Detail Lifecycle Summary Merge Readiness

Date: 2026-07-03
Branch: `codex/p1-50-knowledge-detail-lifecycle-summary-20260703`
Implementation head: `1e606f3`
Target: deployment local `main`
Status: ready for cautious local ff-only merge; not pushed or released

## Scope

P1-50 adds nullable `latest_lifecycle_event` to the internal
`GET /knowledge/assets/{asset_id}` detail response. The field summarizes the
latest matching lifecycle decision event from the source trace using safe
allowlisted transition metadata only.

## Pre-Merge Checks

```text
git merge-base --is-ancestor main HEAD
```

Result: `0`.

```text
git rev-list --left-right --count main...HEAD
```

Result: `0 1`.

```text
git status --short --branch
```

Result: branch is `codex/p1-50-knowledge-detail-lifecycle-summary-20260703`;
only `.agent_runs/` is untracked.

## Verification Evidence

Target GREEN:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetDetailServiceTest.test_returns_single_asset_detail_without_mutating_store tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_detail_is_read_only_and_guarded tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_detail_contract_declares_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

Result: 4 tests OK.

Related subset:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest tests.unit.test_outcome_service.KnowledgeAssetDetailServiceTest tests.unit.test_outcome_service.KnowledgeAssetLifecycleEventsServiceTest tests.unit.test_outcome_service.KnowledgeAssetUsageEventsServiceTest tests.unit.test_outcome_service.KnowledgeAssetDecisionQualityServiceTest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_lists_reviewed_and_published_assets tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_detail_is_read_only_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_lifecycle_events_are_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_usage_events_are_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_decision_quality_is_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_is_safe_and_guarded tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_catalog_item_contract_declares_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_detail_contract_declares_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_lifecycle_events_contract_is_declared tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_usage_events_contract_is_declared tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_quality_summary_contract_is_declared tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

Result: 25 tests OK.

Full verification:

```text
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result: ruff and format checks passed; primary unittest discovery passed with
599 OK / 4 skipped; eval tests passed with 12 OK; threshold report passed for
5 golden cases across 8 dimensions at 1.0 thresholds; OpenAPI contract was up
to date.

PostgreSQL parity:

```text
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result: full local CI parity passed with the same 599 primary unittest tests,
12 eval tests, threshold report, and OpenAPI checks.

## Merge Conditions

- Local fast-forward merge only.
- No push.
- No release.
- Re-run `make ci` and PostgreSQL `ci-local-full` after merge.

## Boundary

This slice does not expose raw lifecycle reasons, lifecycle event bodies,
reviewer identity on detail summaries, raw trace payloads, related knowledge
content, raw score breakdowns, correction payloads, metric deltas, or
secret-like fields. It does not mutate lifecycle/version/retrieval/feedback/
adoption state, lower governance, bypass SQL Safety/EvidenceChain/Approval,
promote adoption/value, write feedback, change connector routing, or allow
R4/R5 automatic execution.
