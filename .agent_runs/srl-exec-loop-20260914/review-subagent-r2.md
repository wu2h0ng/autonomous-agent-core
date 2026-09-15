# Independent adversarial RE-REVIEW (round 2) — P0-3 Increment 1 SRL execution half-loop

> Reviewer: opencode / deepseek-flash
> Builder: opencode / deepseek-flash (SAME MODEL — **self-review / interim only**; does NOT satisfy the cast's G6 cross-provider independent review)
> Worktree: `/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/srl-exec-loop`
> Branch: `feature/srl-execution-half-loop-20260914`
> Head under review: `19778d94` (parent `9aa9ee17`; branch tip after it is `3ba7ac50`, docs-only)
> Scope: `git diff 9aa9ee17..19778d94` (3 files: cast doc, `srl_execution.py`, `test_srl_execution_bridge.py`)
> READ-ONLY on source/test. Scratch probes written to the pre-approved temp dir only.

## Verification performed

- `git diff 9aa9ee17..19778d94` (cast note; `srl_execution.py` +guard +principal binding; test +`test_tool_capability_midwindow_halt_blocks_start`, retargeted mid-window assertion to `C7_REJECTED`).
- Read `srl_execution.py`, `test_srl_execution_bridge.py`, `governance.py` (`CorrectionAuthority.halted`/`guard_unchanged`/`_advance_and_abort_reentrant_guard`/`_current_thread_guard_matches`/`split_correction_authority`), `task_configuration.py` (`seal`/`start_run`/`_require_original_correction_epochs`/`_validate_read_scope`), `c7_receipt.py`, `errors.py`, `apps/api_server/app.py` (wiring, principals, `_configuration_lock`).
- `uv run --extra product-test pytest tests/product/test_srl_execution_bridge.py -q` → **11 passed**.
- `ruff check` (changed source + test) → **All checks passed**; `pyright srl_execution.py` → **0 errors, 0 warnings**.
- Deterministic adversarial probes (fresh SQLite per scenario, temp dir only):
  - F1 re-test: tool-capability reentrant halt inside `start_run`.
  - F2 re-test: cross-tenant and cross-workspace goal+plan.
  - New: config-capability / run-scope / task-scope mid-window halts; plan identity mismatch; capability only on a TERMINAL node; plan capability == config capability.
  - New: cross-thread (non-reentrant) hail of the tool capability during the guarded window.
  - New: lock-order inversion probe using the real `TaskConfigurationSnapshotService.seal` and the real `start_run` (see N1).

## Prior finding status

### F1 [was HIGH] — Tool-capability C7 halt in the verify→start window permitted `RUN_STARTED`

**Status: CLOSED.**

- `srl_execution.py:184-200` captures the tool-capability receipt (`plan_receipt`) from the verify loop; `:207-221` wraps the `self._snapshots.start_run(...)` append in `self._correction.guard_unchanged(task_id, snapshot.reserved_run_id, plan.capability_id, plan_receipt.correction_epochs)` and refuses when `unchanged` is false (`C7EpochReplay`).
- `governance.py:140-168` holds `self._lock` across the `yield`, so the guard is live for the whole append; a same-thread reentrant `correct` on the matching scope hits `_advance_and_abort_reentrant_guard` (`governance.py:188-202`) → `CorrectionGuardConflict`.
- Repro (fresh DB): `_HaltingStartService(correct("capability","workspace.read"))` inside `start_run` → `committed=True started=False denial=C7_REJECTED detail=CorrectionGuardConflict status=COMMITTED run=None`. New test `test_tool_capability_midwindow_halt_blocks_start` (`test_srl_execution_bridge.py:255-269`) asserts exactly this and `run is None`.
- Cross-thread halts landing *before* guard entry are also caught: the guard's entry check re-reads `snapshot(...) == observed_epochs and not halted` (`governance.py:150-153`); a stale vector yields `unchanged=False` → `C7EpochReplay` → `C7_REJECTED`. A cross-thread halt arriving *while* the guard is held blocks on the authority lock and is linearized after the append (run starts, halt applies after, effect blocked at dispatch `governance.py:372`) — the same serialization semantics the config/task/run paths already use. No effect executes under a halt.

**Caveat (non-blocking):** the new test exercises only the reentrant same-thread path (the only way `CorrectionGuardConflict` can be raised). The realistic external (different-thread) halt is handled by linearizability, not by refusal — correct, but the test does not demonstrate it.

### F2 [was MEDIUM] — `_plan_binds` did not bind the plan to the bridge principal's tenant/workspace

**Status: CLOSED.**

- `_plan_binds` (`srl_execution.py:267-272`) now requires `goal.tenant_id == self._principal.tenant_id and goal.workspace_id == self._principal.workspace_id`; with the existing `commitment/workflow/expected_outcome == goal` checks (`:274-282`) the binding transitively covers the principal.
- Repro (fresh DB):
  - cross-tenant goal (`tenant:other`) → `committed=False denial=PLAN_BINDING_MISMATCH status=DRAFT`; `commitment is None`, `configuration_snapshot is None` → **denied before any mutation**.
  - cross-workspace goal (`ws:other`) → same `PLAN_BINDING_MISMATCH`, `DRAFT`, no mutation.
- The misleading post-commit `SNAPSHOT_REJECTED`/foreign-tenant COMMITTED state described in the prior F2 is gone.

## NEW findings (this round)

### N1 [HIGH] — The F1 fix introduces an ABBA lock-order inversion that can permanently deadlock the C7 authority and the configuration lock

The bridge now acquires the **authority** lock (`guard_unchanged`) and, while holding it, calls `TaskConfigurationSnapshotService.start_run`, which acquires the app-global **configuration** lock (`task_configuration.py:295`). Order: **authority → configuration**.

Every `TaskConfigurationSnapshotService.seal`/`start_run` does the opposite: it holds the configuration lock (`task_configuration.py:175` / `:295`) and then acquires the authority lock (`:195`/`:203`/`:208` / `:309`). Order: **configuration → authority**.

These two orders form a classic ABBA cycle. I reproduced it deterministically with the *real* `seal` and the *real* `start_run` (a pause hook only widens the window; the acquisition order is unchanged):

```
bridge thread alive (deadlocked) = True
seal   thread alive (deadlocked) = True
DEADLOCK REPRODUCED
```

Root-cause trace:
- T1 (bridge): enters `guard_unchanged(...)` → holds authority lock → calls `start_run` → blocks on `_configuration_lock`.
- T2 (`seal`, e.g. another task or the normal API path): holds `_configuration_lock` (`task_configuration.py:175`) → calls `self._correction.halted/snapshot/guard_unchanged` → blocks on the authority lock.

Both threads wait forever. Because the authority lock is process-wide, this wedges **all** correction operations (`correct`/`resume`/`snapshot`) and all configuration seals/start-runs — a governance-critical DoS. It is a **regression introduced by `19778d94`**: in parent `9aa9ee17` the `start_run` call was not wrapped in an authority guard (`git show 9aa9ee17:...srl_execution.py` contains no authority `guard_unchanged` around the append; the only occurrences are in the docstring), so the established order was uniformly configuration → authority.

Reachability: requires the bridge and a concurrent seal/start-run on different threads. The `RLock` + `ConcurrentWriteError` design of the snapshot service anticipates exactly such concurrency; the window is small but the failure is permanent. Impact is currently *latent* only because `SrlTaskExecutionBridge` still has no production wiring (prior F3, unchanged) — but the artifact under review is the bridge, and its core purpose here is atomicity.

Suggested directions (for the builder, not prescriptive): acquire the configuration lock before taking the authority guard (or have `TaskConfigurationSnapshotService.start_run` accept/guard an extra capability scope internally so the append and both guards are taken under a single, consistent lock order); or take the tool-capability guard without holding a lock the snapshot service also needs (e.g. verify + epoch re-check inside the snapshot service). Any fix must preserve the F1 property and keep a single global lock order.

### N2 [LOW] — `assert plan_receipt is not None` is a fail-open-ish pop under `-O`

`srl_execution.py:208`. With asserts stripped (`python -O`) and a hypothetical path where the tool receipt is unset, `plan_receipt.correction_epochs` raises an uncaught `AttributeError`, leaving `committed=True` with no typed `ExecutionDenialReason` — the same fail-closed-envelope gap as prior F7. In practice the verify loop always sets `plan_receipt` (both scope values are iterated), so it is currently unreachable; a non-`assert` guard returning `C7_REJECTED` would be more honest.

## Adversarial bypass attempts (fresh DB per scenario)

| # | Attack | Result |
|---|---|---|
| A1 | Reentrant tool-capability halt inside `start_run` (F1) | `committed=True started=False C7_REJECTED (CorrectionGuardConflict)`; no run — **blocked** |
| A2 | Cross-tenant goal + plan (F2) | `committed=False PLAN_BINDING_MISMATCH`, DRAFT, no mutation — **blocked** |
| A2b | Cross-workspace goal + plan (F2) | `committed=False PLAN_BINDING_MISMATCH`, DRAFT, no mutation — **blocked** |
| A3 | Config-capability halt mid-window (`TASK_CONFIGURATION_CAPABILITY`) | `committed=True started=False START_REJECTED (TaskConfigurationDenied)`; no run — **blocked** |
| A4 | Run-scope halt mid-window | `committed=True started=False C7_REJECTED (CorrectionGuardConflict)`; no run — **blocked** |
| A5 | Task-scope halt mid-window | `committed=True started=False C7_REJECTED (CorrectionGuardConflict)`; no run — **blocked** |
| A6 | Cross-thread tool-capability halt while guard held | Worker blocks on the authority lock; run starts, halt linearized after; effect blocked at dispatch — **serialized, no effect** |
| A7 | `plan.task_id` != aggregate task | `committed=False PLAN_BINDING_MISMATCH` — **blocked** |
| A8 | `plan.capability_id` present only on a TERMINAL node | `committed=False PLAN_BINDING_MISMATCH` — **blocked** |
| A9 | `plan.capability_id == TASK_CONFIGURATION_CAPABILITY` | `committed=False PLAN_BINDING_MISMATCH` (no config-capability elevation via plan) — **blocked** |

No effect execution, no provider call, no start bypass for task/run/config/tool scopes, and no cross-tenant mutation were found. The only new defect is the concurrency inversion N1.

## Carry-over items from round 1 (not re-adjudicated here, unchanged)

- F3 (no production wiring / trusted port): unchanged; evidence class remains `implemented + tested`, not `integrated`.
- F4 (mis-named non-falsifying `test_commit_succeeds_but_wrong_scope_is_denied_before_start`): still present (`test_srl_execution_bridge.py:304-314` asserts `committed is False`/DRAFT and names "commit succeeds").
- F5/F6/F7: unchanged; N2 is the F7 envelope gap resurfacing at `:208`.

## Verdict

**NO_APPROVE**

- F1 and F2 are **CLOSED** with concrete, fresh-DB evidence; all scopes (task/run/config-capability/tool-capability) refuse a mid-window halt with no run, and cross-tenant/cross-workspace plans are denied before any mutation. Tests (11), ruff and pyright are green.
- Blocking: the F1 fix wraps the C7-guarded append inside the authority lock while the snapshot service acquires the configuration lock, inverting the lock order used by `seal`/`start_run`. I reproduced a permanent ABBA deadlock with the real seal path. This is a new HIGH-severity regression on the C7-critical path; it must be fixed (consistent global lock order) and covered by a concurrency test before approval.
- Minor: N2 (assert-stripped fail-open envelope).
- Independence limitation: **I am the same model (opencode / deepseek-flash) as the builder; this is a self-review and does NOT satisfy the G6 cross-provider approval.**
