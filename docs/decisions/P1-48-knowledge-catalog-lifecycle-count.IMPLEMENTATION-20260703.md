# P1-48 Knowledge Catalog Lifecycle Count Implementation

Date: 2026-07-03
Branch: `codex/p1-48-knowledge-catalog-lifecycle-count-20260703`
Status: branch-local implementation verified; not merged, pushed, or released

## Goal

Expose a safe lifecycle audit summary on the internal, read-only
`GET /knowledge/assets` catalog surface. P1-48 adds
`lifecycle_event_count` to each catalog item so reviewers can see whether a
KnowledgeAsset has review/publish/deprecate history before opening the detail
or lifecycle-events surfaces.

## TDD Evidence

RED command:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest.test_catalog_lists_active_and_published_assets_without_mutating_store tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_lists_reviewed_and_published_assets tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_catalog_item_contract_declares_review_state -v
```

Expected RED result:

- service catalog item payload raised `KeyError` for missing
  `lifecycle_event_count`;
- HTTP catalog item payload lacked `lifecycle_event_count`;
- OpenAPI `KnowledgeAssetCatalogItem` did not require or declare
  `lifecycle_event_count`.

GREEN command:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest.test_catalog_lists_active_and_published_assets_without_mutating_store tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_lists_reviewed_and_published_assets tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_catalog_item_contract_declares_review_state -v
```

GREEN result: 3 tests OK.

## Implementation

- Added a shared `_knowledge_asset_lifecycle_event_count` helper that counts
  matching review/publish/deprecate trace events for a specific asset.
- `knowledge_asset_catalog_service` now returns `lifecycle_event_count` on each
  catalog item by reading the persisted source trace when available.
- `knowledge_asset_detail_service` now reuses the same helper as P1-48 cleanup,
  preserving its P1-47 response shape.
- `KnowledgeAssetCatalogItem` and `apps/api_server/openapi.json` declare the new
  integer field.

## Verification

Related subset:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest tests.unit.test_outcome_service.KnowledgeAssetDetailServiceTest tests.unit.test_outcome_service.KnowledgeAssetLifecycleEventsServiceTest tests.unit.test_outcome_service.KnowledgeAssetUsageEventsServiceTest tests.unit.test_outcome_service.KnowledgeAssetDecisionQualityServiceTest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_lists_reviewed_and_published_assets tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_detail_is_read_only_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_lifecycle_events_are_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_usage_events_are_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_decision_quality_is_safe_and_guarded tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_catalog_item_contract_declares_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_detail_contract_declares_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_lifecycle_events_contract_is_declared tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_usage_events_contract_is_declared tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

Result: 23 tests OK.

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
- Primary unittest discovery: 599 tests OK / 4 skipped
- Eval tests: 12 OK
- Threshold report: 5 golden cases across 8 dimensions passed at 1.0 thresholds
- OpenAPI contract up to date
- Full local CI parity checks passed

## Boundary

- Internal-only: requires `knowledge:review` scope.
- Read-only: does not mutate lifecycle, version, retrieval, feedback, adoption,
  connector routing, or approval state.
- Safe projection only: exposes a count, not lifecycle events, raw lifecycle
  reasons, raw trace payloads, related knowledge content, score breakdowns,
  correction payloads, metric_deltas, or secret-like fields.
- Product/process boundary: this is an Enterprise OS KnowledgeAsset triage
  usability slice, not an autonomous-core, G10, AGI, or R4/R5 execution claim.
