# P1-40 Knowledge Catalog Priority Counts Implementation

Date: 2026-07-03
Branch: `codex/p1-40-knowledge-catalog-priority-counts-20260703`
Status: branch-local implementation verified; not merged, pushed, or released

## Scope

Add safe page-local `review_priority_counts` to the internal read-only
`GET /knowledge/assets` catalog response.

The count surface mirrors the existing catalog action/rationale counts and the
quality-summary review-priority counts, but stays scoped to the current catalog
page after lifecycle/review filters, ordering, limit, and offset are applied.

## Boundary

P1-40 is internal-only and read-only. It does not:

- expose raw `usage_trace_ids`, raw trace events, raw trace payloads, raw
  reasons, score breakdowns, correction payloads, metric deltas, or secret-like
  fields;
- mutate lifecycle, version, retrieval, feedback, or adoption state;
- claim causal/value attribution;
- bypass SQL Safety, EvidenceChain, Approval, or principal/scope checks;
- change connector routing;
- allow R4/R5 automatic execution.

## TDD Evidence

RED was observed before implementation:

```text
KeyError: 'review_priority_counts'
AssertionError: 'review_priority_counts' not found in [...]
```

The RED command was:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest.test_catalog_paginates_visible_assets_and_counts_current_page tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_paginates_visible_assets tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_catalog_item_contract_declares_review_state -v
```

## Implementation

Changed files:

- `apps/api_server/src/agent_os_api/outcome_service.py`
  - `knowledge_asset_catalog_service` now returns `review_priority_counts`.
  - Counts use the current page items only.
- `apps/api_server/src/agent_os_api/http_app.py`
  - `KnowledgeAssetCatalogResponse` includes `review_priority_counts`.
- `apps/api_server/openapi.json`
  - Regenerated from the live FastAPI schema.
- `tests/unit/test_outcome_service.py`
- `tests/unit/test_http_app.py`
- `tests/unit/test_openapi_contract.py`

## Verification

Targeted GREEN:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest.test_catalog_paginates_visible_assets_and_counts_current_page tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_paginates_visible_assets tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_catalog_item_contract_declares_review_state -v
```

Result: 3 tests OK.

Related KnowledgeAsset/API/OpenAPI subset:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest tests.unit.test_outcome_service.KnowledgeAssetDetailServiceTest tests.unit.test_outcome_service.KnowledgeAssetDecisionQualityServiceTest tests.unit.test_outcome_service.KnowledgeAssetQualitySummaryServiceTest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_lists_reviewed_and_published_assets tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_paginates_visible_assets tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_orders_by_review_priority tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_filters_review_state tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_detail_is_read_only_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_decision_quality_is_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_is_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_filters_status tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_catalog_item_contract_declares_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_detail_contract_declares_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_quality_summary_contract_is_declared tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

Result: 26 tests OK.

Full branch-local CI:

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

PostgreSQL local parity:

```text
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

- Ruff check passed
- Ruff format check passed
- Primary unittest discovery: 598 tests OK
- Eval tests: 12 OK
- Threshold report passed
- OpenAPI contract up to date
- Full local CI parity checks passed

## Engineering Gate Answers

- Entry point: internal `GET /knowledge/assets`
- Contract: `KnowledgeAssetCatalogResponse` / OpenAPI snapshot
- Failure mode: no new write path; existing invalid filter/order/pagination
  errors remain unchanged
- Test validity: tests fail if the response omits `review_priority_counts` or
  if OpenAPI does not require the field
- Integration: FastAPI route, service layer, OpenAPI contract, unit tests
- Boundary: OS Core remains domain-independent and external agent-framework-free
- Observability: no trace or state write is introduced; this is a read-only
  review surface
- Product/process boundary: product runtime internal review capability only;
  no research/autonomy/customer-facing claim
