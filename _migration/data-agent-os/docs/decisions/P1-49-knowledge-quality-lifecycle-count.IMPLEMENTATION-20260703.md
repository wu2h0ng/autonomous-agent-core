# P1-49 Knowledge Quality Summary Lifecycle Count Implementation

Date: 2026-07-03
Branch: `codex/p1-49-knowledge-quality-lifecycle-count-20260703`
Status: branch-local implementation verified; not merged, pushed, or released

## Goal

Expose the same safe lifecycle audit count on the internal, read-only
`GET /knowledge/assets/quality-summary` item projection that already exists on
catalog and detail surfaces. Reviewers can now see whether a KnowledgeAsset has
review/publish/deprecate audit history while using the quality triage view.

## TDD Evidence

RED commands:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python3 -m unittest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_is_safe_and_guarded tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_quality_summary_contract_is_declared -v
```

Expected RED result:

- HTTP quality-summary item raised `KeyError` for missing
  `lifecycle_event_count`;
- OpenAPI `KnowledgeAssetQualitySummaryItem` did not require or declare
  `lifecycle_event_count`.

Service RED confirmation:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetQualitySummaryServiceTest.test_returns_safe_quality_catalog_without_mutation -v
```

Result: service quality-summary item raised `KeyError` for missing
`lifecycle_event_count`.

GREEN command:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetQualitySummaryServiceTest.test_returns_safe_quality_catalog_without_mutation tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_is_safe_and_guarded tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_quality_summary_contract_is_declared -v
```

GREEN result: 3 tests OK.

## Implementation

- `knowledge_asset_quality_summary_service` now reads the asset source trace
  when available and returns `lifecycle_event_count` for each quality-summary
  item.
- `KnowledgeAssetQualitySummaryItem` and `apps/api_server/openapi.json` declare
  the new integer field.
- Existing filters, ordering, pagination, page-local counts, and safe projection
  boundaries are unchanged.

## Verification

Related subset:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetQualitySummaryServiceTest tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest tests.unit.test_outcome_service.KnowledgeAssetDetailServiceTest tests.unit.test_outcome_service.KnowledgeAssetLifecycleEventsServiceTest tests.unit.test_outcome_service.KnowledgeAssetUsageEventsServiceTest tests.unit.test_outcome_service.KnowledgeAssetDecisionQualityServiceTest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_is_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_filters_status tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_lists_reviewed_and_published_assets tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_detail_is_read_only_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_lifecycle_events_are_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_usage_events_are_safe_and_guarded tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_quality_summary_contract_is_declared tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_catalog_item_contract_declares_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_detail_contract_declares_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_lifecycle_events_contract_is_declared tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_usage_events_contract_is_declared tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

Result: 30 tests OK.

Full verification:

```text
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

- Ruff check passed
- Ruff format check passed
- Primary unittest discovery: 599 tests OK / 4 skipped
- Eval tests: 12 OK
- Threshold report: 5 golden cases across 8 dimensions passed at 1.0 thresholds
- OpenAPI contract up to date

PostgreSQL parity:

```text
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

- Ruff check passed
- Ruff format check passed
- Primary unittest discovery: 599 tests OK
- Eval tests: 12 OK
- Threshold report: 5 golden cases across 8 dimensions passed at 1.0 thresholds
- OpenAPI contract up to date
- Full local CI parity checks passed

## Boundary

- Internal-only: requires `knowledge:review` scope.
- Read-only: does not mutate lifecycle, version, retrieval, feedback, adoption,
  connector routing, approval state, or quality scoring.
- Safe projection only: exposes a count, not lifecycle events, raw lifecycle
  reasons, raw trace payloads, related knowledge content, score breakdowns,
  correction payloads, metric_deltas, or secret-like fields.
- Product/process boundary: this is an Enterprise OS KnowledgeAsset reviewer
  triage slice, not an autonomous-core, G10, AGI, causal/value attribution, or
  R4/R5 execution claim.
