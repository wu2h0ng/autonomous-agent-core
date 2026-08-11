# P1-21 KnowledgeAsset Quality Filter Implementation

Date: 2026-07-03
Layer: deployment
Branch: `codex/p1-21-knowledge-quality-filter-20260703`
Status: branch-local verified; not merged, not pushed, not released

## Scope

P1-21 adds an internal filter to the P1-20 quality summary surface:

`GET /knowledge/assets/quality-summary?quality_status=<status>`

Allowed values:

- `unused`;
- `proposal_only`;
- `outcome_observed`;
- `adoption_observed`.

The filter lets an internal reviewer directly inspect KnowledgeAssets that need
attention, such as proposal-only assets without correction evidence or unused
drafts, without exposing asset content or raw trace payloads.

## Implementation Notes

- `knowledge_asset_quality_summary_service` accepts an optional `quality_status`
  filter.
- The service normalizes and validates the filter before scanning assets.
- Invalid filters raise `ValueError`.
- The HTTP route converts invalid filters into `400
  KNOWLEDGE_QUALITY_SUMMARY_INVALID_REQUEST`.
- The response includes `quality_status_filter` so callers can verify whether a
  filter was applied.
- OpenAPI declares the query parameter enum and the 400 response.

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

- Service test failed because `knowledge_asset_quality_summary_service` did not
  accept a `quality_status` keyword.
- HTTP test failed because the response did not include `quality_status_filter`
  and the filter was not applied.
- OpenAPI contract test failed because the route did not declare the query
  parameter.

Branch-local GREEN evidence:

- Targeted suite passed: `3 tests OK`.
- Related KnowledgeAsset/OpenAPI suite passed: `23 tests OK`.
- `make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3` passed:
  - ruff clean;
  - format check clean;
  - `585` primary unittest tests OK / `4` skipped;
  - `12` eval tests OK;
  - threshold report passed for `5` golden cases across `8` dimensions at `1.0` thresholds;
  - OpenAPI contract up to date.
- `AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3` passed with the same primary/eval/OpenAPI gates and `Full local CI parity checks passed`.
