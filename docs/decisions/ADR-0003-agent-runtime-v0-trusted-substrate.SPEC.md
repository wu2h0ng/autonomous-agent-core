# Agent Runtime v0 Trusted Substrate SPEC

> Status: Accepted and implemented on branch `codex/agent-runtime-v0-trusted-substrate`.
> Goal Card: `ADR-0003-agent-runtime-v0-trusted-substrate.goal-card.md`
> Architecture Review: `docs/architecture_reviews/AR-20260624-agent-runtime-v0-trusted-substrate.md`
> Frontier Research Intake: `docs/architecture_reviews/AR-20260624-frontier-agent-runtime-research-intake.md`

## 0. Gate Status

- Decision status: Accepted by CTO/founder on 2026-06-24.
- Code status: implemented in `packages/os_core/src/agent_os_core/agent_runtime/__init__.py`.
- Runtime dependency status: external agent frameworks are reference-only.
- Correction-channel slice: fast-forward merged to deployment local `main` for `POST /outcomes` and `POST /adoptions` after founder/CTO authorization; push/release remain separate gates. Broader factory/API exposure, true wall-clock interruption, concurrency, and workflow runtime replacement require later ADRs.
- Public resume API slice: implemented branch-locally on `codex/agent-runtime-public-resume-api`; exposes internal-only `runtime_checkpoint_ref` and `POST /agent-runtime/runs/{runtime_run_id}/resume` with policy recheck, fingerprint validation, safe output projection, and safe trace append. It is not merged, pushed, or released.
- Packet A Slice 0 branch `codex/agent-runtime-live-wiring` wires `POST /runs` through the existing Trusted Loop adapter without replacing `TrustedLoopRuntime`.

## 1. Problem

Before ADR-0003 implementation, the `agent_runtime` module was a minimal shell:

- `AgentRunContext`
- `ToolRegistry`
- `StructuredOutputValidator`
- `AgentTraceWriter`
- `AgentRuntime.run_tool(...)`

It was useful as a marker, but not yet a trusted runtime substrate. ADR-0003 implements the missing policy pre-checks, typed tool call/result contracts, trace semantics for failure, pause integration, checkpoint/replay boundary, and a thin Trusted Loop adapter.

## 2. Non-Negotiable Boundaries

- Product Core runtime remains self-developed.
- LangGraph, CrewAI, LangChain, OpenAI Agents SDK, AutoGen, OpenHands, Goose, Aider, Cline, and OpenCode remain reference-only.
- OS Core must stay domain-independent.
- Formal data answers still go through SQL Safety and EvidenceChain.
- R4/R5 actions remain proposal-only unless a separate ADR changes the release boundary.
- No pseudo implementation. Every introduced primitive must have at least one real call path and one negative path.
- The design must remain useful to `autonomous-agent-core` as a mechanism pattern without becoming a cross-repo dependency or weakening C6/C7.
- Runtime self-modification remains forbidden; DGM-style systems are external candidate generators only under the ADR-0033 L0-L3 boundary.

## 3. Source Review Summary

Source snapshots reviewed from official repositories on 2026-06-24:

| Framework | Commit | Mechanisms to study | Borrow | Reject |
|---|---:|---|---|---|
| LangGraph | `711b31550286585b3793857b2a99c8dafd98b785` | `StateGraph`, `Pregel`, `BaseCheckpointSaver`, `StateSnapshot`, `Command`, `interrupt`, `ToolNode` | state/checkpoint vocabulary, interrupt/resume semantics, typed tool runtime envelope | full graph engine, framework dependency, broad message-centric agent loop |
| CrewAI | `2eb4e3a236bada5432290654b8d442345eafb19e` | `Crew`, `Task`, `Flow`, event bus, guardrails, checkpoint config | role/task metadata, guardrail retry semantics, event-triggered checkpoints | role-play orchestration as product runtime, hidden telemetry sharing, open-ended delegation |
| LangChain | `57c83d44bc8ae89a189ad521b9756cfac996039c` | `Runnable`, `RunnableConfig`, `BaseTool`, tool schema validation, `AgentMiddleware`, structured output strategies | uniform invoke/ainvoke shape, config propagation fields, tool input schema and middleware interception | LangChain agent loop, dependency-heavy tool abstractions, provider-coupled structured output |

The paired research intake expands this beyond framework source into papers and benchmarks: ReAct, Reflexion, Voyager, Generative Agents, Toolformer, Tree of Thoughts, AIOS, MemGPT, AI Agents That Matter, AgentBench, WebArena, VisualWebArena, OSWorld, TheAgentCompany, Darwin Godel Machine, open-endedness/safety papers, corrigibility, active inference, and empowerment.

## 3a. Autonomous-Core Projection

This runtime package must be designed so its mechanisms can later be evaluated in `autonomous-agent-core` without contamination.

Allowed projection:

- interface ideas;
- deterministic test patterns;
- checkpoint/replay vocabulary;
- policy-gate and correction-gate patterns;
- external candidate-generation templates.

Forbidden projection:

- cross-repo code imports;
- LLM or framework in the autonomous-core control path;
- any organ/adviser writing action, policy, shell, audit, gate, or forbidden-action state;
- runtime self-edit;
- safety-substrate self-edit;
- claims that runtime task success proves autonomy.

Required autonomous-core mapping for every borrowed research idea:

```text
idea -> mechanism/interface/benchmark/rejected
idea -> C6 impact
idea -> C7 impact
idea -> cheap-baseline risk
idea -> falsification gate required before object-layer adoption
```

## 3b. Design-Question Method

This package is not accepted by choosing a technology stack. It is accepted only when each runtime primitive has answered five design questions:

1. Authority: which layer owns the decision, runtime or policy?
2. Time: when does the decision become effective, and can it be replayed?
3. State: which fields are mutable, checkpointed, or forbidden from mutation?
4. Failure: what happens when validation, policy, tool execution, trace, or checkpointing fails?
5. Evidence: what external reviewer can verify without trusting the agent's self-report?

Required rule: if a proposed feature cannot be placed under one of these questions, it is either out of scope for v0 or needs a separate ADR.

## 3c. Risk Gates Added by Review

The review adds the following gates before implementation:

| Risk | Failure mode | v0 control |
|---|---|---|
| Runtime/policy boundary collapse | Runtime begins encoding business goals, research rewards, or agent strategy. | Runtime may schedule, validate, gate, trace, checkpoint, and dispatch. It must not optimize task policy or encode autonomy claims. |
| Hidden optimizer in evaluation harness | Runtime convenience features make the evaluated agent stronger than declared baselines. | Any autonomous-core adoption needs a separate object-layer ADR, cheap-baseline review, and fresh falsification gate. |
| Deterministic replay gap | Randomness, wall-clock time, external IO, or concurrency makes trace replay unverifiable. | v0 must either record nondeterministic inputs or forbid the feature. Broad parallel execution is out of scope. |
| State consistency race | Parallel calls mutate shared run state or tool outputs overwrite each other. | v0 starts with one tool invocation boundary per runtime call. Shared-state mutation needs a later concurrency ADR. |
| Self-modification pressure | DGM/open-endedness results create pressure to let runtime or safety substrate edit itself. | ADR-0033 remains binding: L4 runtime self-edit and L5 safety-substrate self-edit are forbidden. |
| Rollback illusion | Runtime rolls back code/state but cannot undo external irreversible side effects. | Tool specs must classify side effects; irreversible operations remain approval-bound and proposal-only where current product gates require it. |
| Trace-as-narrative | Logs are human-readable but insufficient for audit or replay. | Failure paths require structured events with stable event names, call ids, trace ids, and redaction. |
| Observer confirmation bias | Founder or agent interprets impressive behavior as autonomy or product readiness. | Acceptance language must separate product runtime capability, research mechanism, and autonomy claim. |
| Approval capture | Human approval becomes a rubber stamp or is misbound to a different operation context. | Runtime must not weaken existing approval-context binding; adapter tests must prove pause/approval gates run before action. |
| Cost/resource denial | Agent loops spend unbounded time, tokens, IO, or tool calls. | v0 context and tool spec carry timeout/risk metadata; hard budgeting can be a later slice but must not be made impossible. |

## 4. Proposed v0 Architecture

```text
External entrypoint
  -> AgentRuntime.invoke_tool(...)
  -> AgentRunContext validation
  -> RuntimePolicyGate.check(...)
  -> StructuredOutputValidator / ToolInputValidator
  -> ToolRegistry.resolve(...)
  -> tool execution
  -> AgentToolResult
  -> AgentTraceWriter + telemetry-compatible event
```

### 4.1 AgentRunContext

Extend the existing context to carry run-scoped governance fields:

```text
tenant_id
workspace_id
principal_id
principal_role
run_id
trace_id
policy_scope
risk_ceiling
approval_id?
checkpoint_id?
max_tool_calls?
tool_timeout_ceiling_ms?
cost_budget_units?
metadata
```

Rules:

- `tenant_id`, `workspace_id`, `principal_id`, `run_id`, and `trace_id` are required.
- Context is immutable during one runtime call.
- Context must not carry secrets.
- `risk_ceiling` is a run-scoped maximum tool risk (`R0`..`R5`); tools above it are denied before the tool body.
- `max_tool_calls`, `tool_timeout_ceiling_ms`, and `cost_budget_units` are run-scoped pre-execution budgets. Invalid or exhausted budgets deny before the tool body.

### 4.2 ToolSpec and ToolRegistry

Each registered tool must expose:

```text
name
description
input_schema or required_keys
risk_level
side_effect_class
required_permissions
requires_evidence
requires_approval
timeout_ms?
estimated_cost_units
```

Rules:

- Duplicate registration fails.
- Unknown tool fails.
- Tool name must be stable and non-empty.
- Side-effecting tools require explicit policy clearance.
- `timeout_ms` and `estimated_cost_units` are declared metadata used by runtime budget guards. They are not wall-clock interruption or production billing.

### 4.3 RuntimePolicyGate

`RuntimePolicyGate` decides before tool execution:

```text
ALLOW
DENY_MISSING_PERMISSION
DENY_REQUIRES_APPROVAL
DENY_PAUSED
DENY_UNSUPPORTED_RISK
DENY_INVALID_RISK_CEILING
DENY_RISK_CEILING
DENY_HIGH_RISK_EXECUTION
DENY_INVALID_CONTEXT
```

Rules:

- The gate runs before `ToolRegistry.call`.
- Deny outcomes return structured runtime failures, not successful tool results.
- Paused corrigibility shell denies all runtime execution except explicitly allowed read-only observation.
- Tool risk must be at or below `AgentRunContext.risk_ceiling` even when the caller has the named permission and an `approval_id`.
- R4/R5 non-proposal tools return `DENY_HIGH_RISK_EXECUTION` even with `approval_id`; they are proposal-only in this runtime slice.
- R4/R5 proposal tools must declare a proposal side-effect class such as `action_proposal`; that tool may produce an action proposal but must not execute the business action.
- Lower-risk side-effecting execution still requires `approval_id`.

### 4.4 AgentToolCall and AgentToolResult

Introduce typed execution records:

```text
AgentToolCall:
  call_id
  tool_name
  args
  context_ref

AgentToolResult:
  call_id
  tool_name
  status: ok | denied | validation_error | tool_error
  output?
  error_code?
  error_message?
  trace_id
```

Rules:

- Validation errors do not call the tool body.
- Tool exceptions are captured as `tool_error` and traced.
- Policy denials do not call the tool body.

### 4.5 Trace and Telemetry

Every runtime call writes trace events:

```text
agent_runtime.invocation_started
agent_runtime.policy_allowed / agent_runtime.policy_denied
agent_runtime.validation_failed
agent_runtime.tool_started
agent_runtime.tool_succeeded / agent_runtime.tool_failed
agent_runtime.invocation_finished
```

Rules:

- Trace payloads must not include secrets or full sensitive business payloads.
- Failure paths must be trace-visible.
- The trace writer can remain in-memory in v0 but must expose a port-compatible shape.

### 4.6 Checkpoint/Resume Boundary

v0 does not implement a general graph engine. It introduces a narrow run checkpoint boundary:

```text
RunStateSnapshot:
  run_id
  trace_id
  step_id
  status
  pending_tool_call?
  last_result?
  metadata
```

Rules:

- Checkpoint support is a port, not a framework dependency.
- v0 may ship with in-memory snapshot store plus tests.
- Durable implementation lives in the persistence adapter layer and must not introduce a persistence import into OS Core.
- Snapshots are evidence boundaries, not autonomy claims.
- Snapshot metadata must include verifiable fingerprints for the tool call, relevant run context, and registered tool spec.
- `AgentRuntime.resume_from_checkpoint(...)` may return a stored `last_result` only when all checkpoint fingerprints match the requested resume call and context.
- Fingerprint mismatch, missing checkpoint store, missing `run_id`, missing snapshot, or unknown tool must return a structured validation error and must not execute the tool body.
- `AgentRuntime.resume_from_checkpoint(...)` must emit safe trace events for resume start, success, and failure without raw args/output.
- `SqlAgentCheckpointStore` must persist `RunStateSnapshot` rows by `run_id` and allow a later runtime/store instance to resume only through the same fingerprint validation.
- Checkpoint save failures after tool execution must return a structured `checkpoint_error` result by default and emit an `agent_runtime.checkpoint_failed` trace event; raw checkpoint exception details must not be written to trace payloads. A tool may explicitly set `preserve_result_on_checkpoint_failure` only when returning a completed result is safer than inducing duplicate side-effect retry, such as a completed correction-channel write.
- Checkpoint store failures must not mask pre-execution denials or validation failures. A policy denial such as `DENY_HIGH_RISK_EXECUTION` remains the returned result if the tool body never started.
- Any nondeterministic value needed to explain a result must be captured in trace metadata or explicitly declared out of scope for replay.

### 4.7 TrustedLoopRuntime Adapter

Do not rewrite `TrustedLoopRuntime`.

The first adapter should be one deterministic wrapper that invokes the existing Trusted Loop through the runtime envelope and proves:

- entrypoint exists;
- policy gate is called;
- trace event is emitted;
- pause blocks before loop execution;
- existing SQL Safety/EvidenceChain behavior is not bypassed.

### 4.8 Live HTTP `/runs` Wiring

Packet A Slice 0 composes the existing Trusted Loop adapter into the HTTP run surface:

```text
POST /runs
  -> AgentRunContext
  -> TrustedLoopAgentRuntimeAdapter.evaluate()
  -> RuntimePolicyGate.check()
  -> AgentRuntime.invoke_tool()
  -> TrustedLoopRuntime.evaluate()
  -> EvidenceChain / persisted RunTrace / user_result
```

Rules:

- `POST /runs` constructs a typed `AgentRunContext` and grants only `trusted_loop:evaluate` for this boundary.
- Runtime envelope trace events must not include raw request parameters or raw tool output.
- App-level runtime diagnostics must be request-scoped or otherwise bounded; diagnostic storage must not accumulate all requests for the app lifetime.
- Successful `POST /runs` runtime-envelope events must be persisted into the queryable business `RunTrace` as safe allowlisted metadata, so `/traces/{trace_id}` can prove the HTTP run crossed the runtime policy envelope without exposing raw request parameters or raw tool output.
- `RuntimePolicyGate` denial returns the existing blocked response contract with `stage="agent_runtime"`.
- A paused `ShellView` denies before `agent_runtime.tool_started` and persists a queryable blocked `RunTrace`.
- Internal runtime/tool failures return a sanitized service error instead of a business block and must not expose raw exception text to external report-key projections.
- This `/runs` slice did not change `/approvals/{approval_id}/execute`, did not make R4/R5 executable, and did not introduce a graph/workflow engine.

### 4.9 HTTP `/approvals/{approval_id}/execute` Envelope

The approval-execute slice composes the existing approval-resume path into a
narrow runtime envelope:

```text
POST /approvals/{approval_id}/execute
  -> operator-key auth
  -> AgentRunContext(approval_id, risk_ceiling=R3)
  -> TrustedLoopApprovalExecutionRuntimeAdapter.execute()
  -> RuntimePolicyGate.check()
  -> AgentRuntime.invoke_tool()
  -> TrustedLoopRuntime.approve_and_execute_pending_operation()
  -> ApprovalRuntime / ApprovalContextStore / EvidenceChain / OperationTrace
```

Rules:

- HTTP `X-Operator-Key` remains the transport authentication boundary.
- `AgentRuntime` does not become the approval authority; approval status,
  pending-context claim/release, exact operation/evidence/action binding, stale
  claim behavior, and replay prevention remain owned by `ApprovalRuntime` and
  `ApprovalContextStore`.
- The runtime tool is `trusted_loop.approval_execute` with risk `R3`,
  side-effect class `approval_execution`, permission `trusted_loop:approval_execute`,
  and `requires_approval=True`.
- `AgentRunContext.approval_id` is bound from the route path; missing or paused
  runtime context denies before the tool body.
- R4/R5 automatic execution remains fail-closed inside the existing
  `TrustedLoopRuntime.execute_approved_operation(...)` path.
- Runtime envelope trace events must not include raw request parameters,
  raw approval payloads, or raw connector output.
- Existing 404/409 approval execution response contracts are preserved.

### 4.10 Budget Guard

The budget slice adds a deterministic pre-execution guard:

```text
AgentRunContext(max_tool_calls, tool_timeout_ceiling_ms, cost_budget_units)
  + ToolSpec(timeout_ms, estimated_cost_units)
  -> AgentRuntime budget check
  -> agent_runtime.budget_reserved OR agent_runtime.budget_denied
  -> tool body only if budget is valid and not exhausted
```

Rules:

- Budget checks happen after input validation and before `agent_runtime.tool_started`.
- `max_tool_calls` is counted per `run_id` for tool bodies that are allowed to start.
- `cost_budget_units` is consumed by declared `ToolSpec.estimated_cost_units` before the tool body starts.
- `tool_timeout_ceiling_ms` denies tools without a declared `timeout_ms` and tools whose declared timeout exceeds the run ceiling.
- Invalid budget values return `DENY_INVALID_BUDGET`.
- Exhausted tool-call budget returns `DENY_TOOL_CALL_BUDGET_EXCEEDED`.
- Exhausted cost budget returns `DENY_COST_BUDGET_EXCEEDED`.
- Timeout-ceiling violation returns `DENY_TIMEOUT_BUDGET`.
- Budget trace events must not include raw args, outputs, SQL, connector payloads, or secrets.
- This is not wall-clock preemption, async cancellation, streaming cancellation, or production cost metering.

## 5. Test-First Plan

Add tests before implementation:

- `tests/unit/test_agent_runtime_policy.py`
  - missing principal denied;
  - missing permission denied;
  - paused shell denied;
  - tool above context risk ceiling denied before tool body;
  - tool at context risk ceiling allowed;
  - R4/R5 non-proposal tools denied even with `approval_id`;
  - R4/R5 proposal tools can produce proposals without executing business actions;
  - lower-risk side-effecting tools require `approval_id`;
  - denied call does not execute tool body.
- `tests/unit/test_agent_runtime_tools.py`
  - duplicate tool registration fails;
  - unknown tool fails;
  - required input validation blocks tool body;
  - successful safe tool returns typed `AgentToolResult`.
- `tests/unit/test_agent_runtime_trace.py`
  - success and failure both emit required trace events;
  - trace payload redacts configured sensitive keys;
  - default custom-event redaction matches sensitive keys case-insensitively.
- `tests/unit/test_agent_runtime_replay_boundary.py`
  - snapshot metadata records the last completed runtime boundary;
  - matching checkpoint resume returns the stored result without executing the tool body again;
  - matching checkpoint resume emits safe start/success trace events without raw output;
  - call mismatch fails closed before tool execution;
  - checkpoint mismatch emits a safe failure trace event without raw call args;
  - tool spec mismatch fails closed before tool execution;
  - unsupported nondeterministic inputs fail closed or are marked unreplayable in a structured result;
  - checkpoint store failure after tool execution returns a structured `checkpoint_error` by default and emits `agent_runtime.checkpoint_failed`;
  - checkpoint store failure does not mask pre-execution policy denial.
- `tests/unit/test_agent_runtime_sql_checkpoint.py`
  - SQL checkpoint resume returns the stored result across runtime/store instances without executing the tool body again;
  - SQL checkpoint mismatch fails closed before tool execution.
- `tests/unit/test_agent_runtime_budget.py`
  - tool-call budget denies before the tool body;
  - invalid budget denies before the tool body;
  - timeout ceiling denies a tool whose declared timeout is too high;
  - timeout ceiling denies a tool whose timeout is undeclared;
  - declared cost budget is consumed per run and denies before the next tool body when exhausted.
- `tests/unit/test_persistence.py`
  - `SqlAgentCheckpointStore` round-trips and updates a `RunStateSnapshot`.
- `tests/unit/test_agent_runtime_import_boundaries.py`
  - fail if product Core imports `langgraph`, `crewai`, `langchain`, or `openai_agents`.
- `tests/integration/test_trusted_loop_agent_runtime_adapter.py`
  - one safe Trusted Loop call goes through the runtime adapter;
  - paused shell blocks before Trusted Loop execution.
- `tests/unit/test_http_app.py`
  - `POST /runs` traverses the Agent Runtime envelope and emits `agent_runtime.policy_allowed`, `agent_runtime.tool_started`, and `agent_runtime.tool_succeeded`;
  - a paused shell returns a blocked response with `DENY_PAUSED` at `stage="agent_runtime"` and no `agent_runtime.tool_started` event;
  - the paused denial trace id is queryable through `/traces/{trace_id}`;
  - runtime/tool exceptions return sanitized HTTP 500 errors without exposing raw exception text to external report-key projections;
  - HTTP runtime diagnostics are request-scoped and do not retain prior request `run_id`s;
  - sanitized Agent Runtime HTTP 500 failures are declared in the OpenAPI contract with a typed response schema;
  - successful `POST /runs` persists `agent_runtime.policy_allowed`, `agent_runtime.tool_started`, and `agent_runtime.tool_succeeded` into `/traces/{trace_id}` without raw request parameters;
  - `POST /approvals/{approval_id}/execute` traverses the approval-execute runtime envelope;
  - paused-shell denial blocks approval execution before connector writes.

## 6. Implementation Tasks

- [x] T0: CTO/founder review of Goal Card, SPEC, architecture review, and frontier research intake.
- [x] T1: write red tests for registry, policy, validation, trace, and import boundaries.
- [x] T2: add typed `AgentToolCall`, `AgentToolResult`, `ToolSpec`, and `PolicyDecision`.
- [x] T3: implement `RuntimePolicyGate` with deterministic allow/deny outcomes.
- [x] T4: extend `ToolRegistry` to register `ToolSpec + callable` while keeping backwards compatibility where feasible.
- [x] T5: extend `AgentRuntime` with `invoke_tool(...)` returning `AgentToolResult`.
- [x] T6: wire trace events for all success and failure paths.
- [x] T7: add minimal checkpoint port and in-memory snapshot implementation.
- [x] T8: add Trusted Loop adapter smoke path without changing SQL Safety/EvidenceChain semantics.
- [x] T9: add replay-boundary and nondeterminism handling tests before adding any async, streaming, or parallel runtime behavior.
- [x] T9a: add fingerprint-bound checkpoint resume tests for call/context/spec mismatch denial and matching-result replay without tool re-execution.
- [x] T9b: add durable SQL checkpoint-store adapter, schema, Alembic migration, and cross-runtime resume tests while keeping OS Core persistence-independent.
- [x] T9c: enforce R4/R5 proposal-only runtime policy while preserving approved execution only for lower-risk side-effecting tools.
- [x] T9d: harden explicit custom trace-event sensitive-key redaction with case-insensitive matching.
- [x] T9e: make checkpoint resume success/failure paths trace-visible without raw args/output.
- [x] T9f: prevent checkpoint persistence failures from masking pre-execution denials.
- [x] T10: add autonomous-core projection note for any mechanism that should later become an object-layer ADR.
- [x] T11: update `docs/CURRENT_STATE.yaml`, README, and implementation-local indexes after implementation gate and tests are green.
- [x] T12: wire `POST /runs` through the Agent Runtime envelope with endpoint-level success and pause-denial tests.
- [x] T13: remediate live-wiring review blockers for runtime/tool error sanitization and pre-loop runtime denial trace persistence.
- [x] T14: bound HTTP runtime diagnostics by replacing the shared app-lifetime adapter/writer with per-request adapter/writer instances and retaining only the latest request diagnostics.
- [x] T15: declare sanitized `/runs` Agent Runtime 500 failures in OpenAPI as `AgentRuntimeErrorResponse` and add a contract regression test.
- [x] T16: persist safe successful `/runs` Agent Runtime envelope events into the business `RunTrace`.
- [x] T17: route `POST /approvals/{approval_id}/execute` through a narrow Agent Runtime envelope while preserving Approval/ApprovalContextStore authority and R4/R5 fail-closed execution.
- [x] T18: select Agent Runtime checkpoint backend in the product factory, inject it into HTTP runtime adapters, and persist SQL checkpoint resume output as an allowlisted Trusted Loop summary.
- [x] T19: add pre-execution runtime budget guard for tool-call count, declared timeout ceiling, and declared cost units with safe trace events and failure-first tests.

## 7. Stop Conditions

Stop and return to CTO review if:

- the runtime begins to encode task strategy, business goals, research rewards, or autonomy claims;
- the design needs an external framework dependency to pass;
- the Trusted Loop adapter requires weakening SQL Safety, EvidenceChain, Approval, or Trace;
- runtime policy cannot be tested without mocks that assert the fixture value;
- implementation starts to become a general workflow engine before the trusted substrate is real;
- import-boundary tests conflict with existing approved dependencies.
- nondeterministic execution, parallelism, or external IO is added without a trace/replay boundary;
- rollback language implies irreversible external side effects can be undone by runtime state rollback.

## 8. Acceptance Criteria

- All red-first tests pass after implementation.
- No product runtime dependency on external agent frameworks.
- Runtime has a real entry point.
- Runtime has typed result contracts.
- Runtime has policy-deny, validation-error, missing-tool, and tool-exception failure paths.
- Runtime denies non-proposal R4/R5 execution before the tool body, even when a caller supplies `approval_id`.
- Runtime writes trace events for both allow and deny paths.
- Successful HTTP `/runs` persists safe runtime-envelope events into queryable `RunTrace` without raw request parameters or raw tool output.
- Runtime writes a structured trace event and returns a typed failure if checkpoint persistence fails.
- Trusted Loop adapter does not bypass existing governance modules.
- Runtime remains a substrate: it does not own business truth, research conclusions, autonomy claims, or optimization policy.
- Replay boundaries are explicit enough that an external reviewer can determine what was executed, denied, failed, or declared unreplayable.
- Checkpoint resume is fail-closed: it returns a stored result only for a matching tool call, run context, and tool spec, and mismatches do not execute tools.
- Durable checkpoint storage is an adapter behind `CheckpointStorePort`; OS Core does not import SQLAlchemy or `agent_os_persistence`.
- HTTP approval execution traverses the runtime envelope, and paused-shell denial stops before connector writes.
- Runtime budget guard denies invalid or exhausted tool-call, undeclared/exceeded declared timeout, and declared cost budgets before `agent_runtime.tool_started` and without raw payload trace leakage.
