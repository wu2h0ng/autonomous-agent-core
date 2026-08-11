# P1-45 Knowledge Usage Events Pagination Implementation

Date: 2026-07-03
Branch: `codex/p1-45-knowledge-usage-events-pagination-20260703`
Status: branch-local implementation verified; not merged, pushed, or released

## Goal

Add bounded pagination to the internal, read-only
`GET /knowledge/assets/{asset_id}/usage-events` audit surface. The endpoint
already projects safe usage events for a reviewed KnowledgeAsset; P1-45 makes
that projection operable for longer-running review histories by adding
`limit`, `offset`, `total_count`, and `has_more`.

## TDD Evidence

RED command:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetUsageEventsServiceTest.test_returns_safe_usage_events_without_asset_content_or_mutation tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_usage_events_are_safe_and_guarded tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_usage_events_contract_is_declared -v
```

Expected RED result:

- service raised `TypeError` for unexpected `limit`;
- HTTP response lacked `total_count`;
- OpenAPI route lacked `limit`/`offset` query parameters.

GREEN command:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetUsageEventsServiceTest.test_returns_safe_usage_events_without_asset_content_or_mutation tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_usage_events_are_safe_and_guarded tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_usage_events_contract_is_declared -v
```

GREEN result: 3 tests OK.

## Implementation

- `knowledge_asset_usage_events_service(..., limit, offset)` now validates
  bounded paging with the existing KnowledgeAsset review-surface limit/offset
  rules.
- `GET /knowledge/assets/{asset_id}/usage-events` accepts optional
  `limit`/`offset`, returns `total_count`, `has_more`, `limit`, and `offset`,
  and maps invalid pagination to `400 KNOWLEDGE_USAGE_EVENTS_INVALID_REQUEST`.
- `apps/api_server/openapi.json` declares the query parameters and response
  fields.

## Verification

Related subset:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetUsageEventsServiceTest tests.unit.test_outcome_service.KnowledgeAssetDecisionQualityServiceTest tests.unit.test_outcome_service.KnowledgeAssetDetailServiceTest tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_usage_events_are_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_decision_quality_is_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_detail_is_read_only_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_lists_reviewed_and_published_assets tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_usage_events_contract_is_declared tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_detail_contract_declares_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_catalog_item_contract_declares_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

Result: 19 tests OK.

Full verification:

```text
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

- Ruff check passed
- Ruff format check passed
- Primary unittest discovery: 598 tests OK / 4 skipped
- Eval tests: 12 OK
- Threshold report: 5 golden cases across 8 dimensions passed at 1.0 thresholds
- OpenAPI contract up to date

PostgreSQL parity:

```text
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

- Primary unittest discovery: 598 tests OK
- Eval tests: 12 OK
- Threshold report passed
- OpenAPI contract up to date
- Full local CI parity checks passed

## Boundary

P1-45 is internal-only and read-only. It does not expose raw trace payloads,
raw reasons, related knowledge content, score breakdowns, metric deltas,
correction payloads, or secret-like fields. It does not mutate KnowledgeAsset
lifecycle, versioning, retrieval, feedback, adoption, trace, connector
routing, SQL Safety, EvidenceChain, Approval, or R4/R5 behavior.
