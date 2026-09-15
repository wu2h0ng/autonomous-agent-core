# P0-3 Execution Half-Loop — Gap Assessment + Implementation Cast

> Status: `CTO_CONDITIONAL_GATE_ISSUED 2026-09-14 / INCREMENT_1_ONLY`
> Track: product  primary_class: P  secondary_class: A/E
> Base: origin/main `456b6279`; branch `feature/srl-execution-half-loop-20260914` (worktree `.worktrees/srl-exec-loop`)
> Authority refs: `P-SRL-RUNTIME-1-design-2026-07-16.md`, `P-SRL-RUNTIME-VERIFICATION-MATRIX.md`, `A-SRL-1-threat-model-and-authority-invariants.md`, `GOAL-BLUEPRINT.md` §5

## 0. CTO gate conditions (binding, 2026-09-14)

Conditionally issued for Increment 1 (Product Track execution bridge) only; Increment 2 NOT issued. The conditions below are binding:

1. **Trusted plan only.** `commit_and_start` must NOT accept a plan authored by an SRL organ as execution authority. The plan is resolved by an injected trusted port and must be validated to bind the activated Task, tenant, workspace, Commitment, WorkflowGraph and ExpectedOutcome.
2. **Resolve run identity before C7.** `C7VerificationScope` requires `run_id` and `capability_id`, but without a configuration snapshot `start_run` generates the run id. The bridge must use a trusted, pre-reserved, bound run identity — the sealed `TaskConfigurationSnapshot.reserved_run_id` — and must not use placeholder ids or omit fields to pass the gate. C7 change between commit and start must forbid the start and leave an auditable `COMMITTED` state.
3. **RED tests are real behavioural falsification.** Tests 1-7 must fail on bypass, conflict, scope, halt, evaluator and state transitions. The former "learning gate absent" item is a scope statement, not a RED test; replace it with a test that commit succeeds but start is rejected, asserting the resulting state and that no execution effect occurred.
4. **Narrow acceptance boundary.** Only the trusted-plan commit/start bridge is in scope. NOT in scope: organ-authored execution contracts, effect execution, W1/W2 learning, knowledge candidates, push, merge or release.

## 1. Exact gap (measured on this base)

The activation gate's `TaskServiceCreationAdapter` only materializes a durable Task:

> "It does not commit, run, grant a capability or execute an effect; those remain separate governed gates."

So the SRL loop is observe -> assess -> TaskDraft -> create Task (DRAFT) ... and STOPS.

- **Gap A — commit + run bridge.** `TaskService.commit_task(task_id, commitment, workflow, expected_outcome)` and `start_run(...)` exist and are used by `selfdev_admission.py` (~L257-291, ~L1234, ~L1280), but there is no SRL-side bridge and no trusted plan source for SRL goals.
- **Gap B — `OutcomeLearningGate` is entirely absent** (`grep -rn OutcomeLearningGate packages tests` = nothing). This is Increment 2, NOT issued here.

## 2. Increment 1 design (condition-compliant)

New `packages/os_core/src/agent_os_core/srl_execution.py`:

```text
TrustedSrlExecutionPlanPort.resolve(task_id, authority) -> SrlExecutionPlan | None
SrlExecutionPlan = { commitment, expected_outcome, snapshot: TaskConfigurationSnapshot }
```

`SrlTaskExecutionBridge.commit_and_start(task_id, *, scope: C7VerificationScope)`:

1. resolve `SrlExecutionPlan` via the injected trusted port (never a caller/organ argument);
2. validate binding: `snapshot.consumer_task_id == task_id`, `snapshot.tenant_id/workspace_id == task tenant/workspace`, `snapshot.commitment_id == commitment.commitment_id`, `snapshot.workflow` matches the commitment scope; task must exist and be `DRAFT`;
3. seal the snapshot (`TaskService.seal_configuration_snapshot`) — this reserves/commits the run identity;
4. verify the C7 receipt with `run_id = snapshot.reserved_run_id` and `capability_id` (merged `C7ReceiptVerifier`); fail closed on halt/epoch/scope/unavailable;
5. `commit_task(task_id, commitment, snapshot.workflow, expected_outcome)`;
6. re-verify C7 (epoch unchanged) — if changed, do NOT start; return a typed `COMMITTED_C7_CHANGED` result and leave the auditable COMMITTED state;
7. `start_run(task_id, configuration_snapshot_id=snapshot.snapshot_id, provider_profile_id=snapshot.provider_profile.profile_id)`.

Denials are an enumerable `ExecutionDenialReason`; every denial path has no effect.

## 3. RED tests (must fail before implementation)

```
tests/product/test_srl_execution_bridge.py
  test_draft_task_commits_and_starts_a_run                 # happy path
  test_activated_task_cannot_commit_without_trusted_plan   # condition 1
  test_conflicting_second_commit_fails_closed
  test_plan_scope_mismatch_fails_closed                    # tenant/workspace/task/commitment binding
  test_commit_and_start_require_verified_c7_receipt        # condition 2 (reserved run id)
  test_halted_c7_blocks_commit_and_start
  test_unregistered_evaluator_blocks_commit
  test_commit_succeeds_but_c7_change_before_start_leaves_committed_without_effect  # condition 3
```

## 4. Gates

| Gate | Exit condition |
|---|---|
| G1 RED | 8 tests exist and fail pre-implementation |
| G2 no-author-bypass | SRL organ cannot author execution contracts; plan is trusted-only |
| G3 fail-closed | every denial returns a typed reason; no effect on denial |
| G4 C7 | the merged `C7ReceiptVerifier` gates commit+start with the reserved run id |
| G5 tests green | targeted tests pass; Ruff/Pyright clean; full tests/product zero new failures |
| G6 independent review | cross-provider APPROVE at the exact head |

## 5. Authority and claim boundary

- Only Increment 1 is authorized. No effect execution, no provider call, no learning, no knowledge candidates.
- No release/tag/deploy; no autonomy/HCW claim.
- Deferred: Increment 2 `OutcomeLearningGate`, `MethodSelector`/Dispatch breadth.
- Per-capability C7 boundary (subagent-review F1, CLOSED): the bridge verifies BOTH the start-authorizing `TASK_CONFIGURATION_CAPABILITY` scope and the plan's tool capability before start, and then holds a `guard_unchanged` on the tool capability across the run-start append (the snapshot service holds its own guard for the configuration capability). A correction landing in the verify->start window is therefore refused (the authority raises `CorrectionGuardConflict`, mapped to `C7_REJECTED`) and the run does not start. CTO condition 2 is met for task, run, configuration-capability and tool-capability scopes.
- Principal scope (subagent-review F2, CLOSED): `_plan_binds` now requires the task's goal tenant/workspace to equal the bridge principal's, so a cross-tenant plan is denied before any mutation.
- Status: `implemented + tested`, not `integrated` (no production wiring/real caller yet).
