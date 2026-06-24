# ADR-0003 Implementation Log: Runtime Checkpoint/Trace Security Follow-up

- Date: 2026-06-24
- Branch: `codex/runtime-checkpoint-trace-security`
- Base branch: stacked on `codex/runtime-durable-checkpoint-store` at `dde7425`
- Scope: close narrow runtime checkpoint/trace hardening gaps from the durable-checkpoint review, without changing release gates or runtime execution authority
- Status: local implementation; not merged, not pushed, not a release claim

## Intent

The prior ADR-0003 durable-checkpoint review kept `AgentTraceWriter` custom-event redaction as a residual non-blocking risk:

- runtime-owned events no longer write raw args/output;
- custom events still rely on key-based redaction;
- key matching was case-sensitive.

This follow-up closes two narrow issues:

1. Common sensitive-key casing variants such as `Authorization`, `Secret_Token`, or `API_KEY` could bypass the default denylist in explicit custom trace events.
2. `AgentRuntime.resume_from_checkpoint(...)` returned success/failure results but did not emit runtime trace events for resume start, success, or fail-closed mismatch paths.

## TDD Evidence

Red test added first:

- `tests/unit/test_agent_runtime_trace.py::AgentRuntimeTraceTest::test_trace_writer_redacts_sensitive_keys_case_insensitively`

Observed RED failure before implementation:

```text
AssertionError: 'Bearer sk-live' unexpectedly found in
[{'step': 'custom', 'payload': {'Authorization': 'Bearer sk-live', ...}}]
```

Minimal implementation:

- `AgentTraceWriter._redact(...)` normalizes `self.sensitive_keys` and payload keys with `lower()` for comparison;
- redacted payloads preserve the original key name while replacing the sensitive value with `[REDACTED]`.

Green tests:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src \
  .venv/bin/python -m unittest \
  tests.unit.test_agent_runtime_trace.AgentRuntimeTraceTest.test_trace_writer_redacts_sensitive_keys_case_insensitively -v

Result: 1 test OK.

PYTHONPATH=packages/contracts/src:packages/os_core/src \
  .venv/bin/python -m unittest tests.unit.test_agent_runtime_trace -v

Result: 4 tests OK.
```

Second red test added:

- `tests/unit/test_agent_runtime_replay_boundary.py::AgentRuntimeReplayBoundaryTest::test_resume_rejects_call_mismatch_without_tool_execution`
- `tests/unit/test_agent_runtime_replay_boundary.py::AgentRuntimeReplayBoundaryTest::test_resume_returns_last_result_for_matching_checkpoint`

Observed RED failure before implementation:

```text
AssertionError: 'agent_runtime.checkpoint_resume_failed' not found in [...]
AssertionError: 'agent_runtime.checkpoint_resume_started' not found in [...]
```

Minimal implementation:

- `resume_from_checkpoint(...)` emits `agent_runtime.checkpoint_resume_started` before checkpoint lookup;
- matching checkpoint resume emits `agent_runtime.checkpoint_resume_succeeded` with call id, tool name, run id, trace id, and status;
- fail-closed resume paths emit `agent_runtime.checkpoint_resume_failed` with safe metadata and error code;
- resume trace payloads do not include raw call args or stored result output.

Green tests:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src \
  .venv/bin/python -m unittest \
  tests.unit.test_agent_runtime_replay_boundary.AgentRuntimeReplayBoundaryTest.test_resume_rejects_call_mismatch_without_tool_execution \
  tests.unit.test_agent_runtime_replay_boundary.AgentRuntimeReplayBoundaryTest.test_resume_returns_last_result_for_matching_checkpoint -v

Result: 2 tests OK.

PYTHONPATH=packages/contracts/src:packages/os_core/src \
  .venv/bin/python -m unittest tests.unit.test_agent_runtime_replay_boundary -v

Result: 6 tests OK.
```

## Boundary

This does not turn `AgentTraceWriter` into a general DLP system. It only strengthens the default denylist behavior for explicit custom trace events.

Runtime-owned ADR-0003 events still follow the stronger rule: they do not emit raw tool args or raw tool output by default.

Checkpoint resume trace events are audit metadata, not replay payloads. The durable checkpoint payload remains the recovery surface.

## Remaining Runtime Security Work

The durable checkpoint payload remains recovery state, not safe trace. Before production factory/API exposure of durable checkpoints, a later ADR must decide:

- checkpoint payload projection policy versus full recovery payload;
- encryption and key management;
- retention and deletion policy;
- tenant/workspace isolation;
- whether any checkpoint content may be exposed outside operator-only recovery paths.

## Non-Claims

This implementation does not claim:

- automatic R4/R5 execution;
- external release readiness;
- full DLP;
- tenant isolation;
- field-level authorization;
- workflow-engine replacement;
- autonomous-core adoption.
