# P1-13 KnowledgeAsset Deprecate Lifecycle Implementation

Date: 2026-07-03
Branch: `codex/p1-13-knowledge-deprecate-lifecycle-20260703`
Layer: deployment / phase-1 governed product vertical
Status: branch-local implementation verified; not merged, not pushed, not released

## Scope

P1-13 adds an internal correction lifecycle transition for reviewed
KnowledgeAssets:

- `POST /knowledge/assets/{asset_id}/deprecate`
- `knowledge_deprecate_service`
- OpenAPI contract entry for the new route

The transition allows only `active` or `published` KnowledgeAssets to move to
`deprecated`. Draft candidates still must use the review queue reject path.
Deprecated assets remain stored and auditable, but the existing default
retrieval/catalog behavior excludes them from normal consumption.

## Boundaries

This slice does not:

- publish KnowledgeAssets externally
- expose KnowledgeAsset titles/content to external report principals
- infer value or mutate `outcome` / `result_weight`
- write feedback or adoption records
- change evidence, SQL Safety, provider, approval, connector, or R4/R5 behavior
- validate autonomous-core/G10 claims in the enterprise domain

## Audit Behavior

Successful deprecation appends a safe `knowledge_deprecate_decision` event to
the source `RunTrace`. The payload includes lifecycle metadata, reviewer,
knowledge version, and `reason_present`, but it does not store raw reason text.

The service fails closed before mutation when the source trace is not persisted.

## TDD Evidence

RED failures before implementation:

- `knowledge_deprecate_service` missing
- `POST /knowledge/assets/{asset_id}/deprecate` returned 404
- OpenAPI snapshot lacked `/knowledge/assets/{asset_id}/deprecate`

Targeted GREEN:

```text
75 tests OK
```

Covered suites:

- `tests.unit.test_outcome_service.KnowledgeDeprecateServiceTest`
- `tests.unit.test_outcome_service.KnowledgeAssetCatalogServiceTest`
- `tests.unit.test_outcome_service.KnowledgeReviewActionServiceTest`
- `tests.unit.test_http_app.HttpAppSharedRuntimeTest`
- `tests.unit.test_openapi_contract`
- `tests.unit.test_knowledge_retrieval`
- `tests.unit.test_knowledge_retrieval_sql`

## Branch-Local Verification

```text
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

```text
ruff clean
format check clean
563 primary unittest tests OK / 4 skipped
12 eval tests OK
threshold-report gate passed: 5 golden cases across 8 dimensions at 1.0 thresholds
OpenAPI contract up to date
```

```text
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

```text
563 primary unittest tests OK / 4 skipped
12 eval tests OK
threshold-report gate passed
OpenAPI contract up to date
Full local CI parity checks passed
```

## Gate State

Branch-local verification is complete. Local ff-only merge to deployment `main`
requires explicit founder/CTO authorization and post-merge `make ci` plus
PostgreSQL `ci-local-full`. Push and release remain separate gates.
