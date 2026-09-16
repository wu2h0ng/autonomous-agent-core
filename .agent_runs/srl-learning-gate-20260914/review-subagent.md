# Independent Adversarial Review — P0-3 Increment 2: OutcomeLearningGate

> Reviewer role: independent adversarial code reviewer (READ-ONLY on source/tests)
> Worktree: `autonomous-agent-core/.worktrees/srl-learning-gate`
> Branch: `feature/srl-outcome-learning-gate-20260914`
> Code head: `3185fa05`  Base: `origin/main cd3e816a`
> Cast: `.agent_runs/srl-learning-gate-20260914/P0-3-increment-2-outcome-learning-gate-cast.md`
> Verdict: **APPROVE_WITH_CHANGES** (security-critical evidence-binding bypass)
> Independence limitation: the reviewing model is the **same model as the builder**; this is not a cross-provider independent review and can share blind spots. G5 (cross-provider APPROVE) is therefore **NOT** satisfied by this review.

## 1. What was reviewed

Diff `cd3e816a..3185fa05` (362 insertions):
- `packages/os_core/src/agent_os_core/outcome_learning_gate.py` (new, 98 lines)
- `packages/os_core/src/agent_os_core/__init__.py` (exports)
- `tests/product/test_outcome_learning_gate.py` (new, 205 lines, 6 test funcs)
- cast file

Supporting reads: `task_service.py` (`get_task`, `commit_task`, `current_outcome`, `record_outcome`, `evaluator_registry`), `outcome_evaluators.py` (`verify_verified_recording`), `contracts/outcome.py`.

## 2. Test run (read-only)

```
uv run --extra product-test pytest tests/product/test_outcome_learning_gate.py -q
6 passed in 8.25s
```

Cast §3 / G1 promised **8** tests; the delivered file contains **6** top-level test functions
(`grep -n '^def test_'`): `test_rejects_unknown_evaluator` and
`test_rejects_forged_verified_evidence` are **missing**.

## 3. Adversarial findings

### F1 — HIGH / security-critical: evidence binding is not re-validated on the supplied outcome (check 5 not implemented)

The cast requires: "the evaluator's `verify_verified_recording` re-validates the evidence (a forged/unbound VERIFIED is denied)." The implementation **never calls `verify_verified_recording`** (`grep verify_verified_recording outcome_learning_gate.py` → none). Instead, check 6 delegates to `TaskService.current_outcome()`, which re-validates the **stored aggregate outcome**, not the `outcome` object passed by the caller:

- `outcome_learning_gate.py:79-91` validates `status`, evaluator registration, and then compares **only `observed_outcome_id`** to `current_outcome`.
- `task_service.py:471-514` re-verifies the *stored* outcome and returns it; the supplied object's `score`, `evidence_refs`, `run_id`, `observed_at`, `confidence` are never checked.

Result: any `ObservedOutcome` that reuses the genuine, currently-verified `observed_outcome_id` is ADMITTED even with a completely fabricated payload. This is reachable through the **public constructor** (the `_require_verified_evidence` validator only requires `score is not None` and non-empty `evidence_refs`, both attacker-controlled).

Reproduced (probe, genuine golden-path task):

```
genuine status/id: VERIFIED observed-d18a14f4-... score 1.0 ev ('artifact:1616...',)
A forged-payload (same id, bogus score=999/evidence=()):  ADMITTED
B forged-run_id  (same id):                               ADMITTED
C forged-observed_at future (same id):                    ADMITTED
D fabricated payload same id (public constructor, score=2.0, evidence=("artifact:evil",)): ADMITTED
E fabricated id (not stored):                             OUTCOME_NOT_CURRENT  (correct)
F genuine:                                                ADMITTED  (correct)
```

`OutcomeAdmissionReason.EVIDENCE_INVALID` (`outcome_learning_gate.py:21`) is **dead** — never produced anywhere. This is corroborating evidence that the intended evidence re-validation was designed but not wired.

Impact: the gate is the fail-closed boundary for "only verified, scoped, evidence-bound outcomes may affect confidence." A downstream W1/W2 consumer that uses the admitted `outcome` (the natural reading of `admit(task_id, outcome)`) receives an attacker-shaped VERIFIED outcome with an authentic id. `DEPLOY`/learn-from-this path is poisoned even though the stored task truth is clean.

Required change (choose one, prefer the first):
1. After the scope checks, call the registered evaluator on the **supplied** object:
   `evaluator.verify_verified_recording(expected, outcome, report_resolver=<same resolver as TaskService>, now=self._tasks._clock())`, and map `InvalidTransitionError` → `EVIDENCE_INVALID`. (Note: `report_resolver` is private; expose a read accessor on `TaskService` rather than reaching into privates.)
2. Or require exact identity equality with the projected current outcome: `current == outcome` (compare full model, not just id), which pins every field to the re-validated stored outcome.
3. Add the missing `test_rejects_forged_verified_evidence` test that constructs a forged VERIFIED outcome reusing the genuine id and asserts `EVIDENCE_INVALID`.

### F2 — HIGH: required RED tests missing; G1/G4 and the security path are unverified

Cast §3 lists `test_rejects_unknown_evaluator` and `test_rejects_forged_verified_evidence`; neither exists (`tests/product/test_outcome_learning_gate.py`, only 6 `^def test_`). The security-critical denial path (F1) is therefore entirely untested, and the `UNKNOWN_EVALUATOR` branch (`outcome_learning_gate.py:82-83`) has no coverage. G1 ("the 8 tests exist and fail pre-implementation") is not met, and G4's "targeted pass" passes only because the hard cases were not written. Add both tests.

### F3 — MEDIUM: `run_id` is not part of the scope/binding check

The scope tuple at `outcome_learning_gate.py:69-76` (and the `current` check at `:85-91`) omits `run_id`. `ExpectedOutcome` has no `run_id`, but `aggregate.run.run_id` is available via `get_task`. A supplied outcome with the genuine id but a forged `run_id` is ADMITTED (probe B). Low blast radius today (decision returns only the id) but it contradicts cast check 2 ("binds that exact expected outcome and scope"), and matters once a consumer trusts the object. Bind `outcome.run_id == aggregate.run.run_id` and/or fall under the full-equality fix in F1.

### F4 — LOW: `TASK_UNAVAILABLE` catches broad `Exception`

`outcome_learning_gate.py:60-63` catches all `Exception`. Fail-closed direction is correct, but it silently converts programming errors (e.g. a bug in rehydration) into an admission denial, hiding defects. Prefer the specific not-found exception (`TaskNotFoundError`).

## 4. Checklist verification

- **(a) Can a non-verified/stale/out-of-scope/unknown-evaluator/non-current outcome be admitted?**
  - Non-VERIFIED: denied (`:79-80`). ✔
  - Out-of-scope tenant/workspace/evaluator type+version: denied (`:69-77`). ✔
  - Reported "current" that is stale/superseded: stored `current_outcome` re-verifies and id must match (`:85-91`); a fabricated id → `OUTCOME_NOT_CURRENT` (probe E). ✔ *for the stored outcome*.
  - Unknown evaluator: denied (`:82-83`) — but **untested** (F2).
  - No expected outcome: denied (`:65-67`). ✔
  - **Forged VERIFIED payload under a genuine id: ADMITTED (F1).** ✘
- **(b) Truly read-only?** Yes. The gate only reads via `get_task`, `evaluator_registry.get`, `current_outcome` (pure projection). No Task/belief/knowledge writes; no belief/knowledge imports. `test_gate_does_not_mutate_task_state` supports this. ✔
- **(c) Does the positive test use a genuine verified outcome?** Yes. `_verified()` (`test_outcome_learning_gate.py:70-129`) runs the real `AgentOSApplication` golden path, asserts `result.observed_outcome.status is OutcomeStatus.VERIFIED`, and returns that object; `test_admits_a_current_verified_outcome` passes the genuine object. Not a mock/constant. ✔ (minor: `_verified` swallows the first `run_task` exception with `except Exception: pass`, which is sloppy but the final leg is asserted.)
- **(d) Evidence-binding bypass?** **Yes — F1.** ✔ (finding)
- C7-halt check (cast check 7) is marked optional and is not implemented; acceptable, but if retained in the cast it should be stated as deferred.

## 5. Verdict

**APPROVE_WITH_CHANGES**

### Required changes
1. `outcome_learning_gate.py:79-91` — re-validate the **supplied** outcome's evidence via the registered evaluator (or require `current == outcome` exact equality), mapping failures to `EVIDENCE_INVALID`; wire the currently-dead `EVIDENCE_INVALID` reason. (F1)
2. `tests/product/test_outcome_learning_gate.py` — add `test_rejects_forged_verified_evidence` (forged VERIFIED reusing the genuine id → `EVIDENCE_INVALID`) and `test_rejects_unknown_evaluator`, restoring the cast's 8-test set. (F1/F2)
3. `outcome_learning_gate.py:69-91` — bind `run_id` into the scope/current check. (F3)

### Recommended
4. Narrow the `except Exception` at `:60-63`. (F4)
5. Provide a clean public report-resolver accessor on `TaskService` if the evaluator is to be invoked from the gate, rather than reaching into privates.
6. G5 independence: this review is by the same model as the builder; a genuinely independent/cross-provider review at the fixed head is still required before merge.
