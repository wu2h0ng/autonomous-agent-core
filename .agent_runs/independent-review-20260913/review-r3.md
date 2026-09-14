# Independent Adversarial Re-Review — SRL TaskActivationGate (round 3)

> Reviewer model: `deepseek/deepseek-v4-pro` (builder was `opencode/deepseek-v4-flash`)
> Prior reviews: `review-subagent.md` (H1–H5, APPROVE_WITH_CHANGES) and `review-r2.md` (F1–F5, APPROVE)
> Fix under review: `ce21e318` (parent `ef95ff82`; diff `ef95ff82..ce21e318`)
> Read-only: no source/test edits, no worktrees, no /tmp. Only `review-r3.md` written.

## Verification (reviewer-run)

- `pytest tests/product/test_srl_task_activation_gate.py tests/product/test_srl_runtime_invariants.py` — **60 passed** (`-p no:cacheprovider`).
- `ruff check --no-cache` on the four touched files — clean.
- `pyright` on `srl_activation_gate.py` + `srl_runtime.py` — **0 errors / 0 warnings**.
- `git show ce21e318 --stat` — exactly 4 files, 125 insertions / 15 deletions; source delta confined to `srl_activation_gate.py` (+32/−…) and `srl_runtime.py` (+18/−…), plus 2 test files. No contract/port drift.

## Verdict per prior finding

### H1 — MEDIUM — I-23 fail-open when `assessor-instance:` absent/forged → **PARTIALLY_CLOSED (new fail-open variant)**

**Closed half.** The `None` case (constraint entirely absent) now fails closed in both entry points:
- `srl_activation_gate.py:177-181` — `producer_instance_id is None` → `PRODUCER_IDENTITY_UNAVAILABLE`.
- `srl_runtime.py:318-328` — same, returns `activated=False`, `"I-23: producer identity unavailable"`.
Reproduced: the M0 no-producer test now asserts `"producer identity unavailable"` (test updated `test_srl_runtime_invariants.py:480-481`), and `test_gate_rejects_stripped_producer_identity` passes.

**Remaining open half — empty/whitespace producer value still fails open.**
The fail-closed predicate tests `is None`, but `_goal_constraint` returns `constraint[len(prefix):]`, which is the *empty string* `""` for a constraint of the form `assessor-instance:` (or `assessor-instance:   `, which `NonEmptyStr.strip_whitespace=True` normalizes to the same empty value). `"" is not None`, and `authority.authority_instance_id == ""` is `False`, so the I-23 check is silently skipped.

Reproduced (reviewer-run, inline):
```
gate.activate(goal with constraints=("mandate-ref:mandate-1",
                                      "assessment-ref:assessment:event-1",
                                      "assessor-instance:"), trusted authority)
    -> activated=True, reason=None          # FAIL-OPEN
runtime.activate_goal(same empty-producer goal, trusted authority)
    -> activated=True, reason=None          # FAIL-OPEN
```
The equivalent `mandate-ref:` / `assessment-ref:` empty values do **not** fail open (they use `authority.X != goal_ref`, and the authority field is non-empty, so `""` mismatches and is rejected). Only the producer check uses equality, so only it is bypassed.

Impact: bounded to the same class as the original H1 (a durable Task is created via `TaskServiceCreationAdapter`; no run/grant/effect), and still requires a registry-resolved authority. Severity LOW→MEDIUM, but it defeats the fix's stated intent ("producer identity is required; its absence fails closed"). Root cause is the wrong predicate (`is None` instead of a falsy/`strip()` check) in two places.

### H2 — MEDIUM — authority.mandate_id never bound to goal `mandate-ref:` → **CLOSED**

`srl_activation_gate.py:163-165` now requires `authority.mandate_id == goal_mandate_ref` (missing → `AUTHORITY_BINDING_MISMATCH`). `test_gate_rejects_cross_mandate_authority` passes. Reproduced: cross-mandate authority (`mandate_id="mandate-2"` vs goal `mandate-ref:mandate-1`) → `activated=False` (either `AUTHORITY_NOT_RECOGNIZED` or `AUTHORITY_BINDING_MISMATCH` depending on registry registration; both fail closed).

### H3 — LOW — `source_assessment_id` unverified → **PARTIALLY_CLOSED (latent)**

`srl_activation_gate.py:166-173` now binds `authority.source_assessment_id == goal_assessment_ref` (from `assessment-ref:`), closing the string-consistency half. `test_gate_rejects_assessment_ref_mismatch` passes; reproduced mismatch → `activated=False`.

The residual is unchanged and inherent to the stated boundary: the `assessment-ref:` value is never resolved against a trusted assessment registry, so a registered authority whose `source_assessment_id` points at a non-existent assessment still admits a Task. No assessment registry is in scope, so this remains a latent LOW — same status the prior two reviews recorded.

### H4 — LOW — C7 clearance identity only epoch-checked → **UNCHANGED (latent, not part of this fix)**

`srl_activation_gate.py:215-216` still compares only `clearance.correction_epoch == mandate.correction_epoch`; a garbage `clearance_digest` at the correct epoch passes. Consistent with the brief's "C7 semantics not implemented" boundary; not a required change and no new admission path introduced.

### H5 — INFO — missing branch tests / unused members → **PARTIALLY_CLOSED**

Added 7 tests (stripped producer, cross-mandate, assessment-ref mismatch, mismatched registered authority, tenant scope mismatch, mission mismatch, unavailable mandate) — all pass. Remaining:
- The **empty/whitespace producer value** edge is untested and is the live gap (see H1).
- `ActivationDenialReason.TRUSTED_AUTHORITY_MISSING` and `CreatedTask.run_id` remain unused (non-blocking).

## New bypass attempts

| Bypass | Result |
|---|---|
| Cross-mandate authority (`mandate_id` differs from `mandate-ref:`) | **rejected** (fail-closed) |
| Mismatched mandate-ref / assessment-ref vs authority | **rejected** (fail-closed) |
| Stripped producer — constraint absent (`None`) | **rejected** (`PRODUCER_IDENTITY_UNAVAILABLE`) |
| **Empty producer — `assessor-instance:` empty/whitespace value** | **ADMITTED — `activated=True`** (new finding, see H1) |
| Cross-tenant goal (`tenant_id="t-2"` vs mandate) | **rejected** (`AUTHORITY_BINDING_MISMATCH`) |
| Registry digest mismatch (registered record ≠ caller-supplied) | **rejected** (`AUTHORITY_NOT_RECOGNIZED`) |
| Unavailable mandate (empty registry) | **rejected** (`MANDATE_UNAVAILABLE`) |

## Idempotency confirmation

Identical re-activation through `TaskServiceCreationAdapter` stays idempotent:
```
first  = gate.activate(goal, authority)  -> activated=True, task_id=task:srl:goal-1
second = gate.activate(goal, authority)  -> activated=True, task_id=task:srl:goal-1
first.task_id == second.task_id           -> True
```
The idempotency key is deterministic from the proposal (`event_id` and `occurred_at=proposed_goal.created_at` are proposal-derived), and the durable Goal's `c7-clearance-digest` participates in `ensure_task`'s exact-replay comparison, so a same-id/different-content or different-clearance re-activation fails closed as `TASK_IDENTITY_CONFLICT` (verified by the F1 regression test). No idempotency regression.

## Required change (small, blocking for the H1 invariant)

1. In both `srl_activation_gate.py` (`decide`) and `srl_runtime.py` (`activate_goal`), fail closed when the producer identity is empty/whitespace after extraction — e.g. test `if not producer_instance_id` (or strip and compare to `""`) rather than `is None`.
2. Add a regression test for the empty-value `assessor-instance:` constraint (gate + runtime), asserting `PRODUCER_IDENTITY_UNAVAILABLE` / non-activation.

## Approval status

**APPROVE_WITH_CHANGES**

H2 and the H1 `None`-case are genuinely closed with passing regression tests; H3 is string-bound (residual is the pre-existing latent assessment-registry gap, not a new exploit); the spine, C7 boundary, and idempotency are sound; ruff/pyright clean and 60 targeted tests pass. The single blocker is the empty/whitespace producer value, which re-opens the H1 fail-open through a trivially-forgeable value and is a one-line predicate fix in two places plus a test. No push/merge performed.
