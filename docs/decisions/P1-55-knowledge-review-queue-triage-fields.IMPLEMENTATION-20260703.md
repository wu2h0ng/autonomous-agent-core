# P1-55 Knowledge Review Queue Triage Fields Implementation

Date: 2026-07-03
Branch: `codex/p1-55-knowledge-review-queue-usage-summary-20260703`
Status: branch-local implementation verified; not merged, pushed, or released

## Goal

Expose safe quality/usage triage fields on internal `GET /knowledge/review-queue`
items. The review queue is the first human-review screen for DRAFT
KnowledgeAssets, so reviewers should see the same safe quality status,
recommended action, and usage counters used by later catalog/detail surfaces.

Because DRAFT assets are not consumed by default, `latest_usage_event` remains
nullable and is normally `null` for queue items. This preserves the reviewed-only
consumption gate while making that fact explicit in the review surface.

## TDD Evidence

RED command:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeReviewQueueServiceTest.test_lists_three_draft_candidates_without_mutating_store tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_review_queue_lists_draft_candidates tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_review_queue_contract_declares_quality_triage_fields -v
```

Expected RED result:

- service and HTTP review-queue items raised `KeyError` for missing
  `latest_usage_event`;
- OpenAPI `KnowledgeReviewQueueItem` did not require the quality/usage triage
  fields.

GREEN command:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeReviewQueueServiceTest.test_lists_three_draft_candidates_without_mutating_store tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_review_queue_lists_draft_candidates tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_review_queue_contract_declares_quality_triage_fields tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

GREEN result: 4 tests OK.

## Implementation

- `knowledge_review_queue_service` now projects safe quality/usage triage fields
  for each DRAFT item by reusing existing quality and latest-usage helpers.
- `KnowledgeReviewQueueItem` and `apps/api_server/openapi.json` declare nullable
  `KnowledgeAssetUsageEventSummary`, usage counters, quality status, review
  priority, recommended action, and rationale codes.
- The route remains internal-only and read-only.

## Verification

Related subset:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeReviewQueueServiceTest tests.unit.test_outcome_service.KnowledgeReviewActionServiceTest tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest tests.unit.test_outcome_service.KnowledgeAssetDetailServiceTest tests.unit.test_outcome_service.KnowledgeAssetQualitySummaryServiceTest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_review_queue_lists_draft_candidates tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_review_action_approves_candidate tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_lists_reviewed_and_published_assets tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_detail_is_read_only_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_is_safe_and_guarded tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_review_queue_contract_declares_quality_triage_fields tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_catalog_item_contract_declares_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_detail_contract_declares_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_quality_summary_contract_is_declared tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

Result: 28 tests OK.

Full verification:

```text
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

- Ruff check passed
- Ruff format check passed
- Primary unittest discovery: 600 tests OK / 4 skipped
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
- Primary unittest discovery: 600 tests OK
- Eval tests: 12 OK
- Threshold report: 5 golden cases across 8 dimensions passed at 1.0 thresholds
- OpenAPI contract up to date
- Full local CI parity checks passed

## Boundary

- Internal-only: requires `knowledge:review` scope.
- Read-only: does not mutate lifecycle, version, retrieval, feedback, adoption,
  connector routing, approval state, or quality scoring.
- DRAFT consumption remains blocked by default; this slice does not make
  unreviewed draft assets available to retrieval/search/recall.
- Safe projection only: exposes quality/usage summary fields, not usage event
  bodies, raw trace payloads, source asset content, raw run parameters, related
  knowledge content, tool names on review-queue items, correction payloads,
  metric_deltas, or secret-like fields.
- Product/process boundary: this is an Enterprise OS KnowledgeAsset review
  triage slice, not an autonomous-core, G10, AGI, causal/value attribution,
  adoption/value-promotion, or R4/R5 execution claim.
