# ADR-0003: Agent Runtime v0 Trusted Substrate

- Status: **Accepted and implemented on branch `codex/agent-runtime-v0-trusted-substrate`**
- Date: 2026-06-24
- Risk class: R3 medium/high engineering risk
- Paired Goal Card: `ADR-0003-agent-runtime-v0-trusted-substrate.goal-card.md`
- Paired SPEC: `ADR-0003-agent-runtime-v0-trusted-substrate.SPEC.md`
- Architecture Review: `docs/architecture_reviews/AR-20260624-agent-runtime-v0-trusted-substrate.md`
- Research Intake: `docs/architecture_reviews/AR-20260624-frontier-agent-runtime-research-intake.md`

## 1. Context

The Enterprise OS already has a real Trusted Loop: SQL Safety, EvidenceChain, approval-bound governed action execution, durable approval-context resume, trace persistence, and a corrigibility pause shell. The missing layer was a self-developed Agent Runtime substrate that can host controlled tool/workflow execution without weakening those product governance surfaces.

The prior `agent_runtime` module was only a marker shell: `AgentRunContext`, `ToolRegistry`, `StructuredOutputValidator`, `AgentTraceWriter`, and `AgentRuntime.run_tool(...)`. It did not provide a mandatory policy pre-check, typed tool-call/result contracts, trace-visible failure paths, pause-shell blocking, replay/checkpoint boundary, import-boundary guard, or Trusted Loop adapter.

This ADR implements the first narrow runtime substrate. It is deliberately not a LangGraph/CrewAI replacement yet and not an autonomous-core implementation.

## 2. Decision

Build Agent Runtime v0 as a narrow, self-developed trusted substrate:

- typed run context, tool spec, tool call, tool result, and policy decision records;
- `RuntimePolicyGate` before every governed tool invocation;
- validation before tool body execution;
- trace events for success, denial, validation failure, missing tool, and tool exception;
- redaction of configured sensitive trace keys;
- minimal replay/checkpoint boundary with explicit unreplayable-input failure and fingerprint-bound checkpoint resume;
- durable SQLAlchemy-backed checkpoint adapter outside OS Core;
- `TrustedLoopAgentRuntimeAdapter` that wraps `TrustedLoopRuntime.evaluate()` without rewriting SQL Safety, EvidenceChain, Approval, or OperationTrace;
- AST import-boundary tests blocking external agent-framework imports in product runtime paths.

## 3. Boundaries

- No external agent framework dependency in product Core runtime.
- No cross-repo import from `autonomous-agent-core` or `ai-agent-engineering-workflow`.
- No runtime self-modification; ADR-0033 remains binding for autonomous-core projection.
- No automatic R4/R5 execution.
- R4/R5 runtime tools are proposal-only unless a later ADR changes the release boundary.
- No replacement or weakening of `TrustedLoopRuntime`.
- No claim that Enterprise OS runtime task success proves autonomy.
- No workflow-layer LangGraph/CrewAI replacement in this slice.

## 4. Implementation

Implemented in `packages/os_core/src/agent_os_core/agent_runtime/__init__.py`:

- `AgentRunContext`
- `ToolSpec`
- `AgentToolCall`
- `AgentToolResult`
- `PolicyDecision`
- `RuntimePolicyGate`
- `RunStateSnapshot`
- `CheckpointStorePort`
- `InMemoryCheckpointStore`
- `ToolRegistry.register_tool(...)`
- `AgentRuntime.invoke_tool(...)`
- `AgentRuntime.resume_from_checkpoint(...)`
- `TrustedLoopAgentRuntimeAdapter`

Implemented in `packages/persistence/`:

- `SqlAgentCheckpointStore`
- `agent_runtime_checkpoints` SQLAlchemy table
- Alembic migration `0008_agent_runtime_checkpoints`

The original thin-shell compatibility surface remains:

- `ToolRegistry.register(name, tool)`
- `ToolRegistry.call(name, **kwargs)`
- `AgentRuntime.run_tool(name, context, **kwargs)`

## 5. Tests

Added red-first tests:

- `tests/unit/test_agent_runtime_policy.py`
- `tests/unit/test_agent_runtime_tools.py`
- `tests/unit/test_agent_runtime_trace.py`
- `tests/unit/test_agent_runtime_replay_boundary.py`
- `tests/unit/test_agent_runtime_sql_checkpoint.py`
- `tests/unit/test_agent_runtime_import_boundaries.py`
- `tests/unit/test_persistence.py::PersistenceRepositoriesTest.test_agent_runtime_checkpoint_round_trip_and_rewrite`
- `tests/integration/test_trusted_loop_agent_runtime_adapter.py`

Required properties covered:

- policy denial does not execute tool bodies;
- paused `ShellView` denies runtime execution and audits refusal;
- approval-required tools require an `approval_id`;
- non-proposal R4/R5 tools are denied before tool execution even when `approval_id` is present;
- R4/R5 `action_proposal` tools can produce proposals without executing the business action;
- context `risk_ceiling` denies higher-risk tools before tool execution;
- unknown tools and invalid inputs return structured failures;
- tool exceptions return `tool_error` and are traced;
- trace events exist for success and failure paths;
- sensitive trace payload keys are redacted, including common custom-event casing variants;
- snapshots record the last completed runtime boundary;
- matching checkpoint resumes return the stored result without re-executing the tool;
- mismatched call, context, or tool specs fail closed with `CHECKPOINT_MISMATCH` before tool execution;
- checkpoint resume success and failure paths write safe trace events without raw args/output;
- SQL checkpoint snapshots round-trip and update through a fresh store instance;
- SQL checkpoint resume returns a stored result across runtime instances without re-executing the tool;
- checkpoint store failure after tool execution returns `checkpoint_error` and emits `agent_runtime.checkpoint_failed`;
- checkpoint store failure does not mask pre-execution policy denials such as `DENY_HIGH_RISK_EXECUTION`;
- unsupported nondeterministic inputs fail closed;
- external agent frameworks are blocked as product runtime imports;
- Trusted Loop adapter calls `evaluate()` through the runtime envelope and pause blocks before loop execution.

## 6. Verification

Verified locally on 2026-06-24:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
AGENT_OS_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:15432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result:

- ruff check passed;
- ruff format check passed;
- 448 tests OK, 4 skipped in primary unittest discover after syncing current `main`;
- 12 eval tests OK;
- OpenAPI contract drift check passed.
- full local CI parity passed against the disposable PostgreSQL URL above.

## 7. Non-Claims

This ADR does not claim:

- general autonomous intelligence;
- G10/G-Eco transfer into Enterprise OS;
- workflow runtime replacement;
- production-grade concurrency, streaming, async graph execution, or durable arbitrary replay;
- rollback of irreversible external side effects;
- production connector-side exactly-once beyond already implemented governed-action boundaries.

## 8. Next Slices

Future ADRs may add:

- factory/API wiring for runtime-adapter exposure;
- checkpoint backend selection in product factories;
- hard budgets for time/tool/cost;
- concurrency/async graph boundary;
- workflow-layer LangGraph/CrewAI replacement;
- separate autonomous-core mechanism ADR and falsification gate for any object-layer adoption.
