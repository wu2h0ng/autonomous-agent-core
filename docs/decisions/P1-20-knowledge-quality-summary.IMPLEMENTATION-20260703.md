# P1-20 KnowledgeAsset Quality Summary Implementation

Date: 2026-07-03
Layer: deployment
Branch: `codex/p1-20-knowledge-quality-summary-20260703`
Status: branch-local verified; not merged, not pushed, not released

## Scope

P1-20 adds an internal read-only quality catalog surface:

`GET /knowledge/assets/quality-summary`

The route lists safe per-asset quality signals so an internal reviewer can scan which
KnowledgeAssets are unused, proposal-only, outcome-observed, or adoption-observed.
It is a collection-level summary over the P1-19 single-asset decision-quality drill-down.

Each item reports only safe metadata:

- asset id;
- source trace id;
- lifecycle state;
- proposal usage count;
- correction usage count;
- outcome correction count;
- adoption correction count;
- distinct usage trace count;
- derived quality status.

## Implementation Notes

- `knowledge_asset_quality_summary_service` iterates `KnowledgeStorePort.all_assets()`.
- Per-asset counts reuse `knowledge_asset_decision_quality_service` so the summary and drill-down have the same trace-event interpretation.
- `quality_status` is derived deterministically:
  - `adoption_observed` when adoption correction count is greater than zero;
  - `outcome_observed` when outcome correction count is greater than zero;
  - `proposal_only` when proposal usage count is greater than zero;
  - `unused` otherwise.
- The HTTP route is registered before `/knowledge/assets/{asset_id}` so the static collection route is not captured as an asset id.
- The route requires internal `knowledge:review` scope and denies `external_report`.
- OpenAPI snapshot includes the new route and response schemas.

## Boundaries

This slice does not:

- mutate KnowledgeAsset lifecycle/version/retrieval/feedback/adoption state;
- expose KnowledgeAsset titles/content/full related knowledge;
- expose raw usage trace ids in the collection summary;
- expose raw correction payloads, metric deltas, raw reasons, or secret-like fields;
- create causal/value attribution claims;
- change SQL Safety, EvidenceChain, Approval, connector routing, or R4/R5 behavior;
- replace the P1-19 single-asset decision-quality drill-down.

## Verification

Branch-local RED evidence:

- Service test failed because `knowledge_asset_quality_summary_service` was absent.
- HTTP test failed because `/knowledge/assets/quality-summary` was captured by the dynamic `/knowledge/assets/{asset_id}` route and returned `404 KNOWLEDGE_ASSET_NOT_FOUND`.
- OpenAPI contract test failed because `/knowledge/assets/quality-summary` was absent.

Branch-local GREEN evidence:

- Targeted suite passed: `3 tests OK`.
- Related KnowledgeAsset/OpenAPI suite passed: `21 tests OK`.
- `make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3` passed:
  - ruff clean;
  - format check clean;
  - `583` primary unittest tests OK / `4` skipped;
  - `12` eval tests OK;
  - threshold report passed for `5` golden cases across `8` dimensions at `1.0` thresholds;
  - OpenAPI contract up to date.
- `AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3` passed with the same primary/eval/OpenAPI gates and `Full local CI parity checks passed`.
