# ADR-0003 Approval Execute Runtime Envelope Review

Date: 2026-06-26
Branch: `codex/agent-runtime-approval-execute-envelope`
Reviewed commit: `4d1d429`
Base: local `main@3249c36`
Reviewer: Codex

## Verdict

APPROVE for fast-forward merge into local deployment `main`, subject to explicit
founder/CTO merge authorization.

Do not push, release, or claim external readiness from this review. Deployment
local `main` is already ahead of `origin/main`, so this review only covers the
branch delta against local `main`.

## Findings

No blocking findings.

## Review Checks

- `POST /approvals/{approval_id}/execute` now constructs a route-bound
  `AgentRunContext` and enters `TrustedLoopApprovalExecutionRuntimeAdapter`
  before the Trusted Loop approval-resume call.
- `TrustedLoopApprovalExecutionRuntimeAdapter` registers
  `trusted_loop.approval_execute` as `risk_level="R3"`,
  `side_effect_class="approval_execution"`, `requires_approval=True`, and
  `required_permissions=("trusted_loop:approval_execute",)`.
- `RuntimePolicyGate` still denies paused-shell execution before
  `agent_runtime.tool_started`.
- Approval authority remains in `ApprovalRuntime` and `ApprovalContextStore`;
  Agent Runtime does not become the source of approval truth.
- Existing approval 404/409 response semantics are preserved.
- R4/R5 execution remains fail-closed in
  `TrustedLoopRuntime.execute_approved_operation(...)`.
- Runtime trace events do not include raw request args, approval payloads, or
  connector outputs.

## Verification

Focused review regression:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_approval_execute_traverses_agent_runtime_envelope tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_approval_execute_paused_shell_is_denied_before_connector_write tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_approval_execute_uses_approval_bound_context_without_cross_pollution tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_approval_execute_requires_operator_key_not_run_api_key tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_approval_execute_second_call_is_rejected tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_approval_execute_rejected_approval_is_409 tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_approval_execute_unknown_approval_is_404 tests.unit.test_agent_runtime_policy.AgentRuntimePolicyTest.test_r5_side_effecting_tool_is_denied_even_with_approval_id tests.unit.test_agent_runtime_trace.AgentRuntimeTraceTest.test_runtime_trace_does_not_record_raw_args_or_outputs_by_default tests.unit.test_trusted_loop_snapshot_rollback.TrustedLoopSnapshotTest.test_approval_resume_rejects_r4_r5_business_actions_in_mvp -v
```

Result: 10 tests OK.

Full CI:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result: ruff clean, format clean, 455 tests OK, 4 skipped, 12 eval tests OK,
OpenAPI contract up to date.

Full local CI parity:

```bash
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result: full local CI parity checks passed.

## Residual Risks

- This slice adds a second HTTP runtime envelope, but still does not provide a
  general workflow engine, async graph scheduler, or runtime factory/API surface.
- The route records the latest request's diagnostic writer on app state for
  test/debug inspection; this remains a diagnostics surface, not durable
  production observability.
- The review does not cover remote push/release readiness because local
  deployment `main` is ahead of `origin/main`.

## Required Changes

None before local fast-forward merge, assuming explicit merge authorization.
