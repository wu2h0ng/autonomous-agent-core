# ADR-0003 Audit: Agent Runtime Capability Gap

Date: 2026-06-26
Status: AUDIT RECORD - NOT A RELEASE CLAIM
Scope: self-developed Agent Runtime trusted substrate in the Enterprise OS deployment layer

## Purpose

This audit maps the current Agent Runtime work against the runtime objective:
a self-developed, auditable, downgradeable, recoverable, governable execution
substrate for the Enterprise OS and a future pattern source for the broader
general-agent program.

This document is not a claim that the runtime is an autonomous-core
implementation, autonomous intelligence, a workflow-engine replacement, or a
release-ready product surface.

## Coverage Matrix

| Objective item | Current evidence | Status |
|---|---|---|
| Typed run/tool/result/policy contracts | `AgentRunContext`, `ToolSpec`, `AgentToolCall`, `AgentToolResult`, `PolicyDecision` in `packages/os_core/src/agent_os_core/agent_runtime/__init__.py`; tests in `tests/unit/test_agent_runtime_*`. | Covered for v0 tool boundary |
| Pre-execution policy gate | `RuntimePolicyGate.check(...)` runs before tool body; policy denial tests prove no tool execution. | Covered |
| Pause channel | `ShellView` denial returns `DENY_PAUSED`; `/runs` and approval-execute pause tests prove stop-before-tool/body behavior. | Covered for current entrypoints |
| Rollback boundary | Rollback remains owned by Trusted Loop / action connector / snapshot machinery, not by Agent Runtime. Runtime does not claim to undo irreversible external side effects. | Covered as boundary, not runtime-owned |
| Approval channel | `/approvals/{approval_id}/execute` runtime envelope preserves `ApprovalRuntime` and `ApprovalContextStore` authority. | Covered on main/origin baseline |
| Correction channel | Branch `codex/agent-runtime-correction-channel` implements `/outcomes` and `/adoptions` runtime-envelope entry paths while preserving P5.1b anti-wirehead semantics and adoption-writer authority. | Implemented locally; review/merge pending |
| Trace-safe execution envelope | Runtime trace events are allowlisted; raw args/output removed; success envelope events persist into `RunTrace`; failure paths are trace-visible. | Covered for `/runs`, approval-execute, and runtime tool calls |
| Checkpoint/replay/recovery boundary | `CheckpointStorePort`, `InMemoryCheckpointStore`, `SqlAgentCheckpointStore`, fingerprint-bound resume, checkpoint save failure typing, and safe resume trace events. | Covered for internal runtime checkpoint boundary |
| Tool permission and risk ceiling | Required permissions, `risk_ceiling`, invalid risk handling, R4/R5 fail-closed policy tests. | Covered |
| Action proposal vs execution separation | R4/R5 non-proposal tools deny even with `approval_id`; R4/R5 proposal tools may produce proposals without executing business action. | Covered |
| Failure-first tests and evals | Runtime policy/tools/trace/replay/sql-checkpoint/budget tests; HTTP and real Trusted Loop adapter tests; branch `make ci` and `ci-local-full` passed. | Covered for implemented slices |
| Trusted Loop / EvidenceChain / Approval / Trace real call path | Real `TrustedLoopRuntime.evaluate()` adapter test; HTTP `/runs`; approval-execute envelope; SQL Safety/EvidenceChain/Trace assertions. | Covered for `/runs` and approval execution |
| No external agent-framework core dependency | Import-boundary tests block LangGraph/CrewAI/LangChain/OpenAI Agents runtime imports. | Covered |
| No cross-repo autonomous-core import | Runtime work stays inside deployment repo; projection is documented as pattern only. | Covered by boundary |
| No automatic R4/R5 execution | Runtime and Trusted Loop tests keep R4/R5 execution fail-closed. | Covered |

## Gaps That Still Matter

### G1: Correction channel is branch-local, not merged

`POST /outcomes` and `POST /adoptions` now traverse the Agent Runtime envelope
on branch `codex/agent-runtime-correction-channel`, with policy, pause, trace,
and checkpoint replay tests. This is still a local feature branch. It is not on
`main`, not pushed, and not released.

The branch-local implementation and review records are:

- `ADR-0003-agent-runtime-correction-channel-scope-20260626.md`
- `ADR-0003-agent-runtime-correction-channel.REVIEW-20260627.md`

Merge still requires explicit founder/CTO authorization.

The implementation preserves:

- `POST /outcomes` as self-report only;
- `POST /adoptions` as the operator/external value writer;
- no adoption writer held by `AgentRuntime` or `TrustedLoopRuntime`;
- safe runtime trace without raw metric deltas, causal-attribution details, or
  full feedback/adoption payloads.

### G2: Public checkpoint resume API is not introduced

The runtime has a checkpoint/replay boundary and SQL persistence adapter, but no
public HTTP/SDK resume surface. This is intentional. A public resume API would
need its own typed contract, authorization model, replay-safety review, and
payload-projection rules.

### G3: True wall-clock interruption and streaming cancellation are not implemented

The budget guard is a deterministic pre-execution guard over declared metadata.
It is not OS-level preemption, async cancellation, streaming abort, token
metering, or production billing.

### G4: Concurrency/workflow engine semantics are not implemented

The current runtime substrate is one policy-gated tool boundary plus selected
Trusted Loop adapters. It is not a graph scheduler, CrewAI/LangGraph replacement,
multi-agent workflow engine, or durable async orchestration layer.

### G5: Production telemetry export policy is not implemented

Runtime trace events are safe and queryable through product trace surfaces, but
no production OTel/export/redaction retention policy is accepted in this slice.

## Recommended Order

1. Complete branch-local correction-channel review without treating self-review
   as merge authorization.
2. Obtain explicit founder/CTO authorization before merging
   `codex/agent-runtime-correction-channel` into local `main`.
3. Run post-merge `make ci` and `ci-local-full` on local `main`.
4. Only after correction-channel merge should the project consider:
   production telemetry/export policy, public resume API, true cancellation, or
   concurrency/workflow runtime semantics.

## Stop Conditions

Stop and return to CTO/founder review if a future runtime slice:

- makes `AgentRuntime` the source of business truth, value truth, or knowledge
  promotion authority;
- grants automatic R4/R5 execution;
- weakens SQL Safety, EvidenceChain, Approval, Trace, or P5.1b anti-wirehead
  separation;
- imports LangGraph, CrewAI, LangChain, OpenAI Agents, or autonomous-core code
  into product Core runtime;
- claims runtime task success as autonomous intelligence evidence;
- exposes raw request parameters, SQL, connector payloads, adoption details, or
  secrets through runtime trace/checkpoint surfaces.
