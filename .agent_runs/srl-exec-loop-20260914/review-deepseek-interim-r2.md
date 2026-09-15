# Independent adversarial RE-REVIEW — P0-3 Increment 1 SRL execution bridge (round 2)

> Reviewer: opencode / deepseek-v4-pro
> Builder: opencode / deepseek-v4-flash (SAME PROVIDER — **interim review only**; cross-provider review still required per G6 before promotion)
> Head: `d5934fce` (parent `5111ba37`; base `origin/main` = `456b6279`)
> Scope: `git diff 5111ba37..d5934fce` (3 files, +65/-28)
> Read-only. No source/test changes.

## Verification performed

- `git diff 5111ba37..d5934fce` → `__init__.py` (port rename), `srl_execution.py` (+42/-? ), `test_srl_execution_bridge.py` (+47/-? ).
- Read `srl_execution.py`, `test_srl_execution_bridge.py`, `task_configuration.py` (`seal`/`start_run`/`_require_original_correction_epochs`), `governance.py` (`CorrectionAuthority.guard_unchanged`/`_advance_and_abort_reentrant_guard`), `errors.py`, `c7_receipt.py`, `task_service.py` (`start_run`), `apps/api_server/app.py` (wiring + canonical start).
- `uv run --extra product-test pytest tests/product/test_srl_execution_bridge.py -q` → **9 passed** (was 8).
- `ruff check` on changed files → **All checks passed**; `pyright` → **0 errors, 0 warnings**.
- Repo-wide grep for the removed `SnapshotSealerPort`/`snapshot_sealer` → no dangling references; only `TaskSnapshotServicePort` remains.

## Required changes — confirmation

### (1) Close the verify→start C7 race via the C7-guarded start — CLOSED

- `srl_execution.py:190-192` now calls `self._snapshots.start_run(self._principal, task_id, snapshot.snapshot_id)` instead of the raw `self._tasks.start_run(...)`.
- `TaskSnapshotServicePort` (`srl_execution.py:70-90`) exposes `start_run`, and the concrete `TaskConfigurationSnapshotService.start_run` (`task_configuration.py:289-346`) is the guarded path: it calls `_require_original_correction_epochs(snapshot)` (`:298`, re-derives the live epoch vector for `TASK_CONFIGURATION_CAPABILITY` and compares to `snapshot.observed_correction_epochs`) and wraps the `_tasks.start_run` append in `guard_unchanged` (`:309-342`).
- `guard_unchanged` (`governance.py:140-168`) linearizes against concurrent corrections: it holds `self._lock` across the yield, re-snapshots + re-checks `halted` under the lock, and `_advance_and_abort_reentrant_guard` (`:188-202`) raises `CorrectionGuardConflict` on a reentrant same-thread `correct`. A cross-thread `correct` blocks on the lock; a reentrant one aborts. So a C7 change cannot slip between the epoch re-check and the `RUN_STARTED` append.
- This is the same guarded start the rest of the product uses (`apps/api_server/app.py:1590-1594`). The bridge is no longer bypassing it. ✔

### (2) Add `run_id == reserved_run_id` and mid-window-halt tests — CLOSED

- `test_result_run_id_equals_reserved_run_id` (`test_srl_execution_bridge.py:167-180`) asserts `result.run_id == aggregate.configuration_snapshot.reserved_run_id` and `aggregate.run.run_id == reserved`. This is the promised "condition 2 reserved-run-id" falsification (renamed from the cast's `test_commit_and_start_require_verified_c7_receipt`).
- `test_c7_change_before_start_leaves_committed_without_effect` (`:218-233`) was rewritten to use `_HaltingStartService`, whose `start_run` halts C7 **after** the bridge's verify and **before** the guarded append (`:57-61`). It asserts `committed=True, started=False, denial_reason=START_REJECTED, status=COMMITTED, run=None`. This is the required verify→append TOCTOU falsification.

### (3) Make `test_halted_c7_blocks_start` deterministic — CLOSED

- `test_halted_c7_blocks_start` (`test_srl_execution_bridge.py:236-250`) now asserts a single denial reason, `ExecutionDenialReason.SNAPSHOT_REJECTED`, with a comment explaining the seal step is itself C7-guarded so a pre-halted scope is denied there. The unreachable `C7_REJECTED` alternative is gone.

### (4) `_plan_binds` validates `plan.task_id` and capability — CLOSED

- `_plan_binds` (`srl_execution.py:209-231`) now computes `workflow_capabilities` and requires `plan.task_id == aggregate.task_id` (`:220`) and `plan.capability_id in workflow_capabilities` (`:221`), in addition to the pre-existing commitment/goal/workspace/expected_outcome checks.

## Adversarial bypass attempts

- **plan identity mismatch** (plan.task_id = "task:other", commitment still bound to the real task) → `PLAN_BINDING_MISMATCH` (empirically confirmed via a scratch `AgentOSApplication` + `_bridge`). The dead `plan.task_id` field is now live.
- **capability not in workflow** (capability_id = "admin.execute") → `PLAN_BINDING_MISMATCH` (empirically confirmed).
- **C7 change on the task scope mid-window** → the guarded start refuses (`START_REJECTED`), per the rewritten test. ✔
- **C7 change "during the guarded append"** → guarded by `guard_unchanged` lock + reentrant-abort; no window.

### Residual finding (non-blocking, but still open) — capability-scope C7 halt is NOT re-checked by the guarded start

The bridge's own C7 verify uses `plan.capability_id` as its scope (`srl_execution.py:171`, e.g. `workspace.read`), but the guarded start re-checks only `TASK_CONFIGURATION_CAPABILITY` (plus task/run scopes). A correction that halts **only** the `workspace.read` capability scope between verify and the start append is not detected. Empirically confirmed:

```
capability-scope halt mid-window -> committed=True started=True denial=None
run present: True
```

`_HaltingStartService` with `correct("capability", "workspace.read")` in `start_run` → the run still starts. This is the same capability-scope mismatch the prior review already flagged as "Related/defense-in-depth" (finding 2), now demonstrated to be concretely open. It does **not** execute an effect: the eventual runtime dispatch still consults `correction.halted(action.task_id, action.run_id, action.capability_id)` (`governance.py:372`), so the `workspace.read` tool call is blocked at dispatch. But against the strict CTO condition 2 wording ("C7 change between commit and start must forbid the start"), the `START` itself is not forbidden for a capability-scope halt.

Recommendation (does not block the required changes): either (a) scope the bridge's C7 verify to `TASK_CONFIGURATION_CAPABILITY` so it is fully redundant with the guarded start, or (b) explicitly document that the `plan.capability_id` check is defense-in-depth only and that a capability-scope halt permits `RUN_STARTED` but never an effect.

### Minor observation

- `_plan_binds` capability membership uses **all** nodes with a non-empty `capability` (`srl_execution.py:216-218`), not just `NodeKind.TOOL` nodes, whereas the authoritative `_derive_bindings` derives execution grants from `NodeKind.TOOL` nodes only (`task_configuration.py:407-413`). A `plan.capability_id` present only on a `TERMINAL` node would pass the bridge pre-check (empirically: `denial=None`, run starts) but is not a privilege escalation — plans are trusted-port-only and the aggregate seal enforces the real TOOL-node grant set. Suggest aligning the membership predicate to `node.kind is NodeKind.TOOL` for precision.

## Verdict

**APPROVE_WITH_CHANGES**

All four required changes are CLOSED with evidence: the raw start is replaced by the C7-guarded `TaskConfigurationSnapshotService.start_run`, the reserved-run-id and mid-window-halt falsifications exist, the halted test is deterministic, and `_plan_binds` checks plan identity and capability. Tests (9), ruff, and pyright are green; no dangling references to the renamed port. The only open item is the pre-existing capability-scope mismatch (now empirically confirmed): a capability-scope C7 halt between verify and start lets the run start (though the effect remains blocked at dispatch). Recommend aligning the bridge's C7 scope with `TASK_CONFIGURATION_CAPABILITY` or documenting the defense-in-depth boundary. Cross-provider review remains required before promotion (this is same-provider/interim).
