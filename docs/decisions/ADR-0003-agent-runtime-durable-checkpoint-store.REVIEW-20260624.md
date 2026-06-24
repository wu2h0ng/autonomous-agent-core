# ADR-0003 Follow-up Review: Durable Checkpoint Store and R4/R5 Proposal Boundary

- Review date: 2026-06-24
- Branch reviewed: `codex/runtime-durable-checkpoint-store`
- Reviewed commit: `d6adeb9`
- Base: enterprise `main` `77c7b07`
- Scope: merge-readiness review for the ADR-0003 follow-up branch before any local `main` fast-forward
- Approval status: **PASS FOR LOCAL MERGE GATE; NOT A RELEASE CLAIM**

## Reviewed Delta

This review covers the three-commit follow-up branch:

1. `777137f feat(runtime): persist checkpoint snapshots`
2. `a7306ed fix(runtime): enforce r4 r5 proposal-only policy`
3. `d6adeb9 fix(runtime): make checkpoint failures typed`

The branch adds or hardens:

- `AgentRunContext.risk_ceiling` and fail-closed `DENY_RISK_CEILING`
- fingerprint-bound checkpoint resume across call, context, and tool spec
- `CheckpointStorePort`
- `SqlAgentCheckpointStore`
- `agent_runtime_checkpoints` schema plus Alembic `0008_agent_runtime_checkpoints`
- SQL checkpoint mapper round-trip and cross-runtime replay coverage
- typed `checkpoint_error` result plus `agent_runtime.checkpoint_failed` trace event on checkpoint save failure
- non-proposal `R4`/`R5` denial even when `approval_id` is present
- proposal-class `R4`/`R5` allowance for producing action proposals without executing the business action

## Gate Findings

### H1 - Checkpoint save failure after tool execution was an unstructured escape

- Severity: HIGH before remediation
- Status: **closed in `d6adeb9`**
- Runtime anchor: `packages/os_core/src/agent_os_core/agent_runtime/__init__.py`
- Regression test: `tests/unit/test_agent_runtime_replay_boundary.py::AgentRuntimeReplayBoundaryTest::test_checkpoint_store_failure_returns_structured_error_after_tool_execution`

Prior behavior could execute the tool body and then let `checkpoint_store.save(...)` raise a raw exception out of `invoke_tool()`. The current branch converts that boundary into:

- `AgentToolResult.status == "checkpoint_error"`
- `error_message == "checkpoint save failed"`
- safe metadata containing the original tool status and checkpoint boundary
- `agent_runtime.checkpoint_failed` trace event without raw exception details or raw tool payloads
- final `agent_runtime.invocation_finished` event with `status == "checkpoint_error"`

### H2 - R4/R5 must remain proposal-only

- Severity: HIGH class
- Status: **closed in reviewed branch**
- Runtime anchor: `RuntimePolicyGate.check(...)`
- Regression tests:
  - `tests/unit/test_agent_runtime_policy.py::AgentRuntimePolicyTest::test_r4_non_proposal_tool_is_denied_before_tool_body`
  - `tests/unit/test_agent_runtime_policy.py::AgentRuntimePolicyTest::test_r5_side_effecting_tool_is_denied_even_with_approval_id`
  - `tests/unit/test_agent_runtime_policy.py::AgentRuntimePolicyTest::test_r5_action_proposal_tool_can_run_without_executing_business_action`

The policy now denies non-proposal `R4`/`R5` tools with `DENY_HIGH_RISK_EXECUTION` before tool execution. `approval_id` does not upgrade `R4`/`R5` into executable business actions. Proposal-class tools may run only as proposal producers.

### H3 - Runtime trace must not leak raw args/output

- Severity: HIGH class
- Status: **closed for runtime-owned trace events**
- Runtime anchor: `AgentRuntime.invoke_tool(...)`
- Regression test: `tests/unit/test_agent_runtime_trace.py::AgentRuntimeTraceTest::test_runtime_trace_does_not_record_raw_args_or_outputs_by_default`

Runtime-owned events record execution metadata such as call id, tool name, run id, trace id, status, and error code. They do not emit raw `AgentToolCall.args` or raw `AgentToolResult.output`.

## Residual Non-blocking Risks

### R1 - Durable checkpoint payload is recovery state, not safe trace

- Severity: MEDIUM follow-up
- Status: **accepted as a scoped v0 tradeoff; must not be marketed as DLP-safe storage**
- Anchor: `packages/persistence/src/agent_os_persistence/mappers.py`

`SqlAgentCheckpointStore` persists `RunStateSnapshot` payloads for recovery. That payload may include `last_result.output` and, if later used for pending work, `pending_tool_call.args`. This is intentionally different from runtime trace projection. The branch does not leak these payloads into trace, but checkpoint storage itself must be treated as sensitive durable state behind normal database access controls.

Required later ADR before production exposure:

- checkpoint payload encryption or field-level projection policy
- retention and deletion policy
- tenant/workspace isolation policy
- factory/API selection of checkpoint backend
- explicit statement that checkpoints are not customer-facing audit traces

### R2 - `AgentTraceWriter` custom-event redaction is not a DLP system

- Severity: LOW/MEDIUM follow-up
- Status: **non-blocking because runtime-owned events avoid raw payloads**
- Anchor: `AgentTraceWriter._redact(...)`

The trace writer has a default sensitive-key denylist, but custom events still depend on key-based redaction. Callers must not use it as a general DLP layer. Later hardening should normalize sensitive-key matching and add tool-specific trace projection policies, but this does not reopen H3 because ADR-0003 runtime-owned events no longer write raw args or outputs.

## Merge Conditions

This branch is acceptable for a scoped local fast-forward into local enterprise `main` if the current verification remains green.

Do not treat this as approval for:

- pushing local `main` while it is already ahead of `origin/main` without an explicit remote-sync decision
- external release claims
- automatic `R4`/`R5` execution
- factory/API exposure of Agent Runtime surfaces
- workflow-engine replacement
- autonomous-core adoption
- checkpoint backend selection in product factories

## Verification Evidence

Recorded verification after the reviewed commit:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src \
  .venv/bin/python -m unittest \
  tests.unit.test_agent_runtime_policy \
  tests.unit.test_agent_runtime_tools \
  tests.unit.test_agent_runtime_trace \
  tests.unit.test_agent_runtime_replay_boundary \
  tests.unit.test_agent_runtime_sql_checkpoint \
  tests.unit.test_persistence.PersistenceRepositoriesTest.test_agent_runtime_checkpoint_round_trip_and_rewrite \
  tests.unit.test_migrations_cover_schema -v

Result: 30 tests OK.

ruff check .
Result: OK.

ruff format --check .
Result: OK.

git diff --check
Result: OK.

make ci PYTHON=.venv/bin/python
Result: 446 tests OK, 4 skipped; 12 eval tests OK; OpenAPI contract drift check OK.

AGENT_OS_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:15432/agent_os_test \
  make ci-local-full PYTHON=.venv/bin/python
Result: full local CI parity passed.
```

## Conclusion

No open HIGH blocker remains in the reviewed ADR-0003 follow-up branch.

Gate outcome: **PASS FOR LOCAL MERGE GATE**, subject to final fresh verification and explicit founder/CTO authorization before merging or pushing.
