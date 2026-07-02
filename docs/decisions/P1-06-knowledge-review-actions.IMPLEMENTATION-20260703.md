# P1-06 Implementation: KnowledgeAsset Review Actions

Date: 2026-07-03
Status: BRANCH-LOCAL IMPLEMENTATION VERIFIED - NOT MERGED/PUSHED/RELEASED
Branch: `codex/p1-06-knowledge-review-actions-20260703`
Base: deployment local `main@220caaa`

## Purpose

P1-05 made DRAFT `KnowledgeAsset` candidates reviewable as a queue. P1-06 adds
the smallest bounded human review action surface so those candidates can leave
the queue without pretending that review equals realized external value.

This is a lifecycle-review slice only:

- `approve` moves a DRAFT candidate to `active`;
- `reject` moves a DRAFT candidate to `deprecated`;
- both actions bump the knowledge version through the existing knowledge store;
- neither action records adoption, changes `result_weight`, writes feedback, or
  executes business actions.

## Entry Points

Service:

- `knowledge_review_action_service(runtime, asset_id, action, reviewer, reason)`

HTTP:

- `POST /knowledge/review-queue/{asset_id}/decision`

The HTTP route uses the same internal `knowledge:review` scope as the P1-05
queue. The external report key remains denied.

## Behavior

Request actions are intentionally limited to:

- `approve`;
- `reject`.

Invalid actions are rejected. Unknown assets return a not-found error. Already
reviewed non-DRAFT assets return conflict. The review queue continues to list
only DRAFT candidates, so reviewed assets disappear from the queue.

## Tests

RED was observed before implementation:

- service import failed before `knowledge_review_action_service` existed;
- HTTP `POST /knowledge/review-queue/{asset_id}/decision` returned 404 before
  the route existed;
- OpenAPI route/schema drift failed before regenerating `apps/api_server/openapi.json`.

Targeted GREEN:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest \
    tests.unit.test_outcome_service.KnowledgeReviewActionServiceTest \
    tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_review_action_approves_candidate \
    tests.unit.test_openapi_contract.OpenApiContractTest.test_contract_covers_all_trigger_surfaces \
    tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

Result: 6 tests OK on 2026-07-03.

Covered behavior:

- approving a real DRAFT candidate marks it `active`;
- rejecting a real DRAFT candidate marks it `deprecated`;
- review actions do not change `result_weight` or `outcome`;
- reviewed assets disappear from the DRAFT queue;
- unsupported actions fail closed;
- external report principals cannot use the review action route;
- a second decision on an already-reviewed asset returns conflict;
- OpenAPI includes the new route and request/response schemas.

Full branch verification:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Both passed on 2026-07-03. The full local parity gate reported ruff clean,
format check clean, 549 primary unittest tests OK / 4 skipped, 12 eval tests
OK, 5 golden threshold cases across 8 dimensions passing at 1.0 thresholds,
OpenAPI contract up to date, and `Full local CI parity checks passed`.

## Boundaries

This slice does not:

- implement publish workflow;
- claim realized external value;
- record adoption or feedback;
- alter adoption-driven promotion semantics;
- add persistent queue tables beyond the existing knowledge store;
- expose the route to external report principals;
- claim release readiness, production telemetry export, autonomous-core
  validation, or R4/R5 execution change.
