# ADR-0003 Audit: Agent Runtime Capability Gap

Date: 2026-06-26
Status: AUDIT RECORD UPDATED WITH BRANCH-LOCAL PUBLIC RESUME API - NOT A RELEASE CLAIM
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
| Correction channel | Deployment local `main` implements `/outcomes` and `/adoptions` runtime-envelope entry paths while preserving P5.1b anti-wirehead semantics and adoption-writer authority. | Covered on local main; not pushed or released |
| Trace-safe execution envelope | Runtime trace events are allowlisted; raw args/output removed; success envelope events persist into `RunTrace`; failure paths are trace-visible. | Covered for `/runs`, approval-execute, and runtime tool calls |
| Checkpoint/replay/recovery boundary | `CheckpointStorePort`, `InMemoryCheckpointStore`, `SqlAgentCheckpointStore`, fingerprint-bound resume, checkpoint save failure typing, safe resume trace events, and branch-local internal-only HTTP resume API. | Covered for internal runtime checkpoint boundary; HTTP surface branch-local only |
| Tool permission and risk ceiling | Required permissions, `risk_ceiling`, invalid risk handling, R4/R5 fail-closed policy tests. | Covered |
| Action proposal vs execution separation | R4/R5 non-proposal tools deny even with `approval_id`; R4/R5 proposal tools may produce proposals without executing business action. | Covered |
| Failure-first tests and evals | Runtime policy/tools/trace/replay/sql-checkpoint/budget tests; HTTP and real Trusted Loop adapter tests; branch `make ci` and `ci-local-full` passed. | Covered for implemented slices |
| Trusted Loop / EvidenceChain / Approval / Trace real call path | Real `TrustedLoopRuntime.evaluate()` adapter test; HTTP `/runs`; approval-execute envelope; SQL Safety/EvidenceChain/Trace assertions. | Covered for `/runs` and approval execution |
| No external agent-framework core dependency | Import-boundary tests block LangGraph/CrewAI/LangChain/OpenAI Agents runtime imports. | Covered |
| No cross-repo autonomous-core import | Runtime work stays inside deployment repo; projection is documented as pattern only. | Covered by boundary |
| No automatic R4/R5 execution | Runtime and Trusted Loop tests keep R4/R5 execution fail-closed. | Covered |

## Gaps That Still Matter

### G1: Correction channel is local-main only, not pushed or released

`POST /outcomes` and `POST /adoptions` now traverse the Agent Runtime envelope
on deployment local `main`, with policy, pause, trace, and checkpoint replay
tests. This is a local merge only. It is not pushed, not released, and not an
external shipment claim.

The implementation and review records are:

- `ADR-0003-agent-runtime-correction-channel-scope-20260626.md`
- `ADR-0003-agent-runtime-correction-channel.REVIEW-20260627.md`
- `ADR-0003-agent-runtime-correction-channel.MERGE-READINESS-20260627.md`

The founder/CTO local merge authorization has been used for the local
fast-forward merge. Push and release remain separate gates.

The implementation preserves:

- `POST /outcomes` as self-report only;
- `POST /adoptions` as the operator/external value writer;
- no adoption writer held by `AgentRuntime` or `TrustedLoopRuntime`;
- safe runtime trace without raw metric deltas, causal-attribution details, or
  full feedback/adoption payloads.

### G2: Public checkpoint resume API is branch-local only

Branch `codex/agent-runtime-public-resume-api` introduces the first HTTP resume
surface for checkpointed `/runs` runtime execution:

- internal `POST /runs` responses include a safe `runtime_checkpoint_ref`
  only when a matching persisted checkpoint exists;
- external report-key projections receive `runtime_checkpoint_ref = null`;
- `POST /agent-runtime/runs/{runtime_run_id}/resume` requires the internal
  `runtime:resume` scope;
- `AgentRuntime.resume_from_checkpoint` rechecks `RuntimePolicyGate` before
  returning checkpoint data;
- resume validates call/context/tool fingerprints and fails closed on mismatch;
- successful resume appends safe runtime events to `RunTrace`;
- OpenAPI declares typed `RuntimeResumeErrorResponse` schemas for `404`, `409`,
  `500`, and `503` resume failures;
- checkpoint backend read failures return typed `CHECKPOINT_READ_FAILED` errors
  without backend DSNs, credentials, raw args, or plain-text 500 responses;
- responses expose only a safe `output_ref`, not raw args, raw SQL, raw tool
  output, or connector payloads.

This slice is branch-local. It is not merged, pushed, released, or reviewed as
an external API shipment. The record is
`ADR-0003-agent-runtime-public-resume-api.IMPLEMENTATION-20260627.md`.

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

1. Keep push and release blocked unless separately authorized.
2. Choose the next runtime slice only through its own ADR/gate, with
   failure-first tests and docs sync.
3. Candidate next slices after public-resume review:
   production telemetry/export policy, true cancellation, or
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
