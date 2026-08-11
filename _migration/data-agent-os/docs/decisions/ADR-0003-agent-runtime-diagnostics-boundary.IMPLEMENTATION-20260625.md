# ADR-0003 Agent Runtime Diagnostics Boundary Implementation

- Date: 2026-06-25
- Branch: `codex/agent-runtime-diagnostics-boundary`
- Base branch: rebased onto local `main` at `56c80ce`
- Scope: bound the HTTP app-level Agent Runtime diagnostic writer after Packet A Slice 0 live `/runs` wiring
- Status: implemented locally; post-rebase verification passed; founder/CTO merge decision still required

## Problem

Packet A Slice 0 correctly routed `POST /runs` through the Agent Runtime envelope, but the FastAPI app held one app-lifetime `AgentTraceWriter` and one app-lifetime `TrustedLoopAgentRuntimeAdapter`.

That writer was not user-facing and did not store raw args/output, but it still accumulated runtime-envelope diagnostics across requests. This left two avoidable problems:

- long-running API processes could grow the diagnostic list without a request boundary;
- tests and future debug tools could accidentally observe prior request run ids in the current request's diagnostics.

## Decision

Keep persistent audit in `RunTrace`; keep app-level runtime-envelope diagnostics narrow and request-scoped.

`POST /runs` now creates a fresh `AgentTraceWriter` and `TrustedLoopAgentRuntimeAdapter` per request. After the service call returns or fails, the app stores that writer as the latest diagnostic writer only. This preserves the existing tests' diagnostic access while preventing app-lifetime accumulation.

## Red/Green Evidence

Added failing test first:

- `tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_post_run_runtime_diagnostics_are_request_scoped`

Before the fix:

```text
AssertionError: 10 not less than or equal to 5
```

The failure proved that the second `/runs` request retained the first request's runtime-envelope events.

After the fix:

```text
test_post_run_runtime_diagnostics_are_request_scoped ... ok
```

Review remediation:

- Added typed `AgentRuntimeErrorResponse` / `AgentRuntimeErrorDetail` for sanitized `/runs` Agent Runtime HTTP 500 failures.
- Declared the `/runs` 500 response in `apps/api_server/openapi.json`.
- Added `tests.unit.test_openapi_contract.OpenApiContractTest.test_agent_runtime_error_contract_is_declared_on_runs`.

Post-rebase focused/affected invocation:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_post_run_runtime_diagnostics_are_request_scoped \
  tests.unit.test_openapi_contract.OpenApiContractTest.test_agent_runtime_error_contract_is_declared_on_runs \
  tests.unit.test_http_app \
  tests.unit.test_outcome_service \
  tests.integration.test_trusted_loop_agent_runtime_adapter -v

Result: 63 tests OK
```

Full local gate:

```text
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python

Result: ruff clean; format clean; 453 tests OK, 4 skipped; 12 eval tests OK; OpenAPI contract drift check passed.

AGENT_OS_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:15432/agent_os_test \
  make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python

Result: full local CI parity checks passed against disposable PostgreSQL.
```

## Non-Claims

This slice does not:

- persist successful Agent Runtime envelope events into `RunTrace`;
- change `/approvals/{approval_id}/execute`;
- introduce a workflow engine;
- change R4/R5 execution policy;
- replace `TrustedLoopRuntime`;
- claim autonomous-core evidence or general autonomy.

The remaining production observability decision is whether successful Agent Runtime envelope events should be bridged into persisted traces, exported to telemetry, or kept diagnostic-only.
