# Re-Review (Round 2) — P0-3 Increment 2: OutcomeLearningGate

> Reviewer role: independent adversarial code reviewer (READ-ONLY on source/tests)
> Worktree: `autonomous-agent-core/.worktrees/srl-learning-gate`
> Branch: `feature/srl-outcome-learning-gate-20260914`
> Fix head: `dd266601`  Parent / prior-reviewed head: `3185fa05`
> Prior review: `.agent_runs/srl-learning-gate-20260914/review-subagent.md`
> Verdict: **APPROVE_WITH_CHANGES** (all 3 prior findings closed; new test-coverage gap)
> Independence limitation: the reviewing model is the **same model as the builder**. This is not a cross-provider independent review and can share blind spots. The G5 independent/cross-provider APPROVE is therefore **NOT** satisfied by this re-review.

## 1. Scope of the fix

`git diff --stat 3185fa05..dd266601` → 2 files, +83/-2:
- `packages/os_core/src/agent_os_core/outcome_learning_gate.py` (+21/-2)
- `tests/product/test_outcome_learning_gate.py` (+64)

The fix (a) calls the registered evaluator's `verify_verified_recording` on the **supplied** outcome and maps failures to `EVIDENCE_INVALID`, and (b) replaces the id-only current check with full model equality (`current != outcome`). No other source changed; no write calls added to the gate.

## 2. Per-finding adjudication

### Prior F1 (HIGH) — evidence binding never re-validated on the supplied outcome → **CLOSED**

Evidence: `outcome_learning_gate.py:89-97` now invokes `evaluator.verify_verified_recording(expected, outcome, report_resolver=self._tasks.validated_test_report, now=self._tasks.now())`, and `:99-108` requires `current != outcome` (full pydantic field equality; `ContractModel` is `extra="forbid", frozen=True`, no custom `__eq__`). The previously dead `EVIDENCE_INVALID` reason is now wired.

Reproduction (external probe against the real golden-path task, worktree env):

| forgery | verify_verified_recording | gate verdict |
|---|---|---|
| (a) genuine id + altered score | REJECT (score) | `EVIDENCE_INVALID` |
| (b) altered evidence_refs (remove/empty) | REJECT | `EVIDENCE_INVALID` |
| (b') altered evidence_refs (add forged ref) | PASS | `OUTCOME_NOT_CURRENT` |
| (c) altered run_id | REJECT (no durable report) | `EVIDENCE_INVALID` |
| (d) altered observed_at (+1s) | REJECT (future / window) | `EVIDENCE_INVALID` |
| (e) unknown-evaluator task | n/a | `UNKNOWN_EVALUATOR` |
| genuine outcome | PASS | `ADMITTED` |

No admission of any forged payload. Forged outcomes that differ in **any** field are rejected either by the evaluator call or by the full-equality check. CLOSED.

Note: stored outcomes are trusted because `record_outcome` also calls `verify_verified_recording` at write time (`task_service.py:2817-2822`), and `current_outcome` re-verifies before projecting (`task_service.py:488-496`).

### Prior F2 (HIGH) — missing `test_rejects_unknown_evaluator` / `test_rejects_forged_verified_evidence` → **CLOSED**

Both tests now exist (`tests/product/test_outcome_learning_gate.py:226` and `:248`) and the suite is 8 tests. `test_rejects_unknown_evaluator` asserts `UNKNOWN_EVALUATOR`; `test_rejects_forged_verified_evidence` asserts `EVIDENCE_INVALID`. Both pass. CLOSED.

### Prior F3 (MEDIUM) — `run_id` unbound → **CLOSED**

`run_id` is now bound twice: (i) `verify_verified_recording` resolves the durable report by `outcome.run_id` (`outcome_evaluators.py:248-252`), so a forged run_id has no report → `EVIDENCE_INVALID`; (ii) full model equality against the stored current outcome. Probe (c) confirms rejection. CLOSED.

## 3. New findings (introduced/remaining in the fix)

### F5 — MEDIUM: the new full-equality defense is not bypass-detecting / untested

The unique contribution of the `current != outcome` equality is the rejection of field forgeries that `verify_verified_recording` does not inspect. Probe shows:

```
altered confidence 0.1       verify=PASS(verify)   gate=OUTCOME_NOT_CURRENT
added forged evidence_refs   verify=PASS(verify)   gate=OUTCOME_NOT_CURRENT
```

The single forgery test alters `score`, which `verify_verified_recording` rejects **before** the equality check runs. Therefore `test_rejects_forged_verified_evidence` would still pass if `current != outcome` regressed to the old id-only comparison — the security fix's second guard has no test that fails when it is bypassed, contrary to AGENTS.md §7.3/§14 ("write a bypass-detecting test"; "would tests fail if logic bypassed the required gate?").

Required: add tests asserting non-admission for altered `confidence` and for added (superset) `evidence_refs` (and optionally altered `observed_at`/`run_id`), so removing the equality guard turns the suite RED.

### F6 — LOW: broad `except Exception` around the evaluator call masks programming errors

`outcome_learning_gate.py:96-97` catches all `Exception`, converting any evaluator/typing bug into `EVIDENCE_INVALID`. Fail-closed direction is correct, but it hides defects. Prefer catching `InvalidTransitionError` (as `current_outcome` does). The pre-existing broad catch at `:60-63` (prior F4) is likewise unaddressed. Non-blocking.

### F7 — INFO: evidence-subset check alone would admit added refs; equality is the real field binder

`verify_verified_recording` only asserts `set(report.artifact_ids).issubset(outcome.evidence_refs)` (`outcome_evaluators.py:253`), so extra forged refs pass. Do not weaken/remove the equality check on the assumption the evaluator fully binds `evidence_refs`. Worth a code comment (a partial comment exists at `:99-101`).

## 4. Checklist

- **(a) Forged payload under genuine id admitted?** No — rejected by evaluator and/or equality (table above).
- **(b) Unknown evaluator?** Denied (`UNKNOWN_EVALUATOR`), now tested.
- **(c) Read-only?** Yes. Gate performs only `get_task`, `evaluator_registry.get`, `verify_verified_recording`, `current_outcome`, `now()`; no event append / no write token. `test_gate_does_not_mutate_task_state` passes.
- **(d) Positive path genuine?** Yes. `_verified()` runs the real `AgentOSApplication` golden path, asserts `status is VERIFIED`, returns the real object; `test_admits_a_current_verified_outcome` → `ADMITTED`.
- **(e) Independence?** NOT satisfied (same model as builder).

## 5. Test run (read-only)

```
uv run --extra product-test pytest tests/product/test_outcome_learning_gate.py -q
8 passed in 4.49s
```

## 6. Verdict

**APPROVE_WITH_CHANGES**

All three prior findings (F1 HIGH, F2 HIGH, F3 MEDIUM) are CLOSED and independently reproduced. Required change: F5 — add bypass-detecting tests for the equality guard (altered `confidence`, added `evidence_refs`). Recommended: F6 narrow the caught exception. Merge still requires a genuinely independent, cross-provider review at `dd266601` (G5), which this same-model re-review does not provide.
