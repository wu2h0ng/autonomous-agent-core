# P1-05 Implementation: KnowledgeAsset Review Queue

Date: 2026-07-03
Status: BRANCH-LOCAL IMPLEMENTATION VERIFIED - NOT MERGED/PUSHED/RELEASED
Branch: `codex/p1-05-knowledge-review-queue-20260703`
Base: deployment local `main@8a1b91e`

## Purpose

P1-05 needs KnowledgeAsset candidates to become reviewable operational objects,
not only trace events or static workspace labels. This slice adds a minimal
read-only review queue over the existing Trusted Loop knowledge store.

The trigger is concrete: every successful Trusted Loop run already sediments a
DRAFT `KnowledgeAsset` candidate, and the first review-queue test creates three
real candidates through `run_service` before listing them.

## Entry Points

Service:

- `knowledge_review_queue_service(runtime)`

HTTP:

- `GET /knowledge/review-queue`

The HTTP route requires the internal API key and the new `knowledge:review`
scope. The external report key is denied with `403`, because this is a
management/review surface rather than an external report projection.

## Behavior

The queue returns:

- `status`;
- `review_state`;
- `count`;
- `items[]` with `asset_id`, `title`, `asset_type`, `source_trace_id`,
  `owner`, `state`, `outcome`, `result_weight`, and `knowledge_version`.

It lists only DRAFT candidates and is read-only. It does not create assets,
promote versions, publish assets, infer realized value, or change adoption /
outcome semantics.

## Tests

RED was observed before implementation:

- `knowledge_review_queue_service` import failed before the service existed;
- `GET /knowledge/review-queue` returned 404 before the route existed;
- OpenAPI snapshot drift failed after adding the route and before regenerating
  `apps/api_server/openapi.json`.

Targeted GREEN:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  .venv/bin/python3 -m unittest \
    tests.unit.test_outcome_service.KnowledgeReviewQueueServiceTest.test_lists_three_draft_candidates_without_mutating_store \
    tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_review_queue_lists_draft_candidates \
    tests.unit.test_openapi_contract.OpenApiContractTest.test_contract_covers_all_trigger_surfaces \
    tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

Covered behavior:

- three real `run_service` calls create three DRAFT review candidates;
- service listing preserves source trace order and does not mutate version
  counts;
- HTTP internal key can read the queue;
- external report key is denied from the review queue;
- OpenAPI contract includes `/knowledge/review-queue` and the response schemas.

Full branch verification:

```bash
make ci PYTHON=.venv/bin/python3
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=.venv/bin/python3
```

Both passed on 2026-07-03. The full local parity gate reported ruff clean,
format check clean, 545 primary unittest tests OK / 4 skipped, 12 eval tests
OK, 5 golden threshold cases across 8 dimensions passing at 1.0 thresholds,
OpenAPI contract up to date, and `Full local CI parity checks passed`.

## Boundaries

This slice does not:

- implement publish/approve/reject workflow;
- add persistent queue tables beyond the existing knowledge store;
- change adoption-driven promotion or self-report non-promotion;
- expose the review queue to external report principals;
- claim release readiness, production telemetry export, autonomous-core
  validation, or R4/R5 execution change.
