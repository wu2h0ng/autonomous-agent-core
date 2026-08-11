# P1-25 KnowledgeAsset Quality Review Counts Implementation

Date: 2026-07-03
Layer: deployment
Branch: `codex/p1-25-knowledge-quality-review-counts-20260703`
Status: branch-local implemented and verified; not merged, not pushed, not released

## Scope

P1-25 extends the internal read-only `GET /knowledge/assets/quality-summary`
reviewer surface with safe queue facet counts:

- `quality_status_counts`;
- `review_priority_counts`;
- `recommended_review_action_counts`.

The counts are computed from the currently returned `items`, so they respect
existing `quality_status`, `review_priority`, `recommended_review_action`, and
`order_by` request semantics. All count maps use stable allowlisted keys and
include zero values for absent buckets.

This is an internal reviewer backlog/readiness slice. It does not mutate
KnowledgeAsset lifecycle/version/retrieval/feedback/adoption state and does not
create automatic review, publish, reject, adoption, value, or action-execution
behavior.

## Implementation

- `knowledge_asset_quality_summary_service` now returns three allowlisted count
  maps alongside the existing filtered `count` and `items`.
- `KnowledgeAssetQualitySummaryResponse` declares the three count maps.
- `apps/api_server/openapi.json` was regenerated from the live FastAPI app.

## TDD Evidence

RED:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetQualitySummaryServiceTest.test_returns_safe_quality_catalog_without_mutation tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_is_safe_and_guarded tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_quality_summary_contract_is_declared -v
```

Expected failures were observed:

- service response lacked `quality_status_counts`;
- HTTP response lacked `quality_status_counts`;
- OpenAPI response required fields lacked the three count maps.

GREEN targeted suite:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetQualitySummaryServiceTest.test_returns_safe_quality_catalog_without_mutation tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_is_safe_and_guarded tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_quality_summary_contract_is_declared -v
```

Result: `3` tests OK.

Related KnowledgeAsset/OpenAPI suite:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetUsageEventsServiceTest tests.unit.test_outcome_service.KnowledgeAssetDecisionQualityServiceTest tests.unit.test_outcome_service.KnowledgeAssetQualitySummaryServiceTest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_usage_events_are_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_decision_quality_is_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_is_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_filters_status tests.unit.test_openapi_contract -v
```

Result: `24` tests OK.

Branch-local CI:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

- ruff clean;
- format check clean;
- `586` primary unittest tests OK / `4` skipped;
- `12` eval tests OK;
- threshold report passed for `5` golden cases across `8` dimensions at `1.0`
  thresholds;
- OpenAPI contract up to date.

Branch-local PostgreSQL parity:

```bash
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

- ruff clean;
- format check clean;
- `586` primary unittest tests OK / `4` skipped;
- `12` eval tests OK;
- threshold report passed for `5` golden cases across `8` dimensions at `1.0`
  thresholds;
- OpenAPI contract up to date;
- Full local CI parity checks passed.

## Boundary

This branch does not merge, push, release, expose KnowledgeAsset titles/content/
full related knowledge externally, expose raw usage trace ids from the collection
summary, claim causal attribution/value for context refs, claim autonomous-core
or G10 product validation, change feedback/adoption promotion rules, mutate
KnowledgeAsset lifecycle/version/retrieval/feedback/adoption state from
filter/recommendation/order/count fields, change SQL Safety/EvidenceChain/
Approval, or allow R4/R5 automatic execution.
