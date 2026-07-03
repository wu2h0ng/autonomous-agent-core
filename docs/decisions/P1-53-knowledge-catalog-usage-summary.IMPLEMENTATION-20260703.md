# P1-53 Knowledge Catalog Usage Summary Implementation

Date: 2026-07-03
Branch: `codex/p1-53-knowledge-catalog-usage-summary-20260703`
Status: branch-local implementation verified; not merged, pushed, or released

## Goal

Expose a safe latest usage-event summary on internal `GET /knowledge/assets`
catalog items. Reviewers can triage from the list view by seeing the latest
proposal/correction reuse signal without opening each asset detail first.

## TDD Evidence

RED command:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest.test_catalog_lists_active_and_published_assets_without_mutating_store tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_lists_reviewed_and_published_assets tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_catalog_item_contract_declares_review_state -v
```

Expected RED result:

- service and HTTP catalog items raised `KeyError` for missing
  `latest_usage_event`;
- OpenAPI `KnowledgeAssetCatalogItem` did not require or declare the new summary
  field.

GREEN command:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest.test_catalog_lists_active_and_published_assets_without_mutating_store tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_lists_reviewed_and_published_assets tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_catalog_item_contract_declares_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

GREEN result: 4 tests OK.

## Implementation

- `knowledge_asset_catalog_service` now projects nullable
  `latest_usage_event` for each visible catalog item by reusing the same
  allowlisted summary helper used by the detail response.
- `KnowledgeAssetCatalogItem` and `apps/api_server/openapi.json` declare the
  nullable `KnowledgeAssetUsageEventSummary` field.
- The summary is limited to `trace_id`, `step`, `usage_kind`, `asset_id`, and
  `knowledge_context_refs`.

## Verification

Related subset:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest tests.unit.test_outcome_service.KnowledgeAssetDetailServiceTest tests.unit.test_outcome_service.KnowledgeAssetUsageEventsServiceTest tests.unit.test_outcome_service.KnowledgeAssetDecisionQualityServiceTest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_lists_reviewed_and_published_assets tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_detail_is_read_only_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_usage_events_are_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_decision_quality_is_safe_and_guarded tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_catalog_item_contract_declares_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_detail_contract_declares_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_usage_events_contract_is_declared tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

Result: 19 tests OK.

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
- Safe projection only: exposes latest usage summary fields, not usage event
  bodies, raw trace payloads, source asset content, raw run parameters, related
  knowledge content, tool names on catalog summaries, correction payloads,
  metric_deltas, or secret-like fields.
- Product/process boundary: this is an Enterprise OS KnowledgeAsset catalog
  triage slice, not an autonomous-core, G10, AGI, causal/value attribution,
  adoption/value-promotion, or R4/R5 execution claim.
