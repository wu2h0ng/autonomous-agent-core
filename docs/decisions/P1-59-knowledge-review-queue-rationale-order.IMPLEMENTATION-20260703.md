# P1-59 Knowledge Review Queue Rationale Order Implementation

Date: 2026-07-03
Branch: `codex/p1-59-knowledge-review-queue-rationale-order-20260703`
Status: branch-local implementation verified; not merged, pushed, or released.

## Goal

Add deterministic rationale-code ordering to the internal KnowledgeAsset review
queue so reviewers can page DRAFT candidates by the safe reason they need
attention. This extends P1-58 rationale filtering without changing lifecycle,
retrieval, feedback, adoption, or execution behavior.

## TDD Red

Command:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python -m unittest tests.unit.test_outcome_service.KnowledgeReviewQueueServiceTest.test_orders_draft_candidates_by_review_rationale_code_before_pagination tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_review_queue_orders_review_rationale_code tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_review_queue_contract_declares_quality_triage_fields -v
```

Expected failures confirmed:

- Service rejected `order_by=review_rationale_code` with
  `Unsupported order_by`.
- HTTP response validation rejected `order_by="review_rationale_code"` because
  the review-queue response model only allowed `review_priority`.
- The committed OpenAPI snapshot still declared only `review_priority`.

## Implementation

- `knowledge_review_queue_service(...)` now uses a review-queue-specific
  `order_by` allowlist: `review_priority` and `review_rationale_code`.
- `order_by=review_rationale_code` sorts DRAFT review candidates by the existing
  safe rationale-code order, then by `asset_id` and `source_trace_id`, before
  pagination.
- `KnowledgeReviewQueueResponse.order_by` now accepts
  `review_rationale_code`.
- `GET /knowledge/review-queue` declares the review-queue-specific order enum.
- `apps/api_server/openapi.json` was regenerated and checked.

## Verification

Focused GREEN:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python -m unittest tests.unit.test_outcome_service.KnowledgeReviewQueueServiceTest.test_orders_draft_candidates_by_review_rationale_code_before_pagination tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_review_queue_orders_review_rationale_code tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_review_queue_contract_declares_quality_triage_fields -v
```

Result: 4 tests OK.

Related regression set:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python -m unittest tests.unit.test_outcome_service.KnowledgeReviewQueueServiceTest tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest tests.unit.test_outcome_service.KnowledgeAssetQualitySummaryServiceTest tests.unit.test_http_app.HttpAppSharedRuntimeTest tests.unit.test_openapi_contract.OpenApiContractTest -v
```

Result: 88 tests OK.

Full branch CI:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result: Ruff check passed; format check passed; 608 primary unittest tests OK /
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
