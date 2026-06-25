# ADR-0003 Agent Runtime Live Wiring Review

- Date: 2026-06-25
- Branch reviewed: `codex/agent-runtime-live-wiring`
- Base: `main` at `0b23094`; rebased onto current local `main` at `4905375`
- Initial reviewed head: `b7f3f43`
- Head after remediation: branch head after this review document lands
- Post-gate outcome: founder approved FF merge; local `main` fast-forwarded to `2673ab4` on 2026-06-25
- Scope: Packet A Slice 0, routing `POST /runs` through `AgentRunContext -> TrustedLoopAgentRuntimeAdapter -> RuntimePolicyGate -> TrustedLoopRuntime.evaluate`
- Status: approved after remediation and verification

## Verdict

**APPROVED FOR FOUNDER/CTO FF DECISION.**

The initial review found two high-severity blockers in the live HTTP composition. Both now have red/green regression tests and narrow service-layer fixes. No remaining blocker was found for Packet A Slice 0.

This approval is scoped: it lands `POST /runs` runtime-envelope wiring only. It does not approve `/approvals/{approval_id}/execute` runtime-envelope migration, workflow replacement, production trace retention policy, automatic R4/R5 execution, or external release.

## Findings And Remediation

### [HIGH] Tool exceptions were downgraded to 422 and leaked raw exception text

Initial behavior:

- `AgentRuntime` converted exceptions from the wrapped `TrustedLoopRuntime.evaluate()` call into `AgentToolResult(status="tool_error", error_message=str(exc))`.
- `run_service(...)` mapped every non-`ok` runtime result to the existing business block contract.
- HTTP returned 422 and exposed the raw exception message, including to the external report-key projection.

This was both a semantic error and a privacy risk. Internal programming, dependency, or connector faults are not expected business refusals and must not expose raw exception text.

Red test:

- `tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_post_run_tool_error_returns_500_without_exception_text_for_external`

Before remediation:

```text
AssertionError: 422 != 500
detail.message included dsn=postgres://secret-token@localhost/customer
```

Remediation:

- `run_service(...)` now separates runtime policy/validation refusals from internal runtime/tool failures.
- `tool_error` and `checkpoint_error` return `status="error"` with fixed public code/message:
  - `AGENT_RUNTIME_TOOL_ERROR`
  - `AGENT_RUNTIME_CHECKPOINT_ERROR`
  - `Agent runtime failed before producing a trusted result.`
- `POST /runs` maps that service error to HTTP 500.
- External report-key projection does not expose the runtime error trace id.
- Persisted runtime-error traces include safe metadata only: call id, tool name, error code. They do not include raw args, raw output, or `str(exc)`.

### [HIGH] Runtime policy denial returned an unauditable trace id

Initial behavior:

- A paused shell was denied by `RuntimePolicyGate` before `TrustedLoopRuntime.evaluate()`.
- The 422 response returned an `agent-trace-*` id from `AgentRunContext`.
- No `RunTrace` was persisted under that id because the Trusted Loop never started.
- `/traces/{trace_id}` returned 404 for the refusal.

This violated the product trace boundary: expected refusals must be queryable after the fact.

Red test:

- `tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_post_run_pause_is_denied_by_agent_runtime_before_tool_start`

Before remediation:

```text
AssertionError: 404 != 200 : {"detail":"No run trace for 'agent-trace-...'"}
```

Remediation:

- `run_service(...)` now persists a safe `RunTrace(status="blocked")` for Agent Runtime terminal refusals that occur before the Trusted Loop starts.
- The persisted trace includes:
  - `agent_runtime.policy_denied` or `agent_runtime.validation_failed`
  - final `blocked` event with code, stage, and safe message
- The paused `/runs` response trace id is now queryable through `/traces/{trace_id}`.
- The test asserts that the trace contains `agent_runtime.policy_denied` and `blocked`, and does not contain `agent_runtime.tool_started`.

## Remaining Non-Blocking Note

The HTTP app still keeps a process-local `AgentTraceWriter` in `app.state` for runtime-envelope diagnostic assertions. The payloads are safe and not client-visible, and terminal runtime denials/errors now have persisted `RunTrace` coverage. A later runtime API/observability slice should replace or bound this diagnostic writer and decide whether successful runtime-envelope events should also be bridged into persisted traces.

This is not a merge blocker for Packet A Slice 0 because the landed user-facing and audit-critical surfaces are:

- successful `POST /runs` still persists the existing Trusted Loop `RunTrace`;
- expected Trusted Loop blocks still persist the existing blocked `RunTrace`;
- pre-loop Agent Runtime denials now persist a blocked `RunTrace`;
- runtime/tool internal errors return 500 without raw exception leakage.

## Verification

Post-rebase verification on `a3c6e14`:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest \
  tests.unit.test_http_app tests.unit.test_outcome_service tests.integration.test_trusted_loop_agent_runtime_adapter -v

Result: 60 tests OK

make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python

Result: ruff clean; format clean; 451 tests OK, 4 skipped; 12 eval tests OK; OpenAPI contract drift check passed.

AGENT_OS_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:15432/agent_os_test \
  make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python

Result: full local CI parity checks passed.
```

Red/green review regressions:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_post_run_pause_is_denied_by_agent_runtime_before_tool_start \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_post_run_tool_error_returns_500_without_exception_text_for_external -v

Before remediation: 2 failures
After remediation: 2 tests OK
```

Affected HTTP/service/adapter suite:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest \
  tests.unit.test_http_app \
  tests.unit.test_outcome_service \
  tests.integration.test_trusted_loop_agent_runtime_adapter -v

Result: 60 tests OK
```

Full local gates:

```text
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python

Result: ruff clean; format clean; 451 tests OK, 4 skipped; 12 eval tests OK; OpenAPI contract drift check passed.

AGENT_OS_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:15432/agent_os_test \
  make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python

Result: full local CI parity checks passed.
```

## Gate Result

Founder/CTO approved fast-forwarding `main` to `codex/agent-runtime-live-wiring`; local `main` now contains Packet A Slice 0 at `2673ab4`.

Recommended next slice after merge:

1. Decide whether `/approvals/{approval_id}/execute` should enter an Agent Runtime envelope or remain a separate approval-execution boundary.
2. Decide product-factory checkpoint backend selection and retention policy.
3. Replace or bound the app-level diagnostic `AgentTraceWriter` before broader live runtime exposure.
