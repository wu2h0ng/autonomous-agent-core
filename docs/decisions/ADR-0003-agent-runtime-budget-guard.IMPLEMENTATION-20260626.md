# ADR-0003 Implementation Log: Agent Runtime Budget Guard

Date: 2026-06-26
Branch: `codex/agent-runtime-budget-guard`
Base: stacked on `codex/agent-runtime-checkpoint-factory-selection` at `4420ffc`
Status: implementation complete; branch-local verification passed; branch-local review approved

## Scope

This slice adds a narrow pre-execution budget guard to the existing self-developed Agent Runtime substrate:

- `AgentRunContext.max_tool_calls` limits how many tool bodies may start for a run.
- `AgentRunContext.tool_timeout_ceiling_ms` denies tools without a declared `ToolSpec.timeout_ms` and tools whose declared timeout exceeds the run ceiling.
- `AgentRunContext.cost_budget_units` limits cumulative declared `ToolSpec.estimated_cost_units` per run.
- Budget denial returns a typed `AgentToolResult(status="denied")` before `agent_runtime.tool_started`.
- Budget denial emits a safe `agent_runtime.budget_denied` trace event without raw args or outputs.
- Budget reservation emits a safe `agent_runtime.budget_reserved` trace event with counters only.

## Safety Boundary

This is not a wall-clock interrupter, async cancellation system, graph scheduler, workflow engine, token meter, or production billing system. It is a deterministic pre-execution guard over declared tool metadata, designed to make unbounded tool loops fail closed before the tool body starts.

R4/R5 proposal-only enforcement, Approval/ApprovalContextStore authority, SQL Safety, EvidenceChain, Trace, and checkpoint fingerprinting remain intact.

## Tests

New regression coverage:

- Second tool call is denied before the tool body when `max_tool_calls=1`.
- Invalid run budget is denied before the tool body.
- A tool with declared timeout above `tool_timeout_ceiling_ms` is denied before the tool body.
- A tool without declared timeout is denied before the tool body when `tool_timeout_ceiling_ms` is set.
- Cumulative declared cost units are reserved per run and deny the next tool before the body when exhausted.

Affected suite run:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_agent_runtime_budget tests.unit.test_agent_runtime_policy tests.unit.test_agent_runtime_tools tests.unit.test_agent_runtime_trace tests.unit.test_agent_runtime_replay_boundary tests.unit.test_agent_runtime_sql_checkpoint tests.integration.test_trusted_loop_agent_runtime_adapter tests.unit.test_http_app -v
```

Result: 82 tests OK.

Full branch verification:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result:

- ruff check passed.
- ruff format check passed.
- 463 tests OK and 4 skipped in primary unittest discovery.
- 12 eval tests OK.
- OpenAPI contract drift check passed.
- `ci-local-full` passed against local PostgreSQL on `127.0.0.1:5432/agent_os_test`.

## Non-Claims

This slice does not add runtime preemption, true wall-clock timeout enforcement, streaming cancellation, concurrency control, workflow replacement, public budget API, external-system cost accounting, autonomous-core adoption, or automatic R4/R5 execution.
