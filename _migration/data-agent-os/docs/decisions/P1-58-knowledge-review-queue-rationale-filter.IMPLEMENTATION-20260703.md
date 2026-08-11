# P1-58 Knowledge Review Queue Rationale Filter Implementation

Date: 2026-07-03
Branch: `codex/p1-58-knowledge-review-queue-rationale-filter-20260703`
Status: branch-local implementation verified; not merged, pushed, or released.

## Goal

Add rationale-code triage to the internal KnowledgeAsset review queue so
reviewers can filter DRAFT candidates by the safe reason they need attention,
using the same allowlisted rationale vocabulary already exposed by catalog and
quality-summary surfaces.

## TDD Red

Command:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeReviewQueueServiceTest.test_filters_draft_candidates_by_review_rationale_code tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_review_queue_filters_review_rationale_code tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_review_queue_contract_declares_quality_triage_fields -v
```

Expected failures confirmed:

- Service rejected `review_rationale_code` as an unexpected keyword argument.
- HTTP response did not include `review_rationale_code_filter`.
- OpenAPI did not declare `review_rationale_code` for
  `GET /knowledge/review-queue`.

## Implementation

- `knowledge_review_queue_service(...)` now accepts `review_rationale_code`.
- The value is normalized through the existing allowlisted rationale-code helper.
- DRAFT candidates are filtered after quality-state derivation and before
  pagination.
- Response now returns `review_rationale_code_filter` and page-local
  `review_rationale_code_counts`.
- `GET /knowledge/review-queue` exposes optional `review_rationale_code` with
  the same enum used by catalog and quality-summary surfaces.
- Invalid values return HTTP 400 with
  `KNOWLEDGE_REVIEW_QUEUE_INVALID_REQUEST`.
- `apps/api_server/openapi.json` was regenerated and checked.

## Verification

Focused RED/GREEN:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python3 -m agent_os_api.openapi_contract && PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeReviewQueueServiceTest.test_filters_draft_candidates_by_review_rationale_code tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_review_queue_filters_review_rationale_code tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_review_queue_contract_declares_quality_triage_fields tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

Result: OpenAPI written; 4 tests OK.

Related regression set:

```bash
.venv/bin/python3 -m ruff format apps/api_server/src/agent_os_api/outcome_service.py apps/api_server/src/agent_os_api/http_app.py tests/unit/test_outcome_service.py tests/unit/test_http_app.py tests/unit/test_openapi_contract.py && PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeReviewQueueServiceTest tests.unit.test_outcome_service.KnowledgeReviewActionServiceTest tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest tests.unit.test_outcome_service.KnowledgeAssetQualitySummaryServiceTest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_review_queue_lists_draft_candidates tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_review_queue_filters_quality_triage tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_review_queue_paginates_filtered_candidates tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_review_queue_filters_review_rationale_code tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_review_action_approves_candidate tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_lists_reviewed_and_published_assets tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_orders_by_review_priority tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_filters_review_state tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_is_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_filters_status tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_review_queue_contract_declares_quality_triage_fields tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_catalog_item_contract_declares_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_quality_summary_contract_is_declared tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

Result: 33 tests OK.

Full branch CI:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result: Ruff check passed; format check passed; 606 primary unittest tests OK /
4 skipped; 12 eval tests OK; threshold report passed for 5 golden cases across
8 dimensions at 1.0 thresholds; OpenAPI contract was up to date; PostgreSQL full
local parity checks passed.

## Boundaries

- Internal-only and read-only.
- DRAFT assets remain non-consumable by default.
- No lifecycle/version/retrieval/feedback/adoption mutation.
- No raw trace payloads, source asset content, raw run parameters, related
  knowledge content, tool names on review-queue items, score-breakdown internals,
  correction payloads, metric deltas, or secret-like fields.
- No SQL Safety, EvidenceChain, Approval, connector, R4/R5, autonomous-core,
  G10, AGI, or autonomy claim changes.
