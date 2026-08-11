# ADR-0003 Agent Runtime Success Trace Bridge Implementation

- Date: 2026-06-26
- Branch: `codex/agent-runtime-success-trace-bridge-current`
- Base: local `main` at `3249c36`
- Scope: persist safe Agent Runtime envelope events for successful `POST /runs` into the queryable business `RunTrace`
- Status: implemented and verified branch-locally; review/merge gate pending

## Decision

Successful `POST /runs` requests already traverse:

```text
AgentRunContext -> TrustedLoopAgentRuntimeAdapter -> RuntimePolicyGate -> TrustedLoopRuntime.evaluate
```

Before this slice, successful runtime-envelope events were visible only in the request-scoped HTTP diagnostic writer. The durable business trace at `/traces/{trace_id}` contained Trusted Loop events, but not the Agent Runtime envelope proving that the HTTP run entered the policy-gated runtime path.

This slice persists safe `agent_runtime.*` events around the existing business events after `TrustedLoopRuntime.evaluate()` successfully produces a business trace id. Pre-loop runtime events such as `agent_runtime.tool_started` are stored before the business `intent` event; terminal runtime events such as `agent_runtime.tool_succeeded` are stored after the Trusted Loop events.

## Safety Boundary

- Does not modify Core `AgentRuntime` policy semantics.
- Does not alter SQL Safety, EvidenceChain, Approval, OperationTrace, or user_result production.
- Does not change `/approvals/{approval_id}/execute`.
- Does not enable automatic R4/R5 execution.
- Does not introduce an external agent framework dependency.
- Does not claim autonomous-core evidence.

Persisted runtime payloads are allowlisted to metadata such as:

- `call_id`
- `tool_name`
- `run_id`
- `status`
- `error_code`

Raw request parameters and raw tool outputs remain excluded.

## TDD Evidence

Red test:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_post_run_persists_agent_runtime_envelope_in_run_trace -v
```

Failure before implementation:

```text
AssertionError: 'agent_runtime.policy_allowed' not found in []
```

Green test after implementation:

```text
test_post_run_persists_agent_runtime_envelope_in_run_trace ... ok
```

Affected suite:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest \
  tests.unit.test_http_app \
  tests.unit.test_outcome_service \
  tests.integration.test_trusted_loop_agent_runtime_adapter -v
```

Result:

```text
62 tests OK
```

Full gates:

```text
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python

Result: ruff clean; format clean; 454 tests OK, 4 skipped; 12 eval tests OK; OpenAPI contract drift check passed.

AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python

Result: full local CI parity checks passed.
```

## Pending Gate

Review the diff before any founder/CTO fast-forward decision.
