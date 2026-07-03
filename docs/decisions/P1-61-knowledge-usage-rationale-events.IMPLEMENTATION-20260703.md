# P1-61 Knowledge Usage Rationale Events Implementation

Date: 2026-07-03
Branch: `codex/p1-61-knowledge-usage-rationale-events-20260703`
Status: branch-local verified; not merged, pushed, or released.

## Goal

Extend the internal `GET /knowledge/assets/{asset_id}/usage-events` audit
surface so correction-context usage events include the same safe
`knowledge_context_rationale` projection introduced for `/outcomes` and
`/adoptions` in P1-60.

This moves the feedback loop one step closer to a durable reviewer/operator
surface: an internal reviewer can see not only that a KnowledgeAsset was reused
in a correction context, but the allowlisted reason metadata for that reuse.

## Implementation

- Added `knowledge_context_rationale` to `KnowledgeAssetUsageEventItem`.
- Kept `KnowledgeAssetUsageEventSummary` unchanged so catalog/latest-summary
  surfaces do not expand.
- Reused persisted trace data:
  - `action_proposal.knowledge_context_refs`
  - `knowledge_recall.asset_ids`
  - `knowledge_recall.scores`
  - `knowledge_recall.quality_boosts`
- Projected rationale only for `agent_runtime.tool_succeeded` correction usage
  events and only for the requested asset id.
- Kept proposal-context events at an empty rationale list.

## TDD Evidence

RED:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python -m unittest tests.unit.test_outcome_service.KnowledgeAssetUsageEventsServiceTest.test_returns_safe_usage_events_without_asset_content_or_mutation tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_usage_events_are_safe_and_guarded tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_usage_events_contract_is_declared -v
```

Expected failure observed:

- Service `KeyError: 'knowledge_context_rationale'`.
- OpenAPI schema missing `knowledge_context_rationale`.
- The first HTTP command used a stale method name and was corrected before
  GREEN verification.

Focused GREEN:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python -m unittest tests.unit.test_outcome_service.KnowledgeAssetUsageEventsServiceTest.test_returns_safe_usage_events_without_asset_content_or_mutation tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_usage_events_are_safe_and_guarded tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_usage_events_contract_is_declared tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

Result: 4 tests OK.

Related regression:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python -m unittest tests.unit.test_outcome_service.KnowledgeAssetUsageEventsServiceTest tests.unit.test_outcome_service.KnowledgeAssetDecisionQualityServiceTest tests.unit.test_outcome_service.KnowledgeAssetQualitySummaryServiceTest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_usage_events_are_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_decision_quality_is_safe_and_guarded tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_knowledge_asset_quality_summary_is_safe_and_guarded tests.unit.test_openapi_contract.OpenApiContractTest.test_knowledge_asset_usage_events_contract_is_declared tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

Result: 14 tests OK.

Full branch CI:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result: Ruff check passed; format check passed; 609 primary unittest tests OK /
4 skipped; 12 eval tests OK; threshold report passed for 5 golden cases across
8 dimensions at 1.0 thresholds; OpenAPI contract was up to date; PostgreSQL full
local parity checks passed.

## Boundaries

- Internal usage-events surface only.
- No external report projection.
- No KnowledgeAsset title/content exposure.
- No raw trace payload, raw run parameter, tool output, related knowledge body,
  metric delta, score-breakdown internals, or secret-like field exposure.
- No lifecycle/review/retrieval/feedback/adoption mutation.
- No change to KnowledgeAsset quality status, review priority, or catalog latest
  usage summary.
- No SQL Safety, EvidenceChain, Approval, connector routing, R4/R5, G10,
  autonomous-core, AGI, push, or release claim.
