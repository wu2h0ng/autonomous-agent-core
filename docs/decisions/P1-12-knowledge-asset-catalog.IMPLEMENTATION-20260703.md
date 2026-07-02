# P1-12 KnowledgeAsset Catalog Implementation

Date: 2026-07-03
Branch: `codex/p1-12-knowledge-catalog-20260703`
Base: deployment local `main@d183400`
Status: Branch-local implemented and verified; not merged; not pushed; not released.

## Scope

P1-12 adds an internal read-only KnowledgeAsset catalog for lifecycle visibility after
the P1-05 through P1-11 review/publish path.

New surface:

- `GET /knowledge/assets`
- Query filter: `state=draft|active|published|deprecated|all`
- Default filter: `active,published`
- Scope: internal `knowledge:review`

The catalog returns safe operational metadata:

- `asset_id`
- `title`
- `asset_type`
- `source_trace_id`
- `owner`
- `state`
- `outcome`
- `result_weight`
- `knowledge_version`

## Boundary

This is an internal operator/governance visibility surface only. It does not:

- publish KnowledgeAsset content externally;
- expose the route to `external_report` principals;
- create, review, approve, reject, publish, deprecate, or mutate assets;
- write feedback;
- promote adoption/value;
- change retrieval ranking or default search behavior;
- bypass SQL Safety, EvidenceChain, Approval, Trace, or Eval;
- authorize R4/R5 automatic execution;
- validate autonomous-core/G10 product claims.

## RED

Before implementation, P1-12 tests failed for the intended reasons:

- `knowledge_asset_catalog_service` was missing.
- `GET /knowledge/assets` returned 404.
- OpenAPI trigger-surface coverage lacked `/knowledge/assets`.

Command:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_catalog_lists_reviewed_and_published_assets tests.unit.test_openapi_contract.OpenApiContractTest.test_contract_covers_all_trigger_surfaces -v
```

## GREEN

Implemented:

- `knowledge_asset_catalog_service` in `agent_os_api.outcome_service`.
- `KnowledgeAssetCatalogItem` / `KnowledgeAssetCatalogResponse` models.
- `GET /knowledge/assets` route in `agent_os_api.http_app`.
- OpenAPI snapshot path and contract coverage.
- Unit and HTTP tests for default active/published listing, explicit `state=all`,
  invalid state rejection, external-report denial, and no lifecycle mutation.

Targeted verification:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest tests.unit.test_outcome_service.KnowledgeReviewQueueServiceTest tests.unit.test_outcome_service.KnowledgeReviewActionServiceTest tests.unit.test_http_app.HttpAppSharedRuntimeTest tests.unit.test_http_app.HttpDefaultAppRecallTest tests.unit.test_knowledge_retrieval tests.unit.test_knowledge_retrieval_sql tests.unit.test_openapi_contract -v
```

Result:

- 78 tests OK.

## Full Verification

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

- Ruff check passed.
- Ruff format check passed.
- Primary unittest discovery passed: 560 tests OK / 4 skipped.
- Eval suite passed: 12 tests OK.
- Threshold report passed: 5 golden cases across 8 dimensions, all at 1.0 pass rate.
- OpenAPI contract check passed.

```bash
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

- Ruff check passed.
- Ruff format check passed.
- Primary unittest discovery passed: 560 tests OK / 4 skipped.
- Eval suite passed: 12 tests OK.
- Threshold report passed.
- OpenAPI contract check passed.
- Full local CI parity checks passed.

## Notes

`agent_workflow_runner` was unavailable in this environment, so the concurrency
claim degraded to isolated git worktree plus branch discipline:
`codex/p1-12-knowledge-catalog-20260703`.
