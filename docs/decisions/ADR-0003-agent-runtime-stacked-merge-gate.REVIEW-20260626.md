# ADR-0003 Review: Runtime Stacked Merge Gate

Date: 2026-06-26
Scope: `codex/agent-runtime-reviewed-slices-consolidation` -> `codex/agent-runtime-checkpoint-factory-selection` -> `codex/agent-runtime-budget-guard`
Verdict: READY FOR EXPLICIT FOUNDER/CTO STACKED FF AUTHORIZATION

## Gate Position

This review does not merge `main`, does not push, and does not authorize release.

The reviewed stack is linear and fast-forwardable:

```text
main@3249c36
  -> codex/agent-runtime-reviewed-slices-consolidation@883997c
  -> codex/agent-runtime-checkpoint-factory-selection@4420ffc
  -> codex/agent-runtime-budget-guard@1d86c7e
```

Required merge order:

1. `codex/agent-runtime-reviewed-slices-consolidation`
2. `codex/agent-runtime-checkpoint-factory-selection`
3. `codex/agent-runtime-budget-guard`

## Findings

No merge-blocking findings found in the stacked review gate.

## Risk Review

### Runtime authority

- `TrustedLoopRuntime` remains the business answer/action authority.
- `ApprovalRuntime` and `ApprovalContextStore` remain the approval execution authority.
- `AgentRuntime` only wraps execution with policy, trace, checkpoint, and budget envelope behavior.

### R4/R5 execution

- R4/R5 remains proposal-only in the runtime substrate.
- Approval execution routing preserves existing approval status/context checks.
- No reviewed branch authorizes automatic R4/R5 business execution.

### Trace and payload safety

- Successful runtime-envelope events copied into `RunTrace` are allowlisted metadata.
- Budget trace events do not include raw args, SQL, connector payloads, tool output, or secrets.
- Checkpoint resume output stores an allowlisted Trusted Loop summary, not raw contract objects.

### Checkpoint and recovery

- Product factory selects memory vs SQL runtime checkpoint store.
- HTTP `POST /runs` and `POST /approvals/{approval_id}/execute` inject the selected store into request-scoped runtime adapters.
- SQL checkpoint persistence remains outside OS Core through the checkpoint-store port.

### Budget guard

- Tool-call count, declared timeout ceiling, and declared cost-unit budgets deny before `agent_runtime.tool_started`.
- Timeout ceiling is fail-closed: tools without declared `timeout_ms` are denied when a ceiling is set.
- This is not wall-clock preemption, async cancellation, streaming cancellation, token metering, or production billing.

## Verification Evidence

Branch-local review/verification records:

- `docs/decisions/ADR-0003-agent-runtime-reviewed-slices-consolidation.REVIEW-20260626.md`
- `docs/decisions/ADR-0003-agent-runtime-checkpoint-factory-selection.REVIEW-20260626.md`
- `docs/decisions/ADR-0003-agent-runtime-budget-guard.REVIEW-20260626.md`

Latest budget-guard branch verification:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_agent_runtime_budget tests.unit.test_agent_runtime_policy tests.unit.test_agent_runtime_tools tests.unit.test_agent_runtime_trace tests.unit.test_agent_runtime_replay_boundary tests.unit.test_agent_runtime_sql_checkpoint tests.integration.test_trusted_loop_agent_runtime_adapter tests.unit.test_http_app -v
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result:

- 82 affected runtime/HTTP/adapter tests OK.
- `make ci` OK: ruff check, ruff format check, 463 tests OK, 4 skipped, 12 eval tests OK, OpenAPI drift check OK.
- `ci-local-full` OK against local PostgreSQL on `127.0.0.1:5432/agent_os_test`.

## Merge Decision

Recommended next action: request explicit founder/CTO authorization for stacked fast-forward merge into local `main`, then run post-merge `make ci` and `ci-local-full` on `main`.

Do not push `main` or claim external release without a separate explicit push/release authorization.

No workflow replacement, autonomous-core evidence, AGI/autonomy claim, wall-clock preemption claim, production budget-metering claim, external-system exactly-once claim, or automatic R4/R5 execution claim is authorized by this review.
