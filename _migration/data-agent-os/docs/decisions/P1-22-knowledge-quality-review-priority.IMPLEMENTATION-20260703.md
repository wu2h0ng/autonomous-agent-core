# P1-22 KnowledgeAsset Quality Review Priority Implementation

Date: 2026-07-03
Layer: deployment
Branch: `codex/p1-22-knowledge-quality-review-priority-20260703`
Status: branch-local implemented and verified; not merged, not pushed, not released

## Scope

P1-22 extends the internal read-only `GET /knowledge/assets/quality-summary`
surface with reviewer action hints:

- `review_priority`: `high|medium|low`;
- `recommended_review_action`:
  `review_or_reject|collect_outcome_feedback|monitor_for_adoption|consider_publish`.

The fields are derived only from the existing safe quality status:

- `unused` -> `high`, `review_or_reject`;
- `proposal_only` -> `medium`, `collect_outcome_feedback`;
- `outcome_observed` -> `medium`, `monitor_for_adoption`;
- `adoption_observed` -> `high`, `consider_publish`.

This is a review queue aid, not an automatic lifecycle transition or value
claim.

## Implementation

- `knowledge_asset_quality_summary_service` now projects `review_priority` and
  `recommended_review_action` on each summary item.
- `KnowledgeAssetQualitySummaryItem` declares both fields as typed OpenAPI
  enums.
- `apps/api_server/openapi.json` was regenerated from the live app schema.

## TDD Record

RED:

- `KnowledgeAssetQualitySummaryServiceTest.test_returns_safe_quality_catalog_without_mutation`
  failed with `KeyError: 'review_priority'`;
- `HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_is_safe_and_guarded`
  failed with `KeyError: 'review_priority'`;
- `OpenApiContractTest.test_knowledge_asset_quality_summary_contract_is_declared`
  failed because `review_priority` and `recommended_review_action` were absent
  from the committed schema.

GREEN:

- added derived review-priority/action fields in the service;
- added typed response-model fields;
- regenerated the OpenAPI snapshot.

## Verification

Targeted RED/GREEN suite:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetQualitySummaryServiceTest.test_returns_safe_quality_catalog_without_mutation tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_is_safe_and_guarded tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_quality_summary_contract_is_declared -v
```

Result: `3 tests OK` after implementation.

Related KnowledgeAsset/OpenAPI suite:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetUsageEventsServiceTest tests.unit.test_outcome_service.KnowledgeAssetDecisionQualityServiceTest tests.unit.test_outcome_service.KnowledgeAssetQualitySummaryServiceTest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_usage_events_are_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_decision_quality_is_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_is_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_filters_status tests.unit.test_openapi_contract -v
```

Result: `23 tests OK`.

Branch-local standard CI:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

- ruff clean;
- format check clean;
- `585` primary unittest tests OK / `4` skipped;
- `12` eval tests OK;
- threshold report passed for `5` golden cases across `8` dimensions at `1.0` thresholds;
- OpenAPI contract up to date.

Branch-local PostgreSQL parity:

```bash
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

- `585` primary unittest tests OK / `4` skipped;
- `12` eval tests OK;
- threshold report passed for `5` golden cases across `8` dimensions at `1.0` thresholds;
- OpenAPI contract up to date;
- Full local CI parity checks passed.

## Boundary

This branch does not merge, push, release, expose KnowledgeAsset titles/content/
full related knowledge externally, expose raw usage trace ids from the collection
summary, claim causal attribution/value for context refs, claim autonomous-core
or G10 product validation, change feedback/adoption promotion rules, mutate
KnowledgeAsset lifecycle/version/retrieval/feedback/adoption state, change SQL
Safety/EvidenceChain/Approval, or allow R4/R5 automatic execution.
