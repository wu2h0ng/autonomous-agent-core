# Independent adversarial code review — P0-3 Increment 1 SRL execution bridge

> Reviewer: opencode / deepseek-v4-pro
> Builder: opencode / deepseek-v4-flash (SAME PROVIDER — **interim review only**; a cross-provider review is still required before promotion per G6)
> Head: `5111ba37` (base `origin/main` = `456b6279`)
> Scope: `git diff 456b6279..5111ba37`
> Read-only. No source/test changes; no worktrees; no /tmp.

## Verification performed

- `git diff 456b6279..5111ba37` (4 files, +566): `P0-3-execution-half-loop-cast.md`, `packages/os_core/src/agent_os_core/__init__.py`, `packages/os_core/src/agent_os_core/srl_execution.py` (+211), `tests/product/test_srl_execution_bridge.py` (+263).
- Read `srl_execution.py`, `c7_receipt.py`, `task_service.py` (`commit_task`/`seal_configuration_snapshot`/`start_run`), `task_aggregate.py` (`_validate_commitment_bindings`/`_validate_run_projection_bindings`/`_validate_configuration_snapshot_bindings`), `task_configuration.py` (`seal`/`start_run`), `governance.py` (`CorrectionAuthority`), `apps/api_server/app.py` (wiring + `start_run`), `selfdev_admission.py` (canonical commit/start flow).
- Ran `uv run --extra product-test pytest tests/product/test_srl_execution_bridge.py -q` → **8 passed**.
- Ran `ruff check` on the two new files → **All checks passed**; `pyright` → **0 errors**.

## Condition-by-condition findings

### (1) Trusted-plan only + binding validation — PASS (minor notes)

- The plan is resolved **only** through the injected `TrustedSrlExecutionPlanPort.resolve(task_id)` (`srl_execution.py:127`). `commit_and_start` accepts only `task_id` and an optional `snapshot_command`; a caller/organ cannot pass a `Commitment`/`WorkflowGraph`/`ExpectedOutcome`/plan as an argument. No execution-contract injection surface exists in the bridge signature. ✔
- Binding is validated in two layers: `_plan_binds` (`srl_execution.py:194-211`) and, authoritatively, inside the aggregate — `TaskAggregate.commit → _validate_commitment_bindings` (`task_aggregate.py:468-495`, checks task/goal/tenant/workspace + evaluator∈workflow.evaluator_refs) and seal `→ _validate_configuration_snapshot_bindings` (`task_aggregate.py:549-589`). The aggregate is the real enforcement; `_plan_binds` is a redundant pre-check. ✔
- Notes (not exploitable, incomplete vs. documented binding set):
  - `plan.task_id` (`SrlExecutionPlan.task_id`, `srl_execution.py:46`) is **never** checked against `aggregate.task_id`; the field is dead. Binding integrity is preserved only because `commitment.task_id`/`expected_outcome.task_id` are checked instead.
  - `plan.capability_id` (`srl_execution.py:50`) is used as the C7 scope capability but is **not** validated against the workflow's tool `NodeSpec.capability` set. It is trusted verbatim from the port.

### (2) Reserved run id + C7-before-start; C7 change after commit ⇒ COMMITTED, no run — PASS with one significant gap

- Run identity is `snapshot.reserved_run_id` (`srl_execution.py:156`), not a placeholder; `TaskService.start_run` resolves `resolved_run_id = snapshot.reserved_run_id` when a snapshot is present (`task_service.py:422`), and `_validate_run_projection_bindings` rejects any run whose `run_id != snapshot.reserved_run_id` (`task_aggregate.py:543`). ✔
- C7 is verified with `reserved_run_id` before start via `C7ReceiptIssuer.issue` + `C7ReceiptVerifier.verify` against `C7VerificationScope` (`srl_execution.py:152-161`); the verifier re-snapshots the live authority and raises `C7EpochReplay`/`C7AuthorityHalted` on change (`c7_receipt.py:150-162`). The `_HaltingSealer` test deterministically demonstrates a C7 halt between seal and verify leaving `committed=True, started=False, C7_REJECTED` with no run. ✔
- **Gap (required change): the actual start is not C7-guarded.** The bridge calls raw `self._tasks.start_run(...)` (`srl_execution.py:173`), i.e. `TaskService.start_run` (`task_service.py:387-463`), which performs **no** correction-authority check. The C7-guarded start is `TaskConfigurationSnapshotService.start_run` (`task_configuration.py:289-346`), which re-derives bindings, re-checks `_require_original_correction_epochs`, and wraps the append in `guard_unchanged` (`governance.py:140-168`). This is also the path the rest of the product uses (`selfdev_admission.py:1280` via `apps/api_server/app.py:1590-1594`). Because the bridge bypasses it, a C7 halt/epoch-advance landing **after** `verify` (line 161) but **before** the `RUN_STARTED` append (line 453) is not detected and the run still starts — a TOCTOU window that violates the strict reading of condition 2 ("C7 change between commit and start must forbid the start"). The bridge's issue+verify double-snapshot only closes the commit→seal→verify window, not the verify→append window.
- Related: the C7 scope capability is `plan.capability_id` (e.g. `workspace.read`), whereas the seal guards `TASK_CONFIGURATION_CAPABILITY` (`task_configuration.py:195-217`). The execution-capability check is a reasonable defense-in-depth addition, but it does not substitute for a guarded start on the reserved run id.

### (3) 8 tests are real behavioural falsification — MOSTLY PASS (two gaps)

All 8 pass and are behavioural (they assert aggregate state transitions, not just return codes): happy path, plan-absent denial, conflicting second commit (`TASK_NOT_DRAFT`), scope mismatch (`PLAN_BINDING_MISMATCH`), mid-window C7 halt (`C7_REJECTED` + no run), pre-halt, evaluator misbinding (`COMMIT_REJECTED`), wrong-scope-before-start (`PLAN_BINDING_MISMATCH`).

- Gap A: `test_halted_c7_blocks_start` (`test_srl_execution_bridge.py:203-219`) accepts a **set** of denial reasons `{C7_REJECTED, SNAPSHOT_REJECTED}`. In practice the pre-halt is always caught by the seal step (sealer `halted()` → `SNAPSHOT_REJECTED`), so the `C7_REJECTED` arm is unreachable and the test does not actually falsify the "C7 halt at the start gate" path.
- Gap B: the cast (`P0-3-execution-half-loop-cast.md` §3) promised `test_commit_and_start_require_verified_c7_receipt` (condition 2 reserved-run-id). It is **absent**. No test asserts `started.run.run_id == configuration_snapshot.reserved_run_id`; the run-identity guarantee is enforced by code (`task_aggregate.py:543`) but not falsified by a test. No test exercises the verify→start TOCTOU window from finding (2).

### (4) Narrow boundary — PASS

No effect execution, no provider call, no learning, no knowledge-candidate materialization, no organ-authored execution contracts, no push/merge/release. `TaskConfigurationSnapshotCommand` carries only `prior_selector` (default `None`, `task_configuration.py:101-102`), so a caller cannot inject commitment/workflow/provider content through `snapshot_command`; the only caller-influenced field is prior selection, which the sealer validates. ✔

## Additional observations

- Doc drift: the cast §2 orders the bridge as seal→verify→commit→re-verify→start and lists 8 test names that do not match the implementation (`commit→seal→verify→start` per the class docstring, `srl_execution.py:80-86`, and renamed/missing tests). The implementation's ordering is the *correct* one (the sealer requires committed workflow/expected_outcome via `_derive_bindings`, `task_configuration.py:398-399`); the cast should be reconciled, but this is documentation, not a code defect.
- G1 "RED before implementation" is not independently verifiable from this diff range: tests and implementation land in the same commit `5111ba37`; there is no separate failing-tests commit to inspect.
- `C7ReceiptIssuer`/`C7ReceiptVerifier` are constructed over `app.correction` (read view), while the sealer also reads `app.correction`; `_HaltingSealer` halts via `app.correction_admin.correct(...)` on the shared epoch store, so the halt is visible to both. Wiring is consistent. ✔

## Required changes (with file:line)

1. **[REQUIRED] Close the verify→start C7 gap.** Replace the raw start call `srl_execution.py:173` (`self._tasks.start_run(...)`) with the C7-guarded start path — expose a guarded `start` on the sealer port (or take `TaskConfigurationSnapshotService`), which re-checks `_require_original_correction_epochs` and wraps the append in `guard_unchanged` as `task_configuration.py:289-346` already does. Rationale: today a C7 change landing after `verify` (`srl_execution.py:161`) but before the `RUN_STARTED` append (`task_service.py:453`) still starts the run, violating CTO condition 2.
2. **[REQUIRED] Add a falsifying test** that asserts `result.run_id == sealed.reserved_run_id` (the promised `test_commit_and_start_require_verified_c7_receipt` from the cast §3) and a test that halts/advances C7 *after* verification but *before* the append to prove the start is refused (covers finding 2).
3. **[REQUIRED] Tighten `test_halted_c7_blocks_start`** (`test_srl_execution_bridge.py:203-219`) to assert a single denial reason (deterministically `SNAPSHOT_REJECTED`), or split it so the `C7_REJECTED` path is exercised by a real mid-window halt rather than accepted as an unreachable alternative.
4. **[RECOMMENDED] `_plan_binds`** (`srl_execution.py:194-211`): validate `plan.task_id == aggregate.task_id` and that `plan.capability_id` appears in the workflow's tool `NodeSpec.capability` set; the aggregate validators backstop the former today, but the bridge's own contract check should not silently accept a mismatched plan identity/capability.

## Verdict

**APPROVE_WITH_CHANGES**

The bridge is sound on the deterministic attack surfaces: plan is trusted-port-only (condition 1), run identity is the sealed `reserved_run_id` and C7 is verified with it before start for every path that can be reached without racing the final append (condition 2), the denial enum is exhaustive and effect-free, and the boundary stays narrow (condition 4). The blocking issue is the C7-unguarded final `start_run` (finding 2), which re-opens a window the CTO condition explicitly demands be closed, plus the missing reserved-run-id and TOCTOU falsification tests. These are fixable without redesign. A cross-provider review is still required (this review is same-provider/interim).
