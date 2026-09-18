# AR-20260707: Architecture review — staged-out capabilities C/D/E (ADR-0013)

- Status: **All findings fixed; all next slices implemented** — C/D/E engine layers + F1/F2/F3 fixes + F4 trace + durable persistence + runtime selection point + TrustedLoop run() integration + C/D trace wiring all implemented and CI-green (1096 tests). All AR-20260707 next slices now IMPLEMENTED: durable persistence (PolicyApprovalRecordStorePort + SqlPolicyApprovalRecordStore + alembic 0013), runtime selection point (ApprovalRouter + RuntimeFactory.build_approval_router), TrustedLoopRuntime.run() behavioral integration (pre-approved actions execute directly with policy_evaluated->pre_approved->executed trace), and C/D OperationTrace wiring (injectable trace_sink for workflow transitions + MCP invocations). All flags remain default-off.
- Review identity: `builder-id: codex`, `reviewed-by: codex (self-audit)`
- Parent: `docs/decisions/ADR-0013-master-implementation-roadmap-concurrent.md`, `docs/decisions/ADR-0012-r4-r5-automatic-execution-release.md`
- Touches: `packages/os_core/src/agent_os_core/mcp_gateway/`, `packages/os_core/src/agent_os_core/workflow.py`, `packages/os_core/src/agent_os_core/policy_engine.py`, `packages/contracts/src/agent_os_contracts/architecture.py` (OperationState extension planned), `packages/contracts/src/agent_os_contracts/trusted_loop.py` (ActionProposal.execution_mode already added).
- Verification basis: `make ci` green — 1030 unit tests / 4 skipped, 12 eval OK, lint/format/anti-stub/openapi-drift/eval-threshold-report/current-state-verification all pass.

> **Scope note.** This AR reviews the OS Core engine layer only. It does not authorize turning any feature flag on in a deployed environment. All flags (`mcp_gateway`, `full_bpm_workflow`, `r4_r5_auto_execution`) remain default-off. Push/release remain founder/CTO gates.

## 1. Context

Workstreams C (MCP Gateway), D (Full BPM), E (R4/R5 auto-execution PolicyEngine) were implemented under ADR-0013 concurrent authorization. This AR audits the result against the hard boundaries (AGENTS.md), ADR-0006 (no external agent framework in OS Core), ADR-0007 (no cross-repo import), ADR-0012 (R4/R5 preconditions), and the project's safety invariants (SQL Safety / EvidenceChain / C7 pause supremacy / trace-by-default).

## 2. Findings by severity

### 2.1 MUST-FIX (before any flag may be enabled)

#### F1 — E: TOCTOU between policy mint and consume (R5 correctness / C7 supremacy)

`PolicyEngine.evaluate` checks `self._paused()` and, on success, mints a `PolicyApprovalRecord`. But `consume_approval` (the execution-time call) does **not** re-check the pause shell. ADR-0012 §3.5 requires "A paused shell must block any automatic R4/R5 execution at the runtime level, regardless of tenant policy."

Between mint and consume the shell can be paused, the policy revoked, or the record consumed by a concurrent caller. The consume path must fail-closed.

- **Fix:** `consume_approval` must re-check pause shell and record validity (active + version match) at consume time, and must be the single minted-record consumer (idempotent). Return a typed denial when the check fails rather than silently consuming.

#### F2 — E: duplicate mint (idempotency hole)

`evaluate` mints a new `PolicyApprovalRecord` on every call, even when an active record for the same `(proposal_id, rule_id)` already exists. A retried evaluate (e.g. after a transient transport error) produces multiple active records, each independently consumable → potential double-execution.

- **Fix:** `evaluate` must reuse an existing active record for the same proposal when guardrails still hold, or explicitly record-and-deny a second mint. Idempotency key on proposal.

### 2.2 SHOULD-FIX (correctness / observability)

#### F3 — C: audit decision semantics conflate execution failure with allowed

`McpToolRouter` records `decision="allowed", reason="tool_error"` when the handler raises. Downstream queries for `decision=="allowed"` will count execution failures as allowed invocations. The audit field should distinguish `executed_ok` from `executed_error`.

- **Fix:** use distinct decision values (`allowed`, `executed_error`, `denied`) rather than overloading `allowed` + a reason string.

#### F4 — OperationTrace not wired for C/D/E (ADR-0012 §3.4 gap)

None of the three modules writes `OperationTrace`/`RunTrace`. ADR-0012 §3.4 requires `proposed → policy_evaluated → policy_pre_approved → executed → observed` for auto-executed R4/R5. `OperationState` lacks the policy states.

- **Fix (subsequent slice):** extend `OperationState` with `POLICY_EVALUATED`/`POLICY_PRE_APPROVED`; wire `PolicyEngine.evaluate` → `OperationTraceBuilder`; wire workflow transitions and MCP invokes to trace. This is a follow-up slice, not a blocker for the engine itself, but is a blocker for **enabling** the R4/R5 flag.

### 2.3 NON-BLOCKING observations

- **O1 — D: passive timeout.** `timeout_check` must be called by an external scheduler; the engine does not self-schedule. This is an acceptable design boundary but must be documented as a deployment requirement when the flag is enabled.
- **O2 — D: in-memory only.** `WorkflowRuntime` has no persistence port. A durable port is a subsequent slice; not a correctness blocker while the flag is off.
- **O3 — D: ApprovalLiteRuntime vs WorkflowRuntime coexistence.** Both exist; the flag chooses. The runtime selection point (which path a proposal takes) is not yet wired in `TrustedLoopRuntime`. Documented, not a defect.
- **O4 — E: guard_conditions schema unvalidated.** Unknown guard keys fail-closed (safe) but are silent. Acceptable fail-closed; add diagnostics later.
- **O5 — C: double gating.** `McpToolRouter.invoke` checks context risk ceiling, and `RuntimePolicyGate` (when routed through `AgentRuntime`) checks it again. Defense-in-depth, not redundant waste — acceptable.
- **O6 — C: attach wrapper raises.** When routed through `AgentRuntime`, a deny becomes a generic `tool_error` rather than surfacing the deny reason. Acceptable for the flag-off default; improve projection when the flag is enabled.

## 3. Boundary compliance audit

| Boundary | C | D | E | Evidence |
|---|---|---|---|---|
| OS Core does not import domain_packs/providers/action_connectors/examples | ✓ | ✓ | ✓ | only `agent_os_contracts` + internal imports |
| No external agent framework (ADR-0006) | ✓ | ✓ | ✓ | no LangGraph/CrewAI/OpenAI SDK imports |
| No cross-repo import (ADR-0007) | ✓ | ✓ | ✓ | no autonomous-core / workflow-repo imports |
| Feature flag default-off | ✓ | ✓ | ✓ | `mcp_gateway`/`full_bpm_workflow`/`r4_r5_auto_execution` default False |
| R4/R5 default proposal-only | ✓ | n/a | ✓ | E returns `proposal_only` when flag off or no policy/matching rule |
| C7 pause supremacy | partial | n/a | **F1: mint-time only** | E checks pause at evaluate; consume-time check missing (F1) |
| SQL Safety / EvidenceChain unweakened | ✓ | ✓ | ✓ | untouched |
| Test-first (red→green) | ✓ | ✓ | ✓ | each module: ImportError red, then green |
| Failure path covered | ✓ | ✓ | ✓ | each module has deny/error negative tests |

## 4. Decision

- C, D, E engine layers are **accepted as flag-off implementations**.
- F1 and F2 are **mandatory fixes** before the R4/R5 flag may be enabled in any non-test context.
- F3 is a should-fix for C observability.
- F4 (OperationTrace wiring) is a **mandatory subsequent slice** before enabling R4/R5 auto-execution; it does not block the engine existing.
- O1–O6 are recorded as follow-ups; none block the current state.

## 5. What this AR does NOT authorize

- Turning on `r4_r5_auto_execution`, `full_bpm_workflow`, or `mcp_gateway` in a deployed environment.
- Push or release of local main.
- Claiming R4/R5 auto-execution is "done" — the engine exists, the durable+trace slice (F4) and consume-time recheck (F1) remain.
- Any change to the autonomy narrative (RR-0024 word gate remains).

## 6. Next slices (in order)

1. Fix F1 (consume-time pause recheck) + F2 (idempotent mint) — test-first.
2. Fix F3 (C audit decision values) — test-first.
3. Extend `OperationState` + wire OperationTrace for C/D/E (F4) — test-first.
4. Durable `PolicyApprovalRecordStore` port + postgres adapter.
5. Wire runtime selection point (TrustedLoopRuntime → ApprovalLite vs WorkflowRuntime).
