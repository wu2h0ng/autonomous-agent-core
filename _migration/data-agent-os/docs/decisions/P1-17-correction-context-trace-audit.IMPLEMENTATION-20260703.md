# P1-17 Correction Context Trace Audit Implementation

Date: 2026-07-03
Branch: `codex/p1-17-correction-context-trace-audit-20260703`
Status: branch-local verified; not merged, not pushed, not released

## Scope

P1-17 makes the correction-channel trace audit match the P1-16 response projection:

- successful HTTP `POST /outcomes` runtime-envelope trace events append safe `knowledge_context_refs` to `agent_runtime.tool_succeeded`;
- successful HTTP `POST /adoptions` runtime-envelope trace events append the same safe field;
- the field is derived from the correction service output, which itself is derived from the source trace's latest `action_proposal` event.

This gives internal trace readers an auditable link from correction/adoption events back to the historical KnowledgeAssets that were used as proposal context.

## Boundary

This is a trace-audit projection only. It does not:

- write `knowledge_context_refs` into tool inputs, `tool_started`, feedback store rows, adoption ledger rows, or KnowledgeAsset records;
- expose KnowledgeAsset titles, content, summaries, or full `related_knowledge`;
- claim causal attribution or measured value for referenced historical assets;
- promote referenced assets to reviewed, published, adopted, or value-backed;
- change self-report no-promotion or adoption promotion rules;
- alter SQL Safety, EvidenceChain, Approval, connector routing, OpenAPI response contracts, external report exposure, or R4/R5 behavior;
- reuse `/runs` trace persistence ordering for correction-channel events.

## TDD Evidence

RED command:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_correction_responses_project_used_knowledge_context_refs -v
```

Expected RED failure:

```text
[None, None] != [['knowledge-...'], ['knowledge-...']]
```

The response payloads already projected `knowledge_context_refs`, but persisted correction `agent_runtime.tool_succeeded` trace events did not.

Targeted GREEN command:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest \
  tests.unit.test_outcome_service.RecordOutcomeServiceTest \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_correction_responses_project_used_knowledge_context_refs \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_outcomes_traverse_agent_runtime_envelope_without_knowledge_promotion \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_adoptions_traverse_runtime_envelope_and_preserve_writer_authority \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_outcomes_paused_shell_denies_before_feedback_write \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_adoptions_paused_shell_denies_before_adoption_write \
  tests.unit.test_openapi_contract -v
```

Result: 20 tests OK.

## Branch-Local Verification

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result: ruff clean, format check clean, 572 primary unittest tests OK / 4 skipped, 12 eval tests OK, threshold report gate passed, OpenAPI contract up to date.

```bash
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result: PostgreSQL local parity passed with 572 primary unittest tests OK / 4 skipped, 12 eval tests OK, threshold report gate passed, OpenAPI contract up to date.

## Gate State

Local merge, push, and release remain separate gates. A local `ff-only` merge requires founder/CTO authorization and post-merge CI. No push or release is authorized by this implementation record.
