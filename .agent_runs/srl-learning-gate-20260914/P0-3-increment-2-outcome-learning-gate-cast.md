# P0-3 Increment 2 — OutcomeLearningGate (CTO gate issued 2026-09-14)

> Status: `CTO_GATE_ISSUED / INCREMENT_2`
> Track: product  primary_class: P  secondary_class: A/E
> Base: origin/main `cd3e816a`; branch `feature/srl-outcome-learning-gate-20260914` (worktree `.worktrees/srl-learning-gate`)

## 1. Gap

`grep -rn OutcomeLearningGate packages tests` → nothing. There is no gate that decides whether a terminal outcome may update cross-task state (W1/W2) or seed knowledge candidates. Increment 1 produced a durable, executed Task; without this gate any outcome could be learned from — including self-reported or stale ones — contradicting the blueprint's "only verified, scoped, evidence-bound outcomes may affect confidence".

## 2. Scope (Increment 2, narrow)

A **fail-closed admission gate**, not a learner. `OutcomeLearningGate.admit(task_id, outcome) -> OutcomeAdmissionDecision` with an enumerable `OutcomeAdmissionReason`. It performs NO belief/knowledge mutation; it only decides admissibility and returns a typed receipt. Actual W1/W2 consumers are deferred to a later, separately gated slice.

Checks (all fail-closed):
1. the task exists and has an `ExpectedOutcome`;
2. the outcome binds that exact expected outcome (id) and scope (tenant/workspace/evaluator type+version);
3. status is `VERIFIED` (UNRESOLVED / INVALID / NOT_MET are never admitted);
4. the evaluator is registered (unknown evaluator denied);
5. the evaluator's `verify_verified_recording` re-validates the evidence (a forged/unbound VERIFIED is denied);
6. the supplied outcome is the task's CURRENT trusted outcome (`TaskService.current_outcome`);
7. (optional) C7 is not halted for the scope.

## 3. RED tests

```
tests/product/test_outcome_learning_gate.py
  test_admits_a_current_verified_outcome
  test_rejects_unverified_outcome
  test_rejects_outcome_for_missing_expected_outcome
  test_rejects_scope_mismatch
  test_rejects_unknown_evaluator
  test_rejects_non_current_outcome
  test_rejects_forged_verified_evidence   # evidence-binding via the evaluator
  test_gate_does_not_mutate_task_state    # boundary: admission is read-only
```

## 4. Gates

| Gate | Exit condition |
|---|---|
| G1 RED | the 8 tests exist and fail pre-implementation |
| G2 fail-closed | every denial returns a typed reason; no state mutation |
| G3 no-learning-claim | the gate does not update beliefs/knowledge; it returns a receipt only |
| G4 tests green | targeted pass; Ruff/Pyright clean; full tests/product zero new failures |
| G5 independent review | cross-provider APPROVE at the exact head |

## 5. Boundaries

- No W1/W2 belief mutation, no knowledge candidate creation, no promotion.
- No effect execution, no release/tag/deploy, no autonomy/HCW claim.
