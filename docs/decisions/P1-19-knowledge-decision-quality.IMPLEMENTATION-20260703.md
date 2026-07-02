# P1-19 KnowledgeAsset Decision Quality Implementation

Date: 2026-07-03
Layer: deployment
Branch: `codex/p1-19-knowledge-decision-quality-20260703`
Status: branch-local verified; not merged, not pushed, not released

## Scope

P1-19 adds an internal read-only aggregate surface:

`GET /knowledge/assets/{asset_id}/decision-quality`

The route summarizes whether a reviewed KnowledgeAsset id has been reused in later governed decisions and whether those later decisions have correction-channel evidence.

It reports only safe aggregate metadata:

- proposal usage count;
- correction usage count;
- outcome correction count;
- adoption correction count;
- distinct usage trace count;
- usage trace ids.

## Implementation Notes

- `knowledge_asset_decision_quality_service` scans persisted trace events through the existing `TraceStorePort.all_traces()` read surface.
- `action_proposal` events with `knowledge_context_refs` count as proposal usage.
- Successful correction-channel `agent_runtime.tool_succeeded` events count only when their tool is `trusted_loop.record_outcome` or `trusted_loop.attest_adoption`.
- The HTTP route requires internal `knowledge:review` scope and denies `external_report`.
- Missing assets return `404 KNOWLEDGE_ASSET_NOT_FOUND`.
- OpenAPI snapshot includes the new route and response schema.

## Boundaries

This slice does not:

- mutate KnowledgeAsset lifecycle/version/retrieval/feedback/adoption state;
- promote adoption/value or create causal attribution claims;
- expose KnowledgeAsset titles/content/full related knowledge;
- expose raw correction payloads, metric deltas, raw reasons, or secret-like fields;
- change SQL Safety, EvidenceChain, Approval, connector routing, or R4/R5 behavior;
- reuse `/runs` ordering semantics for correction-channel events.

## Verification

Branch-local RED evidence:

- Service tests failed because `knowledge_asset_decision_quality_service` was absent.
- HTTP test failed with route `404`.
- OpenAPI contract test failed because `/knowledge/assets/{asset_id}/decision-quality` was absent.

Branch-local GREEN evidence:

- Targeted suite passed: `4 tests OK`.
- Related KnowledgeAsset/OpenAPI suite passed: `18 tests OK`.
- `make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3` passed:
  - ruff clean;
  - format check clean;
  - `580` primary unittest tests OK / `4` skipped;
  - `12` eval tests OK;
  - threshold report passed for `5` golden cases across `8` dimensions at `1.0` thresholds;
  - OpenAPI contract up to date.
- `AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3` passed with the same primary/eval/OpenAPI gates and `Full local CI parity checks passed`.
