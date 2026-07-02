# P1-11 Knowledge Publish Lifecycle Implementation

Date: 2026-07-03
Branch: `codex/p1-11-knowledge-publish-lifecycle-20260703`
Base: deployment local `main@34673e8`
Status: branch-local implemented and full-verified; not pushed, not released

## Scope

This slice adds a bounded internal publish lifecycle for reviewed
KnowledgeAssets.

`LifecycleState` now includes `published`. A KnowledgeAsset must first be
reviewed from `draft` to `active`; only then can an internal reviewer publish it
through `POST /knowledge/assets/{asset_id}/publish`. Published assets remain
governed internal knowledge and are consumed by default retrieval alongside
`active` reviewed assets and external adopted value-backed assets.

## Entry Points

- Contract: `LifecycleState.PUBLISHED`
- Service: `knowledge_publish_service(...)`
- HTTP: `POST /knowledge/assets/{asset_id}/publish`
- Retrieval: default in-memory and SQL retrieval include `active`, `published`,
  or external adopted value-backed assets.
- Trace: `knowledge_publish_decision` event on the source RunTrace.
- OpenAPI snapshot: `apps/api_server/openapi.json`

## Boundaries

This is an internal lifecycle transition only.

It does not expose KnowledgeAsset titles/content externally, write feedback,
promote adoption/value, infer realized value, bypass review, lower governance,
execute business actions, export production telemetry, validate autonomous-core
or G10 product claims, or allow R4/R5 automatic execution.

Draft assets cannot be published directly. Deprecated assets cannot be
published. The publish route requires the same internal `knowledge:review` scope
as review actions; external-report principals remain denied.

## TDD Evidence

RED:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 \
  -m unittest \
  tests.unit.test_knowledge_retrieval.InMemoryKnowledgeRetrieverTest.test_default_search_consumes_only_reviewed_or_value_backed_assets \
  tests.unit.test_knowledge_retrieval_sql.SqlKnowledgeRetrievalTest.test_default_search_consumes_only_reviewed_or_value_backed_assets \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_publish_requires_active_asset -v
```

Result: failed because `LifecycleState.PUBLISHED` did not exist and
`/knowledge/assets/{asset_id}/publish` returned 404.

Targeted GREEN:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 \
  -m unittest \
  tests.unit.test_knowledge_retrieval \
  tests.unit.test_knowledge_retrieval_sql \
  tests.unit.test_outcome_service.KnowledgeReviewActionServiceTest \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest \
  tests.unit.test_openapi_contract -v
```

Result: 69 tests OK after regenerating the OpenAPI snapshot and explicitly
adding the publish route to the contract surface list.

Full verification:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Results:

- ruff check passed.
- ruff format check passed.
- primary unittest suite passed: 557 tests OK / 4 skipped.
- eval suite passed: 12 tests OK.
- threshold report passed: 5 golden cases across 8 dimensions met 1.0 thresholds.
- OpenAPI contract check passed.
- PostgreSQL `ci-local-full` parity passed.

## Product Claim

Reviewed KnowledgeAssets can now be promoted to an internal published lifecycle
state and continue to feed governed recall/search. This is product runtime
lifecycle governance, not external publication, not value promotion, and not an
autonomy or G10 validation claim.
