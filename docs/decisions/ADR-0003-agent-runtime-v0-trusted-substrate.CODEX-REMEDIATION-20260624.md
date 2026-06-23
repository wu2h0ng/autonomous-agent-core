# ADR-0003 Codex Remediation: Agent Runtime v0 Trusted Substrate

- Remediation date: 2026-06-24
- Branch: `codex/agent-runtime-v0-trusted-substrate`
- Base review: `docs/decisions/ADR-0003-agent-runtime-v0-trusted-substrate.REVIEW-20260624.md`
- Merge status: **PENDING SECOND REVIEW; DO NOT MERGE UNTIL REVIEW GATE PASSES**

## Scope

This remediation closes the ADR-0003 pre-merge blockers H1-H3:

1. `AgentRuntime.run_tool()` policy bypass.
2. R4/R5 and side-effect metadata not enforced by `RuntimePolicyGate`.
3. Runtime trace events recording raw args/output by default.

It does not add a workflow engine, durable distributed checkpointing, concurrency, factory/API exposure, autonomous-core adoption, external agent-framework dependency, or automatic R4/R5 business execution.

## Changes

### H1 - `run_tool()` bypass closed

`AgentRuntime.run_tool()` now delegates to `invoke_tool()` using a compatibility-generated `AgentToolCall`. It returns an `AgentToolResult` and therefore goes through:

- context validation
- pause shell denial
- risk/permission/approval policy gate
- input validation
- structured trace events
- checkpoint boundary

Regression test:

- `tests/unit/test_agent_runtime_tools.py::AgentRuntimeToolsTest::test_compat_run_tool_uses_policy_gate_instead_of_direct_call`

### H2 - R4/R5 and side-effect execution now fail closed

`RuntimePolicyGate` now requires `approval_id` when any of the following is true:

- `ToolSpec.requires_approval` is true
- `ToolSpec.risk_level` is `R4` or `R5`
- `ToolSpec.side_effect_class` is not a non-side-effect class (`none`, `read`, `read_only`, `readonly`, or empty)

Permission checks still run before approval checks, so missing authorization remains `DENY_MISSING_PERMISSION`.

Regression tests:

- `tests/unit/test_agent_runtime_policy.py::AgentRuntimePolicyTest::test_r4_tool_is_denied_without_approval_even_without_tool_opt_in`
- `tests/unit/test_agent_runtime_policy.py::AgentRuntimePolicyTest::test_side_effecting_tool_is_denied_without_approval_even_at_lower_risk`
- `tests/unit/test_agent_runtime_policy.py::AgentRuntimePolicyTest::test_r5_side_effecting_tool_can_run_with_approval_id`

### H3 - Trace projection safe by default

Runtime trace events no longer record raw `args` or raw `output`. The runtime-level trace payload is now limited to execution metadata such as:

- `call_id`
- `tool_name`
- `run_id`
- `trace_id`
- `status`
- `error_code`

`AgentTraceWriter` also has a default sensitive-key denylist for explicit custom events, but the runtime does not depend on redaction to protect raw tool payloads.

Regression tests:

- `tests/unit/test_agent_runtime_trace.py::AgentRuntimeTraceTest::test_runtime_trace_does_not_record_raw_args_or_outputs_by_default`
- `tests/unit/test_agent_runtime_trace.py::AgentRuntimeTraceTest::test_trace_writer_redacts_sensitive_keys_in_explicit_events`

## Verification

```bash
/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest \
  tests.unit.test_agent_runtime_policy \
  tests.unit.test_agent_runtime_trace \
  tests.unit.test_agent_runtime_tools \
  tests.unit.test_agent_runtime_replay_boundary \
  tests.integration.test_trusted_loop_agent_runtime_adapter -v
```

Result: 19 tests OK.

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result: ruff clean, format clean, 434 tests OK with 4 skipped, 12 eval tests OK, OpenAPI contract clean.

```bash
AGENT_OS_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:15432/agent_os_test \
  make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result: full local CI parity passed.

## Residual Gate

This remediation does not itself approve merge. ADR-0003 still requires a second merge-readiness review gate before merging to `main`.
