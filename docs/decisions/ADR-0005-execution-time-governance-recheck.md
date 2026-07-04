# ADR-0005: Execution-time governance recheck (corrigibility + seam) before connector side-effect

- Status: Proposed on feature branch `codex/s1-execution-time-governance-recheck-20260705`.
  Not merged, not pushed, not released.
- Cross-repo authorization: workspace RR-0048 phase-gate Option 2, slice **S1** (founder-authorized
  2026-07-05, real-execution preparation). This ADR records the OS-side decision only; the sibling repo
  `autonomous-agent-core` is NOT imported (Hard Boundary #19).
- Supersedes/extends: **ADR-0004** explicitly named this follow-up — *"this seam is consulted at initial
  proposal time. Approval-resume execution does not re-consult the seam in this slice; add a follow-up
  ADR/gate if a live use-case requires execution-time governance recheck."* Real execution (S2) is that use-case.

## Context

The governed-decision seam (ADR-0004) and the operator corrigibility pause (ADR-0001, `BlockCode.PAUSED`) are
both enforced at **proposal time** inside `TrustedLoopRuntime.run()`. But an approval-required action is
executed **later**, via `execute_approved_operation()` (approval-resume). Approval can take arbitrarily long.
Between proposal/approval and execution, two governance-relevant states can change:

1. The operator may **PAUSE** the system (C7). Today `execute_approved_operation()` does **not** re-read
   `shell_view.paused` before touching a connector — the runtime-level pause guard exists only in `run()`.
   (An app-adapter pause guard exists for the HTTP approval-execute route, but OS Core must not depend on the
   caller to enforce corrigibility.)
2. The external governed-decision seam may flip to **DENY** (e.g. the disposer learned the action is unsafe).
   Today the seam is not re-consulted at execution time (the ADR-0004 gap).

For a **real** (non-dry-run) governed action, a stale governance state is a safety defect: the system could
execute an action after it was paused, or after the disposer denied it.

## Decision

Add a runtime-level **execution-time governance recheck** in `execute_approved_operation()`, run **after** the
existing approval/fingerprint/grounding validation and **before** any connector interaction
(`_execute_governed_operation` → dry-run/snapshot/`connector.execute`). The recheck catches **state changes
since approval**, fail-closed, without re-litigating the already-granted human approval:

- **Corrigibility (C7) is absolute.** If `shell_view.paused` → raise `TrustedLoopBlocked(BlockCode.PAUSED,
  stage="corrigibility_pause_execution")` before the connector. Recorded in the tamper-evident audit via
  `shell_view.observe`. The runtime holds only a read-only `ShellView`; it cannot un-pause itself.
- **Seam re-consulted.** If a `governance_decision_client` is present, re-consult it at execution time
  (`approved=True`, since the OS Approval lifecycle has approved). Semantics — **only a fresh DENY blocks**:
  - `DENY` → raise `TrustedLoopBlocked(BlockCode.GOVERNANCE_DENIED, stage="governed_decision_execution")`.
  - `ALLOW` / `ESCALATE` / `VERIFY_MORE` → **proceed** (ESCALATE/VERIFY_MORE are redundant post-approval; the
    human already approved — the recheck is not a second approval gate).
  - client unavailable / invalid verdict → **proceed** (ADR-0047 "never block on the organ"; the human
    approval stands), recorded as a withheld/degraded governed-decision event.

Remote reasons are never surfaced (reuse `_GOVERNANCE_DECISION_REASON_WITHHELD`).

## Scope / non-goals

- **No contract change.** Reuses `BlockCode.PAUSED` and `BlockCode.GOVERNANCE_DENIED`; reuses the existing
  `GovernanceDecisionRequest`/`GovernanceDecisionResponse` v1.1.0.
- **No behavior change when nothing changed:** with no seam client and not paused, `execute_approved_operation`
  behaves exactly as before (an added no-op gate). All existing approval-execute tests stay green.
- R4/R5 remain proposal-only (`execute_approved_operation` already rejects them). The seam can still only
  tighten; the recheck can only *block*, never authorize.
- Does not touch SQL Safety, EvidenceChain grounding (already asserted before the recheck), Provider routing,
  or external projection.

## Consequences

- Positive: closes the ADR-0004 execution-time gap and adds runtime-level (not caller-dependent) corrigibility
  defense-in-depth. A paused system, or a disposer that denies after approval, cannot cause a real connector
  side-effect. This is the safety prerequisite for S2 (first real reversible R0-R3 action).
- Cost: one extra seam round-trip at execution time (bounded by the transport's hard wall-clock timeout, and
  degrades safe on failure).

## Tests (added with this ADR; would fail if the recheck were bypassed)

- paused after approval → `execute_approved_operation` raises `PAUSED` and the connector store stays empty.
- seam returns `DENY` at execution time → raises `GOVERNANCE_DENIED`, connector not called.
- seam returns `ALLOW` at execution time → executes normally (connector called once).
- seam `ESCALATE`/`VERIFY_MORE` at execution time → executes (post-approval redundant, not a re-gate).
- seam client raises at execution time → executes (never block on the organ), degraded event recorded.
- no seam client + not paused → unchanged baseline execution.
