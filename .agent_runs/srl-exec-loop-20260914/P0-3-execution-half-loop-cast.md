# P0-3 Execution Half-Loop — Gap Assessment + Implementation Cast

> Status: `DESIGN_CAST / PRE_IMPLEMENTATION / CTO_GATE_REQUIRED`
> Track: product  primary_class: P  secondary_class: A/E
> Base: origin/main `a0c7a604`; branch `feature/srl-execution-half-loop-20260914` (worktree `.worktrees/srl-exec-loop`)
> Authority refs: `P-SRL-RUNTIME-1-design-2026-07-16.md`, `P-SRL-RUNTIME-VERIFICATION-MATRIX.md`, `A-SRL-1-threat-model-and-authority-invariants.md`, `GOAL-BLUEPRINT.md` §5

## 1. Exact gap (measured on this base)

The activation gate's `TaskServiceCreationAdapter` currently only materializes a durable Task:

> "It does not commit, run, grant a capability or execute an effect; those remain separate governed gates."

So the SRL loop is: observe -> assess -> **TaskDraft -> create Task (DRAFT)** ... and then STOPS. Missing:

- **Gap A — commit + run bridge.** Nothing turns the created DRAFT Task into committed, executing work. `TaskService.commit_task(task_id, commitment, workflow, expected_outcome)` and `start_run(...)` exist and are already used by `selfdev_admission.py` (builds Commitment/ExpectedOutcome/WorkflowGraph at ~L257-291; commits at ~L1234; starts at ~L1280), but there is no SRL-side bridge and no trusted plan source for SRL goals.
- **Gap B — `OutcomeLearningGate` is entirely absent.** `grep -rn OutcomeLearningGate packages tests` returns NOTHING. Outcome -> W1/W2 learning / knowledge candidate admission does not exist anywhere.

## 2. Increment 1 (this gate): SRL commit + run bridge (no learning yet)

New `SrlTaskExecutionBridge` in `packages/os_core/src/agent_os_core/srl_execution.py`:

- `commit_and_start(task_id, *, plan: SrlExecutionPlan, c7: C7ClearanceReceipt, scope: C7VerificationScope)`.
- The `plan` (Commitment + WorkflowGraph + ExpectedOutcome) comes from an injected **trusted** `SrlExecutionPlanPort.resolve(...)`; the SRL organ cannot author execution contracts (authority stays in the spine).
- Preconditions, all fail-closed with an enumerable `ExecutionDenialReason`:
  - task exists and is `DRAFT` (no double-commit);
  - `plan` present and scope-bound (tenant/workspace/task match);
  - C7 receipt verifies via the merged `C7ReceiptVerifier` (epoch/halt/scope);
  - `ExpectedOutcome` evaluator is registered (contract_error None).
- Then `commit_task(...)`; then `start_run(...)`. It never executes an effect itself; dispatch remains `RunCoordinator` + `CapabilityBroker`.

Deferred (Increment 2, separate gate): `OutcomeLearningGate.admit(ObservedOutcome)` gating W1/W2 updates and knowledge candidates.

## 3. RED tests (must fail before implementation)

```
tests/product/test_srl_execution_bridge.py
  test_draft_task_commits_and_starts_a_run
  test_activated_task_cannot_commit_without_trusted_plan
  test_conflicting_second_commit_fails_closed
  test_plan_scope_mismatch_fails_closed
  test_commit_and_start_require_verified_c7_receipt
  test_halted_c7_blocks_commit_and_start
  test_unregistered_evaluator_blocks_commit
  test_learning_gate_absent_until_increment_2   # explicit boundary
```

Each must fail if the bridge commits without a plan, skips C7 verification, double-commits, or starts a run without commit.

## 4. Gates

| Gate | Exit condition |
|---|---|
| G1 RED | 8 tests exist and fail pre-implementation |
| G2 no-author-bypass | SRL organ cannot author execution contracts; plan is trusted-only |
| G3 fail-closed | every denial path returns a typed reason; no effect on denial |
| G4 C7 | the merged `C7ReceiptVerifier` gates commit+start |
| G5 tests green | targeted tests pass; Ruff/Pyright clean; full tests/product zero new failures |
| G6 independent review | cross-provider APPROVE at the exact head |

## 5. Authority and claim boundary

- Implementation requires a CTO gate; this cast is not that gate.
- No effect execution in this increment; no provider call; no learning.
- No release/tag/deploy; no autonomy/HCW claim.
- Deferred: `OutcomeLearningGate` (Increment 2), knowledge/procedure candidate admission, and the `MethodSelector`/Dispatch breadth.
