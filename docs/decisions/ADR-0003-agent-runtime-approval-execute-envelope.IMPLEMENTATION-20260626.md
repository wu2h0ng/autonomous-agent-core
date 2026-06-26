# ADR-0003 Agent Runtime Approval Execute Envelope Implementation

Date: 2026-06-26
Branch: `codex/agent-runtime-approval-execute-envelope`
Base: local `main@3249c36`

## Scope

This slice routes `POST /approvals/{approval_id}/execute` through the self-developed
Agent Runtime envelope without changing the approval authority model.

The authority source remains:

- HTTP operator-key authentication for the transport boundary;
- `ApprovalRuntime` and `ApprovalContextStore` for approval status, claim/release,
  exact stored operation/evidence/action context, stale-claim behavior, and replay
  prevention;
- `TrustedLoopRuntime.execute_approved_operation(...)` for EvidenceChain,
  operation fingerprint, SQL Safety, and R4/R5 proposal-only enforcement.

## Implementation

Code changes:

- Added `TrustedLoopApprovalExecutionRuntimeAdapter` in
  `packages/os_core/src/agent_os_core/agent_runtime/__init__.py`.
- The adapter registers `trusted_loop.approval_execute` as a governed runtime tool
  with `risk_level="R3"`, `side_effect_class="approval_execution"`,
  `requires_approval=True`, and permission `trusted_loop:approval_execute`.
- `POST /approvals/{approval_id}/execute` now constructs a per-request
  `AgentTraceWriter`, `TrustedLoopApprovalExecutionRuntimeAdapter`, and
  `AgentRunContext` with `approval_id` bound from the route path.
- Approval not-found and approval-conflict outcomes are returned as structured tool
  output so the existing HTTP 404/409 response contract is preserved.
- Runtime policy denials, including paused-shell denial, return the existing typed
  approval-execute error shape with the runtime denial code.

## Tests

Red-first tests added:

- `tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_approval_execute_traverses_agent_runtime_envelope`
- `tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_approval_execute_paused_shell_is_denied_before_connector_write`

The second test proves a paused shell is denied before `agent_runtime.tool_started`
and before the `action_record` connector writes.

Verification:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_approval_execute_traverses_agent_runtime_envelope tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_approval_execute_paused_shell_is_denied_before_connector_write -v
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_http_app tests.unit.test_outcome_service tests.unit.test_agent_runtime_policy tests.unit.test_agent_runtime_tools tests.integration.test_trusted_loop_agent_runtime_adapter -v
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Results:

- 2 new approval-execute tests OK after red failures.
- 79 focused HTTP/service/runtime/adapter tests OK.
- `make ci` OK: ruff clean, format clean, 455 primary tests OK, 4 skipped,
  12 eval tests OK, OpenAPI contract up to date.
- `ci-local-full` OK against the local PostgreSQL `agent_os_test` database on
  `127.0.0.1:5432`.

Environment note: the prior disposable test DSN on `127.0.0.1:15432` was not
running in this session, so the verification used the reachable local
`agent_os_test` database as the disposable parity target.

## Non-Claims

This slice does not:

- make R4/R5 business actions executable;
- move approval authority into Agent Runtime;
- claim production release readiness;
- add workflow/graph/concurrency runtime behavior;
- introduce external agent-framework runtime dependencies;
- change the OpenAPI response schema.
