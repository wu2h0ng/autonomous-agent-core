# ADR-0003 Review: Agent Runtime Budget Guard

Date: 2026-06-26
Branch: `codex/agent-runtime-budget-guard`
Base: stacked on `codex/agent-runtime-checkpoint-factory-selection` at `4420ffc`
Verdict: APPROVE FOR FOUNDER/CTO STACKED FF DECISION

## Scope Reviewed

- Runtime budget fields on `AgentRunContext` and `ToolSpec`.
- Pre-execution budget reservation and denial path in `AgentRuntime`.
- Budget regression tests.
- Documentation/status updates for the stacked ADR-0003 runtime slice.

## Findings

No merge-blocking findings.

## Review Notes

- Budget controls are context/tool metadata, not policy strategy. `AgentRunContext` carries `max_tool_calls`, `tool_timeout_ceiling_ms`, and `cost_budget_units`; `ToolSpec` carries `timeout_ms` and `estimated_cost_units` ([runtime](/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.worktrees/codex-agent-runtime-budget-guard/packages/os_core/src/agent_os_core/agent_runtime/__init__.py:50)).
- The budget check runs after policy/input validation and before `agent_runtime.tool_started`, so denial prevents tool-body execution while preserving existing policy-gate authority ([runtime](/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.worktrees/codex-agent-runtime-budget-guard/packages/os_core/src/agent_os_core/agent_runtime/__init__.py:597)).
- Timeout ceiling is fail-closed: when `tool_timeout_ceiling_ms` is set, tools without declared `timeout_ms` are denied instead of implicitly allowed ([runtime](/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.worktrees/codex-agent-runtime-budget-guard/packages/os_core/src/agent_os_core/agent_runtime/__init__.py:612)).
- Budget trace events contain only call/tool/run/trace/error/counter metadata and do not include raw args, SQL, connector payloads, or tool outputs ([runtime](/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.worktrees/codex-agent-runtime-budget-guard/packages/os_core/src/agent_os_core/agent_runtime/__init__.py:667)).
- Regression tests cover tool-call exhaustion, invalid budgets, timeout above ceiling, undeclared timeout under a ceiling, and declared cost exhaustion before the tool body ([tests](/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.worktrees/codex-agent-runtime-budget-guard/tests/unit/test_agent_runtime_budget.py:39)).

## Non-Blocking Limits

- This is not wall-clock interruption, async cancellation, streaming cancellation, token metering, or production billing.
- Budget use is in-process per `AgentRuntime` instance. Durable budget accounting across process restarts is intentionally not implemented in this slice and should require a later ADR if needed.
- Cost control depends on declared `ToolSpec.estimated_cost_units`; it is not external-system cost reconciliation.

## Verification

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_agent_runtime_budget tests.unit.test_agent_runtime_policy tests.unit.test_agent_runtime_tools tests.unit.test_agent_runtime_trace tests.unit.test_agent_runtime_replay_boundary tests.unit.test_agent_runtime_sql_checkpoint tests.integration.test_trusted_loop_agent_runtime_adapter tests.unit.test_http_app -v
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result:

- 82 affected runtime/HTTP/adapter tests OK.
- `make ci` OK: ruff check, ruff format check, 463 tests OK, 4 skipped, 12 eval tests OK, OpenAPI drift check OK.
- `ci-local-full` OK against local PostgreSQL on `127.0.0.1:5432/agent_os_test`.

## Gate

Approved for founder/CTO stacked fast-forward merge decision after the prerequisite branches land in order:

1. `codex/agent-runtime-reviewed-slices-consolidation`
2. `codex/agent-runtime-checkpoint-factory-selection`
3. `codex/agent-runtime-budget-guard`

No release claim, workflow replacement claim, wall-clock preemption claim, autonomous-core evidence claim, or automatic R4/R5 execution claim is authorized by this review.
