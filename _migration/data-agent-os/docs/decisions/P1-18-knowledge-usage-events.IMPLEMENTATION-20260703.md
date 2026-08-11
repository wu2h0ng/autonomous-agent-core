# P1-18 KnowledgeAsset Usage Events Implementation

Date: 2026-07-03
Layer: deployment
Branch: `codex/p1-18-knowledge-usage-events-20260703`
Status: branch-local verified; not merged, not pushed, not released

## Scope

P1-18 adds an internal read-only audit surface:

`GET /knowledge/assets/{asset_id}/usage-events`

The route answers a narrow operator question: where was this KnowledgeAsset id later referenced as decision/correction context?

It projects only safe usage metadata:

- `proposal_context` from persisted `action_proposal` events.
- `correction_context` from successful correction-channel `agent_runtime.tool_succeeded` events for `/outcomes` and `/adoptions`.
- Asset ids and trace ids only; no KnowledgeAsset title/content/full related knowledge, raw correction payload, metric deltas, reasons, or secret-like values.

## Implementation Notes

- `TraceStorePort` now exposes `all_traces()` for read-only audit enumeration.
- `InMemoryTraceStore` and `SqlTraceStore` implement `all_traces()`.
- `knowledge_asset_usage_events_service` verifies the target KnowledgeAsset exists before scanning traces.
- The HTTP route requires internal `knowledge:review` scope and denies `external_report`.
- Missing assets return `404 KNOWLEDGE_ASSET_NOT_FOUND`.
- OpenAPI snapshot includes the new route and response schema.

## Boundaries

This slice does not:

- mutate KnowledgeAsset lifecycle/version/retrieval/feedback/adoption state;
- promote adoption/value or create causal attribution claims;
- expose KnowledgeAsset titles/content/full related knowledge externally;
- change SQL Safety, EvidenceChain, Approval, connector routing, or R4/R5 behavior;
- reuse `/runs` ordering semantics for correction-channel events.

## Verification

Branch-local RED evidence:

- Service test failed because `knowledge_asset_usage_events_service` was absent.
- HTTP test failed with route `404`.
- OpenAPI contract test failed because `/knowledge/assets/{asset_id}/usage-events` was absent.

Branch-local GREEN evidence:

- Targeted suite passed: `22 tests OK`.
- `make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3` passed:
  - ruff clean;
  - format check clean;
  - `576` primary unittest tests OK / `4` skipped;
  - `12` eval tests OK;
  - threshold report passed for `5` golden cases across `8` dimensions at `1.0` thresholds;
  - OpenAPI contract up to date.
- `AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3` passed with the same primary/eval/OpenAPI gates and `Full local CI parity checks passed`.
