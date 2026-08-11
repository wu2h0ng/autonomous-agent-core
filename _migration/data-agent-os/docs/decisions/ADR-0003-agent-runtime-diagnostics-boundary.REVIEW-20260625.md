# ADR-0003 Agent Runtime Diagnostics Boundary Review

- Date: 2026-06-25
- Branch reviewed: `codex/agent-runtime-diagnostics-boundary`
- Base: rebased local `main` at `56c80ce`
- Initial reviewed head: `fd28cd8`
- Head after post-rebase verification: current branch head after this amended commit
- Scope: Packet A Slice 1 follow-up; request-scoped HTTP runtime diagnostics on top of live `/runs` runtime-envelope wiring already merged to local `main`
- Status: approved after remediation, rebase, and fresh verification

## Verdict

**APPROVED FOR FOUNDER/CTO FF DECISION.**

The initial diagnostics-boundary implementation closed the non-blocking app-lifetime diagnostic writer issue from the live-wiring review. One contract gap was found during this review: the branch introduced a structured `/runs` HTTP 500 runtime-error path but did not declare that response in the OpenAPI contract. The gap is remediated with a typed response schema, snapshot update, and regression test.

This approval is scoped to:

- `POST /runs` entering the Agent Runtime envelope;
- sanitized runtime/tool/checkpoint failure mapping;
- persisted pre-loop Agent Runtime denial traces;
- request-scoped HTTP app runtime diagnostics;
- the typed `/runs` Agent Runtime 500 OpenAPI schema.

It does not approve `/approvals/{approval_id}/execute` runtime-envelope migration, production trace export/retention policy, workflow-engine replacement, automatic R4/R5 execution, external release, or autonomous-core evidence claims.

## Finding And Remediation

### [MEDIUM] `/runs` Agent Runtime 500 response was runtime-tested but not declared in OpenAPI

Initial behavior:

- `POST /runs` returned sanitized HTTP 500 details for internal Agent Runtime/tool/checkpoint failures.
- The route decorator still declared only 200 and 422 responses.
- `apps/api_server/openapi.json` did not include the runtime-error response schema.

This was a contract gap: the failure path had runtime tests and ADR text, but the public API contract did not declare the typed 500 shape.

Red test:

- `tests.unit.test_openapi_contract.OpenApiContractTest.test_agent_runtime_error_contract_is_declared_on_runs`

Before remediation:

```text
AssertionError: '500' not found in {'200': ..., '422': ...}
```

Remediation:

- Added `AgentRuntimeErrorDetail` and `AgentRuntimeErrorResponse`.
- Declared `/runs` response `500` with `AgentRuntimeErrorResponse`.
- Regenerated `apps/api_server/openapi.json`.
- Added an OpenAPI contract regression test asserting the 500 response and detail schema.

## Verification

Review red/green regression:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest \
  tests.unit.test_openapi_contract.OpenApiContractTest.test_agent_runtime_error_contract_is_declared_on_runs -v

Before remediation: 1 failure
After remediation: test OK
```

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

Full local gates:

```text
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python

Result: ruff clean; format clean; 453 tests OK, 4 skipped; 12 eval tests OK; OpenAPI contract drift check passed.

AGENT_OS_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:15432/agent_os_test \
  make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python

Result: full local CI parity checks passed.
```

## Gate Result

Founder/CTO can decide whether to fast-forward local `main` to `codex/agent-runtime-diagnostics-boundary`.

Recommended next runtime slice after merge:

1. Decide whether `/approvals/{approval_id}/execute` should enter an Agent Runtime envelope or remain a separate approval-execution boundary.
2. Decide product-factory checkpoint backend selection and retention policy.
3. Decide whether successful Agent Runtime envelope events should be bridged into persisted `RunTrace`, exported to telemetry, or remain diagnostic-only.
