# Goal Card - Agent Runtime v0 Trusted Substrate

> Paired decision package: `ADR-0003-agent-runtime-v0-trusted-substrate.SPEC.md`, `docs/architecture_reviews/AR-20260624-agent-runtime-v0-trusted-substrate.md`, and `docs/architecture_reviews/AR-20260624-frontier-agent-runtime-research-intake.md`.
> Status: Accepted and implemented on branch `codex/agent-runtime-v0-trusted-substrate`.

- Objective: turn the current self-developed `agent_runtime` shell into a small, trusted execution substrate whose first implementation target is Enterprise OS, but whose design contract is constrained by autonomous-core requirements: C6 organ-not-subject, C7 corrigibility, G10 subject-side coupling, ADR-0033 self-modification boundary, and G-Eco freeze discipline.
- Business value: create the runtime layer that can later host richer workflow/agent behavior while preserving the non-bypassable Trusted Loop: policy gate, evidence, approval, trace, pause, and audit remain first-class.
- Task type: backend architecture + test-first runtime slice.
- Risk level: R3 medium/high engineering risk. It touches OS Core runtime boundaries, tool execution, policy, trace, and later Trusted Loop adaptation. It does not approve automatic R4/R5 execution.
- Owner: CTO/founder gate approved implementation on 2026-06-24. Codex implemented the scoped runtime v0; Claude/CTO lane may review diff and risk.
- Max implementation retries: 2 before a fresh CTO review.

## Scope Include

- `packages/os_core/src/agent_os_core/agent_runtime/`
  - `AgentRunContext`
  - `ToolRegistry`
  - `StructuredOutputValidator`
  - `AgentTraceWriter`
  - `AgentRuntime`
  - new runtime policy and typed tool invocation primitives
- OS Core integration points:
  - `corrigibility` pause view as a mandatory runtime pre-check
  - `trace`/telemetry-compatible event writing
  - `operation_state_machine` adapter only where needed
  - `TrustedLoopRuntime` adapter after the substrate has direct tests
- Tests:
  - unit tests for policy allow/deny, tool schema validation, missing tool, failure trace, and pause refusal
  - import-boundary guard that fails if product Core imports external agent frameworks
  - integration smoke test showing one safe deterministic tool call through the runtime
- Research intake:
  - framework source review: LangGraph, CrewAI, LangChain
  - frontier papers and benchmarks: ReAct, Reflexion, Voyager, Generative Agents, Toolformer, Tree of Thoughts, AIOS, MemGPT, AI Agents That Matter, AgentBench, WebArena, VisualWebArena, OSWorld, TheAgentCompany, DGM, open-endedness/safety, corrigibility, active inference, empowerment
  - cross-layer mapping for autonomous-core, Enterprise OS, and workflow

## Scope Exclude

- No external framework dependency in product runtime.
- No cross-repo import from `autonomous-agent-core` or `ai-agent-engineering-workflow`.
- No replacement of `TrustedLoopRuntime`.
- No general multi-agent marketplace, plugin ecosystem, MCP write gateway, or open-ended autonomous loop.
- No automatic R4/R5 execution.
- No workflow-layer LangGraph/CrewAI replacement in this slice. That is a later meta-layer task after the product runtime substrate is real.
- No autonomous-core implementation in this slice. Any object-layer adoption requires a separate autonomous-core ADR and fresh falsification gate.

## Source Review Requirement

Before implementation, read current source and research from primary sources and record exact commits/URLs:

- LangGraph: state graph, checkpoint, interrupt/resume, tool node.
- CrewAI: crew/task execution, guardrails, event bus, checkpoint/resume.
- LangChain: Runnable interface, tool schema, middleware, structured output.
- Papers/benchmarks/open-endedness/corrigibility/agency sources listed in the frontier research intake.

The review may borrow mechanisms and tests. It must not copy product code or introduce framework imports.

## Required Outputs

- Architecture review with source-review findings and explicit borrow/reject list.
- SPEC with typed contracts, negative paths, test plan, and staged implementation tasks.
- Runtime design-question answers for each new primitive: authority, time, state, failure, and evidence.
- Red-first tests before runtime implementation.
- Runtime implementation with a real entry point and failure paths.
- Current-state update after each gate.

## Required Checks

- A test must fail if `ToolRegistry` bypasses policy before execution.
- A test must fail if a paused corrigibility shell still allows runtime execution.
- A test must fail if invalid tool input reaches the tool body.
- A test must fail if an unregistered tool is treated as success.
- A test must fail if tool failure is not traced.
- A boundary test must fail if `langgraph`, `crewai`, `langchain`, or `openai_agents` is imported under product Core runtime paths.
- A replay-boundary test must fail if unsupported nondeterministic inputs are silently treated as replayable.
- A review check must reject any runtime primitive that embeds business strategy, research reward, or autonomy-claim logic.

## Gate

Implementation was authorized by CTO/founder on 2026-06-24 and completed on branch `codex/agent-runtime-v0-trusted-substrate`. Merge/release remains a separate gate.
