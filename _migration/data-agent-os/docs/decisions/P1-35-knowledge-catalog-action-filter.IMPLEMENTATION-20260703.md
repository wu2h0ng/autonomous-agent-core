# P1-35 Knowledge Catalog Action Filter Implementation

Date: 2026-07-03
Branch: `codex/p1-35-knowledge-catalog-action-filter-20260703`
Layer: deployment
Status: branch-local verified; not merged, pushed, or released

## Scope

Add a safe `recommended_review_action` filter to the internal read-only
`GET /knowledge/assets` catalog.

This extends the P1-33/P1-34 catalog review-state surface so internal reviewers
can narrow catalog triage by the same allowlisted recommended action already
derived from aggregate quality status:

- `review_or_reject`
- `collect_outcome_feedback`
- `monitor_for_adoption`
- `consider_publish`

The response echoes `recommended_review_action_filter` when the filter is
accepted.

## Product Boundary

This is a deployment-layer product slice for the phase-1 governed product
vertical. It improves the internal review operator path from prior outcomes and
KnowledgeAsset evidence back into the next review/proposal cycle.

It does not:

- expose raw `usage_trace_ids`, raw trace events, raw trace payloads, raw
  reasons, score breakdowns, correction payloads, `metric_deltas`, or
  secret-like fields
- mutate lifecycle, version, retrieval, feedback, adoption, approval, or
  connector state
- claim causal attribution or value realization
- bypass SQL Safety, EvidenceChain, Approval, Trace, or Eval
- change connector routing or allow R4/R5 automatic execution
- import autonomous-core code or claim autonomous-core/G10 validation in the OS

## TDD Evidence

RED failures observed before implementation:

```text
TypeError: knowledge_asset_catalog_service() got an unexpected keyword argument 'recommended_review_action'
KeyError: 'recommended_review_action_filter'
StopIteration
```

Targeted verification:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest.test_catalog_filters_safe_review_state_fields tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_filters_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_catalog_item_contract_declares_review_state -v
```

Result: 3 tests OK.

Related KnowledgeAsset/API/OpenAPI verification:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest tests.unit.test_outcome_service.KnowledgeAssetDetailServiceTest tests.unit.test_outcome_service.KnowledgeAssetDecisionQualityServiceTest tests.unit.test_outcome_service.KnowledgeAssetQualitySummaryServiceTest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_lists_reviewed_and_published_assets tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_filters_review_state tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_detail_is_read_only_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_decision_quality_is_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_is_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_filters_status tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_catalog_item_contract_declares_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_detail_contract_declares_review_state tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_quality_summary_contract_is_declared tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

Result: 22 tests OK.

Full local CI:

```text
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result: 594 primary unittest tests OK / 4 skipped, 12 eval tests OK, threshold
report passed with 5 golden cases across 8 dimensions at 1.0 thresholds, and
OpenAPI contract up to date.

PostgreSQL parity:

```text
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result: 594 primary unittest tests OK, 12 eval tests OK, threshold report
passed, OpenAPI contract up to date, and full local CI parity checks passed.

## Changed Files

- `apps/api_server/src/agent_os_api/outcome_service.py`
- `apps/api_server/src/agent_os_api/http_app.py`
- `apps/api_server/openapi.json`
- `tests/unit/test_outcome_service.py`
- `tests/unit/test_http_app.py`
- `tests/unit/test_openapi_contract.py`

## Engineering Gates

- Entry point: internal `GET /knowledge/assets`
- Contract: `KnowledgeAssetCatalogResponse` and OpenAPI snapshot
- Failure mode: unsupported `recommended_review_action` returns
  `KNOWLEDGE_CATALOG_INVALID_REQUEST`
- Test validity: tests assert accepted filtering, response echo, invalid filter
  rejection, and OpenAPI enum declaration
- Integration: internal API/service path only
- Boundary: OS Core remains domain-independent and free of external Agent
  framework runtime dependencies
- Observability: no trace or state mutation is introduced
*** End Patch
