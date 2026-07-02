# P1-10 Internal Knowledge Context Projection Implementation

Date: 2026-07-03
Branch: `codex/p1-10-internal-knowledge-context-projection-20260703`
Base: deployment local `main@6513fbe`
Status: branch-local implemented and full-verified; not pushed, not released

## Scope

This slice projects the P1-09 proposal context onto the internal user-facing
decision artifact.

When a run recalls reviewed/value-backed KnowledgeAssets, internal
`user_result.decision.knowledge_context_refs` now exposes the consumed
KnowledgeAsset asset ids. External audience projections receive an empty list.

This makes the internal product surface auditable without copying KnowledgeAsset
titles/content into recommendation text or external reports.

## Entry Points

- API model: `UserResultDecision.knowledge_context_refs`
- Read projection: `_build_user_result_artifact(..., audience=...)`
- HTTP surface: `POST /runs` `user_result.decision.knowledge_context_refs`
- OpenAPI snapshot: `apps/api_server/openapi.json`

## Boundaries

This is a read-side projection only.

It does not change recall ranking, EvidenceChain, SQL Safety, recommendation
text, risk tier, approval, connector routing, action execution, feedback
writing, adoption/value promotion, KnowledgeAsset publish workflow, or R4/R5
execution policy.

Only safe asset id references are exposed internally. External audience
projection hides them by returning an empty list.

## TDD Evidence

RED:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 \
  -m unittest tests.unit.test_http_app.HttpDefaultAppRecallTest.test_runs_response_carries_related_knowledge -v
```

Result: failed with `None != ['knowledge-...']` because internal
`user_result.decision` did not expose `knowledge_context_refs`.

Targeted GREEN:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 \
  -m unittest \
  tests.unit.test_http_app.HttpDefaultAppRecallTest.test_runs_response_carries_related_knowledge \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_run_response_redacts_external_audience_result_details \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_external_api_key_forces_external_user_result_projection \
  tests.unit.test_outcome_service \
  tests.unit.test_openapi_contract -v
```

Result: 35 tests OK.

Full verification:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Results:

- ruff check passed.
- ruff format check passed.
- primary unittest suite passed: 556 tests OK / 4 skipped.
- eval suite passed: 12 tests OK.
- threshold report passed: 5 golden cases across 8 dimensions met 1.0 thresholds.
- OpenAPI contract check passed.
- PostgreSQL `ci-local-full` parity passed.

## Product Claim

Internal decision artifacts now show which reviewed/value-backed KnowledgeAsset
ids influenced the proposal context. This is product runtime auditability, not
autonomous-core validation, G10 validation, or a release claim.
