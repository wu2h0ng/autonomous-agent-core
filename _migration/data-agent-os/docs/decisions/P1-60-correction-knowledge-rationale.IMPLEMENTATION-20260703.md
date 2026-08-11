# P1-60 Correction Knowledge Rationale Implementation

Date: 2026-07-03
Branch: `codex/p1-60-correction-knowledge-rationale-20260703`
Status: branch-local implementation verified; not merged, pushed, or released.

## Goal

Expose safe `knowledge_context_rationale` on `/outcomes` and `/adoptions`
responses so correction and adoption records can show why the prior proposal
used each KnowledgeAsset context reference. This closes an audit gap in the
feedback loop without exposing KnowledgeAsset content, raw trace payloads, or
score-breakdown internals.

## TDD Red

Command:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python -m unittest tests.unit.test_outcome_service.RecordOutcomeServiceTest.test_correction_responses_project_used_knowledge_context_refs tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_correction_responses_project_used_knowledge_context_refs tests.unit.test_openapi_contract.OpenApiContractTest.test_correction_responses_declare_knowledge_context_refs -v
```

Expected failures confirmed:

- Service responses lacked `knowledge_context_rationale`.
- HTTP `/outcomes` and `/adoptions` responses lacked
  `knowledge_context_rationale`.
- The committed OpenAPI snapshot did not declare the field on
  `OutcomeResponse` or `AdoptionResponse`.

## Implementation

- Added a trace-derived helper that reconstructs safe rationale from persisted
  `action_proposal` and `knowledge_recall` metadata.
- `/outcomes` and `/adoptions` service responses now include
  `knowledge_context_rationale`.
- HTTP `OutcomeResponse` and `AdoptionResponse` now declare
  `knowledge_context_rationale: list[KnowledgeContextRationaleItem]`.
- `apps/api_server/openapi.json` was regenerated and checked.

## Verification

Focused GREEN:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python -m unittest tests.unit.test_outcome_service.RecordOutcomeServiceTest.test_correction_responses_project_used_knowledge_context_refs tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_correction_responses_project_used_knowledge_context_refs tests.unit.test_openapi_contract.OpenApiContractTest.test_correction_responses_declare_knowledge_context_refs tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

Result: 5 tests OK.

Related regression set:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src .venv/bin/python -m unittest tests.unit.test_outcome_service.RecordOutcomeServiceTest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_correction_responses_project_used_knowledge_context_refs tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_outcomes_traverse_agent_runtime_envelope_without_knowledge_promotion tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_adoptions_traverse_runtime_envelope_and_preserve_writer_authority tests.unit.test_openapi_contract.OpenApiContractTest.test_correction_responses_declare_knowledge_context_refs tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema -v
```

Result: 11 tests OK.

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

- Internal correction/adoption response projection only.
- No lifecycle, review, retrieval, adoption, feedback, approval, SQL Safety,
  EvidenceChain, or connector behavior change.
- No KnowledgeAsset title/content, raw trace payload, raw run parameters,
  related knowledge body, tool output, metric deltas, score-breakdown internals,
  or secret-like fields are exposed.
- Self-report `/outcomes` still does not promote knowledge.
- `/adoptions` remains the only realized external-value promotion path.
- No autonomous-core, G10, AGI, autonomy, R4/R5, or business-action execution
  claim.
