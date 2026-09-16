# Final Adversarial Review — P0-3 Increment 2: `OutcomeLearningGate`

> Reviewer role: FINAL adversarial reviewer (READ-ONLY on source/tests; only this report written)
> Worktree: `autonomous-agent-core/.worktrees/srl-learning-gate`
> Branch: `feature/srl-outcome-learning-gate-20260914` @ `0ca899db`
> Merge-base with `origin/main`: `cd3e816a` (verified via `git merge-base`)
> Commit chain under review: `3185fa05` (feat) → `dd266601` (fix) → `0ca899db` (test: falsify full-equality guard)
> Date: 2026-09-16
> Verdict: **APPROVE_WITH_CHANGES**

## 0. Independence limitation (stated honestly)

I am running as the model **`deepseek/deepseek-flash` (DeepSeek family)**, served through the opencode CLI. I have no cryptographic attestation of the builder's or the prior reviewers' identities, so I **cannot certify cross-provider independence**. The two in-tree prior reviews (`review-subagent.md`, `review-subagent-r2.md`) both explicitly state they were the *same model as the builder*; my review is by a different model than those files claim to be, but I cannot prove the builder itself was not also a DeepSeek-family model. All findings below are reproduced with my own executable probes against the real runtime, so the *evidence* is independent even though *provider independence cannot be self-certified*. The cast gate G5 ("cross-provider APPROVE at the exact head") is **not** something this review can unilaterally declare satisfied.

## 1. Scope of the diff

`git diff --stat cd3e816a..0ca899db` → 4 files, +453:
- `.agent_runs/srl-learning-gate-20260914/P0-3-increment-2-outcome-learning-gate-cast.md` (cast)
- `packages/os_core/src/agent_os_core/__init__.py` (+8 exports)
- `packages/os_core/src/agent_os_core/outcome_learning_gate.py` (new, 115 lines)
- `tests/product/test_outcome_learning_gate.py` (new, 279 lines)

No existing runtime file was modified. Worktree also shows `D agent-os.sqlite3.collaboration` and two untracked review files — pre-existing/other-agent artifacts, not part of this branch's commits.

## 2. Adversarial verification (all probes executed against the real golden path)

Probes were run from the worktree environment against a genuinely VERIFIED outcome produced by the real `AgentOSApplication` developer golden path (`_verified()`). Probe artifacts live in the pre-approved temp dir, not in the repo.

| # | Attack | `verify_verified_recording` | Gate verdict | Admitted? |
|---|---|---|---|---|
| — | genuine outcome | PASS | `ADMITTED` | yes (correct) |
| a1 | genuine id + `score=0.5` | RAISE | `EVIDENCE_INVALID` | no |
| a2 | genuine id + `score=0.0` | RAISE | `EVIDENCE_INVALID` | no |
| a3 | genuine id + `run_id="run:forged"` | RAISE (no durable report) | `EVIDENCE_INVALID` | no |
| a4 | genuine id + `observed_at = +1s` (future) | RAISE | `EVIDENCE_INVALID` | no |
| a5 | genuine id + `observed_at = -1s` (predates report) | RAISE | `EVIDENCE_INVALID` | no |
| a6 | genuine id + `confidence=0.01` | **PASS** | `OUTCOME_NOT_CURRENT` | no |
| a7 | genuine id + `evidence_refs=()` | RAISE | `EVIDENCE_INVALID` | no |
| a8 | genuine id + `evidence_refs + ("artifact:forged",)` (superset) | **PASS** (subset check only) | `OUTCOME_NOT_CURRENT` | no |
| b | `EVIDENCE_INVALID` reachable? | — | reached by a1–a5,a7 | **not dead code** |
| c | unknown evaluator task | n/a | `UNKNOWN_EVALUATOR` | no |
| d | read-only? | — | event count `before=40 after=40`; `test_gate_does_not_mutate_task_state` passes | **no writes** |
| e | bypass-detection | — | Equality-guard mutant (source recompiled with `current != outcome` removed) **admits** both the `confidence=0.01` forgery (`ADMITTED`) and the superset `evidence_refs` forgery (`ADMITTED`) | guard is load-bearing |

**Key bypass-detection result.** With the equality guard removed, the mutant gate returns `ADMITTED` for the confidence forgery and the superset-evidence forgery. Therefore `test_rejects_forgery_that_passes_the_evaluator` (line 256) turns RED if that guard regresses — the equality guard is bypass-detected. The evaluator alone does not bind `confidence` or extra `evidence_refs` (confirmed: the real `PytestOutcomeEvaluator.verify_verified_recording` PASSes both), so the full-equality check is the actual field binder.

### Answers to the required questions
- **(a) forged outcome reusing a genuine `observed_outcome_id` with altered score/evidence_refs/run_id/observed_at/confidence → REJECTED?** Yes, every variation tested was rejected (table above).
- **(b) `EVIDENCE_INVALID` reachable?** Yes — reproduced via score/run_id/observed_at/evidence_refs forgeries and covered by `test_rejects_forged_verified_evidence`.
- **(c) unknown evaluator rejected?** Yes — `UNKNOWN_EVALUATOR`.
- **(d) gate read-only?** Yes — no event append, no write token, event count unchanged, state-equality test passes.
- **(e) tests bypass-detecting?** Yes for the core path (equality guard covered by the confidence test; each denial reason asserted by `is` identity). One residual untested forgery vector (superset `evidence_refs`, F1).

## 3. Test results

```
uv run --extra product-test pytest tests/product/test_outcome_learning_gate.py -q
9 passed in 3.74s
```

Full product suite (regression check, not required by the task):
```
uv run --extra product-test pytest tests/product -q
23 failed, 2531 passed, 1 skipped in 242.53s
```
The 23 failures are **pre-existing and unrelated** to this branch (branch touches only an isolated new module + exports):
- `test_task_configuration_api.py`, `test_task_configuration_application.py` — hardcoded `NOW = datetime(2026, 7, 15)` with `expires_at=NOW + 30 days` ⇒ expired before today's run (`CommitmentExpiredError`). Date-bomb tests.
- `test_provider_relevance_assessor.py`, `test_data_agent_situated_fullstack.py`, `test_wave2_renderer_conformance.py` — environment/fixture composition and a `SurfaceEventBatch` sequence-validation fixture mismatch, in modules with no dependency on the new module.
Caveat: I did not execute the base commit `cd3e816a` to prove each failure predates the branch; I classify them by failure mode and module independence (high but not cryptographic confidence).

## 4. Findings

### F1 — MEDIUM (residual of prior F5, partially closed): superset `evidence_refs` forgery has no dedicated bypass-detecting test
`verify_verified_recording` only asserts `set(report.artifact_ids).issubset(outcome.evidence_refs)` (`outcome_evaluators.py:253`), so a genuine outcome with an **added** fake `artifact:*` ref PASSes the evaluator and is rejected solely by the full-equality guard (`outcome_learning_gate.py:102-108`). Reproduced: superset → `OUTCOME_NOT_CURRENT`, not admitted. The confidence test added at `0ca899db` closes the *bypass-detection* requirement for the equality guard in general, but this specific, evaluator-invisible forgery vector remains untested. Adding the test is a defense-in-depth guarantee, not a security hole today.

### F2 — LOW: broad `except Exception` masks programming errors
`outcome_learning_gate.py:60-63` (get_task) and `:89-97` (evaluator) catch `Exception`, converting any typing/refactor bug into `TASK_UNAVAILABLE` / `EVIDENCE_INVALID`. Direction is fail-closed (safe), but defects are hidden. `TaskService.current_outcome` similarly catches only `InvalidTransitionError`. Prefer typed catches.

### F3 — LOW: `current_outcome()` call is outside the try/except
`outcome_learning_gate.py:102` calls `self._tasks.current_outcome(task_id)` unguarded. `current_outcome` re-invokes the evaluator and only catches `InvalidTransitionError` internally; an unexpected exception propagates out of `admit` instead of returning a typed denial. No unauthorized admission results (it raises), but the "every denial returns a typed reason" property in the cast (G2) is not fully guaranteed for this path.

### F4 — INFO / claim discipline: no runtime consumer (not integrated)
`grep` shows `OutcomeLearningGate` referenced only in the module, `__init__.py` exports, and the test file. No W1/W2 belief/knowledge path calls it. This is consistent with the cast, which explicitly defers consumers to a later gated slice; the correct status claim is `specified / implemented / tested`, **not** `integrated`. Do not describe this increment as wired into learning.

### F5 — LOW: cast check #7 (C7 not halted) not implemented
The cast lists an *optional* check "(7) C7 is not halted for the scope"; the gate does not perform it. `record_outcome` enforces C7 halt at write time (`task_service.py:2764`), and this gate is read-only, so no authority bypass occurs. Before any downstream consumer mutates beliefs/knowledge, the C7-halt check must be added in that consumer slice.

### F6 — LOW: blank `task_id` yields a validation error, not a typed denial
`OutcomeAdmissionDecision.task_id` is `NonEmptyStr`; a blank `task_id` raises a pydantic `ValidationError` at decision construction rather than returning a fail-closed reason. Minor; callers pass real ids.

## 5. Strengths
- Fail-closed ordering is correct: existence → expected outcome → scope/evaluator binding → VERIFIED → registered evaluator → evidence re-validation on the **supplied** outcome → full-equality against the current trusted outcome.
- The supplied outcome (not just the stored one) is re-validated, so replaying a genuine id with forged fields is rejected before the equality check, and the equality check catches evaluator-invisible fields (confidence, extra refs).
- Positive path uses the real runtime golden path and asserts `VERIFIED`; denial paths use independent fixtures.
- `Ruff` clean and `Pyright` 0 errors on both new files (re-verified).
- The new test's `NOW = datetime.now(timezone.utc)` avoids the repo's date-bomb pattern.

## 6. Required and recommended changes

**Required before merge to main (G5):**
1. (F1) Add a bypass-detecting test for the added-`evidence_refs` (superset) forgery, e.g. `test_rejects_forged_evidence_refs_superset` asserting `admitted is False` and `reason_code is OUTCOME_NOT_CURRENT`. This closes the last evaluator-invisible forgery vector and pins the load-bearing equality guard against regression for both classes.
2. (Findings F2/F3) Narrow the broad `except Exception` catches to the typed exceptions (`InvalidTransitionError`, `TaskNotFoundError`) and wrap the `current_outcome()` call, so G2's "every denial returns a typed reason" holds for all paths. Retain a fail-closed fallback if desired, but do not swallow arbitrary programming errors silently.
3. (F4) State the claim level explicitly as `implemented/tested`, **not** `integrated`, and record that W1/W2 consumers + the optional C7-halt check (F5) are deferred to the next gated slice.

**Recommended:** document in `OutcomeAdmissionDecision`/gate docstring that the evaluator does not bind `confidence` or extra `evidence_refs` and that the full-equality guard is the field binder (F1/F6 context).

## 7. Verdict

**APPROVE_WITH_CHANGES**

The five required adversarial properties hold at `0ca899db`: forged outcomes are rejected, `EVIDENCE_INVALID` is live, unknown evaluators are denied, the gate is read-only, and the equality guard is bypass-detected. No admissible forged payload was found. The required changes above are coverage/robustness hardening and claim-discipline corrections — none of them indicates an exploitable admission path today. Merge to `main` additionally requires a genuinely cross-provider independent APPROVE at `0ca899db`, which this DeepSeek-family review cannot self-certify (see §0).
