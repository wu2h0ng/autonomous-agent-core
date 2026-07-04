# ADR-0006: Local-disposer-governed first real reversible R0-R3 action (S2)

- Status: Proposed on feature branch `codex/s2-local-disposer-real-governed-action-20260705`.
  Not merged, not pushed, not released.
- Cross-repo authorization: workspace RR-0048 phase-gate Option 2, slice **S2** (founder-authorized
  2026-07-05), with the founder's explicit risk-acceptance for *"首个真实(可逆、R0-R3、控制试点)动作"* — the
  first real action, bounded to reversible, R0-R3, controlled-pilot. Sequenced after **S1** (ADR-0005),
  which is the safety prerequisite (execution-time corrigibility + seam recheck) this slice relies on.
- Builds on: **ADR-0004** (governed-decision seam, tighten-only) and **ADR-0005** (execution-time recheck).
  The sibling repo `autonomous-agent-core` is NOT imported (Hard Boundary #19); the seam is a shared
  versioned contract implemented independently on both sides.

## Context

The governed spine is already built: the tighten-only seam (ADR-0004), the reversible `action_record`
connector with snapshot/rollback, the operator corrigibility pause (C7), and the execution-time recheck
(ADR-0005). What was missing was a **real, native governed decision** driving a **real reversible action
end-to-end** on `main` — the first step of RR-0048 Option 2 (real-world execution).

The real cohort A/B verifier that gives the disposer its decision strength — `MetricCohortABVerifier`
(standardized mean difference over a cohort A/B query, fail-closed on malformed/thin/error data) — had
been implemented and reviewed on the stranded `feat/m4-seam-endtoend-2026-07-03` branch (commit `898261e`,
"Claude-reviewed") but was **never landed on `main`**. That branch also bundles the live cross-process
seam service (S3 scope) and feedback compounding (S4 scope); merging it wholesale would collapse S2+S3+S4
into one step, against the founder's *"S1再S2，按顺序到S4"* (in-sequence) directive.

## Decision

Land **only the S2 piece** on `main`, in sequence:

1. **Port the real verifier.** Bring `MetricCohortABVerifier` (and its 6 tests-first unit tests) from the
   reviewed M4 commit into the OS-Core seam module verbatim. It is a `CohortABVerifier` subclass — **no
   contract change**, no dependency on the S3 seam service. This un-strands the decision-strength component.
2. **Wire the native disposer to a real reversible action.** An integration test wires
   `LocalGovernanceDecisionClient(MetricCohortABVerifier(...), approval_required_at_or_above="R4")` into a
   `TrustedLoopRuntime` with the `action_record` connector and proves the founder's risk-acceptance bounds:
   - **verified cohort effect → real write:** disposer ALLOW → OS approval → ADR-0005 execution-time recheck
     (disposer re-consulted, still ALLOW) → `connector.execute` → a real ledger record.
   - **reversible:** `runtime.rollback(snapshot_id)` restores the ledger to empty (可逆).
   - **controlled by C7:** an operator pause after approval halts the action before any connector
     side-effect (0 records); the runtime cannot un-pause itself (控制试点).
   - **decision strength:** with no verified cohort effect the disposer ESCALATEs (never auto-clears an
     unverified causal effect); the same action with a verified effect clears to ALLOW.

## Scope / non-goals

- **Local disposer only.** The native `LocalGovernanceDecisionClient` runs in-process (deterministic, no
  LLM in the control path). The **live cross-process seam service** (`RemoteGovernanceDecisionClient` over a
  subprocess) is **S3**, not this slice.
- **No feedback/outcome learning.** The outcome→KnowledgeAsset compounding loop is **S4**.
- **No contract change.** Reuses the seam contract v1.1.0, `BlockCode.PAUSED`/`GOVERNANCE_DENIED`, and the
  existing snapshot/rollback path. R4/R5 remain proposal-only; the seam can only tighten.
- **Honest capability bound.** The claim proven here is the causal loop's **structure/decision strength**
  (RR-0046 §22): the disposer discriminates a verified interventional effect from an unverified one. It is
  **not** the value-prediction-under-shift claim that RR-0046 §28-29 falsified.

## Consequences

- Positive: the first real reversible R0-R3 action executes end-to-end under a native governed decision,
  fully reversible and fully corrigible, on the release target `main`. The stranded decision-strength
  component is un-stranded. S3 (live service) and S4 (outcome learning) remain clean, separate slices.
- Cost: the real cohort A/B verifier now lives on `main` and is covered by CI; the M4 branch's copy becomes
  redundant (to be reconciled when S3 lands the seam service).

## Tests (added with this ADR; would fail if the governed real-action path were bypassed)

- `tests/unit/test_cohort_ab_verifier.py` — the real verifier: strong effect → effective+confident;
  null effect → not effective; thin/malformed/query-error → fail-closed; deterministic (6 tests).
- `tests/integration/test_s2_governed_real_action_local_disposer.py` — verified effect executes end-to-end
  (real ledger write, disposer ALLOW at execution); reversible via rollback; C7 pause halts the real action
  (0 records); unverified effect ESCALATEs and never auto-clears; decision strength discriminates the two.
