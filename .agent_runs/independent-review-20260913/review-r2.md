# Independent Re-Review — SRL TaskActivationGate (round 2)

> Reviewer model: `deepseek/deepseek-v4-pro` (distinct from builder `opencode/deepseek-v4-flash`)
> Prior review: `.agent_runs/independent-review-20260913/review.md` (F1–F5, APPROVE_WITH_CHANGES)
> Fix under review: `ef95ff82` (base `0045aeea`; diff `5923fa32..ef95ff82`)
> Commands run: targeted pytest (`53 passed`), ruff (clean), pyright (`0 errors`), full product suite (`22 failed, 2212 passed, 1 skipped` — same 22 pre-existing failures as prior review)

## Verdict per prior finding

### F1 — CLOSED — Fail-closed activation restored for conflicting re-activation
`srl_activation_gate.py:205-212`

`decide` now wraps `self._task_creation.create_task(...)` in `try/except`, mapping `InvalidTransitionError` → `TASK_IDENTITY_CONFLICT` (new enum member, `:40`) and `ConcurrentWriteError` → `TASK_CREATION_REFUSED`, returning a typed `TaskActivationDecision` instead of propagating to the caller. `TaskServiceCreationAdapter` also keys `occurred_at=proposed_goal.created_at` (`:286`) instead of `authority.authorized_at`, making the idempotency key deterministic from the proposal. The new test `test_conflicting_authority_reactivation_fails_closed` (`tests/product/test_srl_task_activation_gate.py:476-502`) asserts `activated=False` and `TASK_IDENTITY_CONFLICT` for a competing authority on the same goal, and passes. This is exactly the required change; the adapter docstring was also corrected (`:246-251`) to stop over-claiming idempotency.

### F2 — CLOSED — Dead empty-string checks removed
`srl_activation_gate.py:158`

The `authority.mandate_id == ""` / `authority.standing_mission_id == ""` clauses are gone; the binding check is now the single reachable condition `source_proposed_goal_id != proposed_goal.proposal_goal_id`.

### F3 — PARTIALLY_CLOSED — `standing_mission_id` bound; `source_assessment_id` still unbound
`srl_activation_gate.py:181-188`

The gate now calls `MandateRegistryPort.current_ratified_mission(authority.mandate_id)` (with `SituationalTrustDenied` → `MANDATE_UNAVAILABLE`) and rejects `AUTHORITY_BINDING_MISMATCH` when `authority.standing_mission_id != mission.standing_mission_id`. The first, more material half of F3 is closed.

The second half — `authority.source_assessment_id` is never bound to a real assessment — remains unaddressed. This stays latent (the adapter does not materialize `source_assessment_id` into the `Goal`), so it is not currently exploitable to reach `TaskService`, exactly as the prior review stated. No new exploit is introduced; it is still a gap for whenever those fields are used downstream.

### F4 — CLOSED — C7 clearance digest recorded for traceability
`srl_activation_gate.py:278`

The adapter now appends `c7-clearance-digest:{clearance.clearance_digest}` to the durable Task's `Goal.constraints`, so the resulting Task carries a traceable clearance identity (the prior review's core concern). Consistent with the brief's "C7 semantics not implemented" boundary, the digest is *recorded* but still not *verified* against a C7 lineage — only the epoch is compared (`:199`). A garbage digest at the correct epoch still passes. This residual is inherent to the stated boundary and was not a required change.

### F5 — OPEN (INFO, non-blocking) — unused members unchanged
- `ActivationDenialReason.TRUSTED_AUTHORITY_MISSING` (`:30`) is still never emitted.
- `CreatedTask.run_id` (`:63`) is still declared but never populated.

Neither was a required change and both remain non-blocking informational findings.

## New-defect search on the fix

No new defect found. Specific checks:

1. **F3 second registry lookup** — `InMemoryMandateRegistry.current_ratified_mission` raises only `SituationalTrustDenied` on every failure path (`srl_mandate_registry.py:61-78`), which the gate catches (`:185-186`). No uncaught exception path introduced. The `MandateRegistryPort` protocol already declares `current_ratified_mission` (`srl_ports.py:146`), so no type/interface drift.
2. **F1 exception coverage** — `ensure_task` raises exactly `InvalidTransitionError` and `ConcurrentWriteError` (plus the internal swallowed `ConcurrentWriteError`); both are mapped to typed denials. No other spine exception reaches the caller in the fail-closed paths.
3. **`occurred_at` change** — deterministic from the proposal; a same-id/different-content proposal now yields `TASK_IDENTITY_CONFLICT` (fail-closed), and an identical re-activation remains idempotent (verified by `test_task_service_adapter_creates_durable_idempotent_task`).
4. **Constraint additions** — `c7-epoch`/`c7-clearance-digest`/`authority`/`capability-scope` are all `NonEmptyStr`/str-formatted; no collision with the `assessor-instance:` prefix parsed by `_producer_instance_id` (`:236-240`).
5. **Regression** — full suite still `22 failed` (same pre-existing time-sensitive/config tests; none import the srl modules), `2212 passed` (+1 from the new F1 test). The 39 runtime invariants pass.

Minor observations (not defects): the gate's `_clock` and the registry's `clock` are independent sources — in production a drifted clock could flip a `mandate_is_active`/`current_ratified_mission` boundary differently; and the F4 digest recording makes re-activation with a same-epoch-but-different-digest clearance fail-closed (a deliberate, correct tightening).

## Required focus (round-2 confirmation)

1. **Authority bypass → TaskService**: still none. The added `current_ratified_mission` check only *tightens* the spine; `source_assessment_id` remains unmaterialized, so no new admission path.
2. **I-23**: unchanged, enforced in both `SrlRuntime.activate_goal` and the gate.
3. **Idempotency**: now deterministic per proposal; conflict path fails closed (F1 closed).
4. **Regression**: 39/39 invariants pass; full-suite failure count unchanged.
5. **Bypass-detecting tests**: +1 conflicting-authority test; the missing scope/`content_digest`/`MANDATE_UNAVAILABLE` branch tests from the prior review's item 4 remain a recommended (non-blocking) follow-up.
6. **Scope creep**: none — 47-line source delta confined to the one module plus one test.

## Approval status

**APPROVE**

F1 (the only blocking finding) is closed with a targeted regression test, F2 and F4 are closed, and F3's remaining `source_assessment_id` gap is a pre-existing latent LOW that was not required and introduces no new exploit. Targeted 53 pass, ruff/pyright clean, and the full suite shows no new failures. Recommended non-blocking follow-ups: (a) bind `source_assessment_id` to a real assessment when it is first materialized downstream, and (b) add the scope-mismatch / `content_digest`-mismatch / `MANDATE_UNAVAILABLE` branch tests.
