# Independent adversarial RE-REVIEW (round 4) — P0-3 Increment 1 SRL execution half-loop

> Reviewer: opencode / deepseek-flash
> Builder: opencode / deepseek-flash (SAME MODEL — **self-review / interim only**; does NOT satisfy the cast's G6 cross-provider independent review)
> Worktree: `/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/srl-exec-loop`
> Branch: `feature/srl-execution-half-loop-20260914`
> Fix commit under review: `e10aea1c` (parent `64842ffa`)
> Scope: `git diff 64842ffa..e10aea1c` (2 files: `task_configuration.py`, `test_srl_execution_bridge.py`)
> READ-ONLY on source/test. Scratch probes written to the pre-approved temp dir only; a temporary detached worktree at `64842ffa` was used for the falsification check and removed afterwards.

## Verification performed

- `git diff 64842ffa..e10aea1c`: `_nested_correction_guards` drops the shared `observed_epochs` argument and now calls `correction.snapshot(task_id, run_id, capability_id)` **per capability at guard entry** (`task_configuration.py:92-106`); `start_run` no longer passes `snapshot.observed_correction_epochs` (`:349-354`); the unused `import pytest` is removed and a new regression test is added (`test_srl_execution_bridge.py:189-201`).
- Read `task_configuration.py` (`_nested_correction_guards`, `seal`, `start_run`, `_require_original_correction_epochs`, `_derive_bindings`), `srl_execution.py`, `governance.py` (`snapshot`/`halted`/`guard_unchanged`/`_advance_and_abort_reentrant_guard`/`_current_thread_guard_matches`), `c7_receipt.py`, `app.py` (`correction_admin` split).
- `uv run --extra product-test pytest tests/product/test_srl_execution_bridge.py -q` → **12 passed**.
- `uv run --extra product-test ruff check packages/os_core/src/agent_os_core/task_configuration.py tests/product/test_srl_execution_bridge.py` → **All checks passed!**
- `uv run --extra product-test pyright packages/os_core/src/agent_os_core/task_configuration.py` → **0 errors, 0 warnings**.
- Deterministic adversarial probes (fresh SQLite per scenario, temp dir only) + a base-commit (`64842ffa`) falsification run.

## Prior finding status

### N3 [was HIGH] — the service reused the configuration capability's sealed epoch vector as the guard baseline for the tool capability, permanently denying valid starts after any prior correction

**Status: CLOSED. Confirmed by concrete evidence.**

- Root cause was a single shared `observed_epochs = snapshot.observed_correction_epochs` (captured at seal for `TASK_CONFIGURATION_CAPABILITY`, `task_configuration.py:230-234`, built at `:998`) passed to `guard_unchanged` for *every* guarded capability. Since `CorrectionEpochVector.capability_epoch` is per-capability (`governance.py:121-127`), the tool guard compared the tool capability's live vector against the config capability's sealed vector; any prior correction of either scope made them diverge → `TaskConfigurationDenied` → `START_REJECTED`.
- Fix: `_nested_correction_guards` now reads its own baseline per capability at entry — `observed = correction.snapshot(task_id, run_id, capability_id)` immediately before `guard_unchanged(..., observed)` (`task_configuration.py:92-106`). So each scope is compared against its own live epoch, and `_require_original_correction_epochs` (`:616-635`) independently anchors the sealed config-capability vector.
- Probes (fresh DB, no mid-window halt at all), at `e10aea1c`:

  | Probe | Scenario | Result at `e10aea1c` | Result at base `64842ffa` |
  |---|---|---|---|
  | P1 | prior `correct`+`resume` of tool `workspace.read`, then normal start | `committed=True started=True run=<id>` | `START_REJECTED`, no run |
  | P2 | prior `correct`+`resume` of `config.task.configuration.snapshot`, then normal start | `committed=True started=True run=<id>` | `START_REJECTED`, no run |
  | P3 | prior `correct`+`resume` of the **task** scope, then normal start | `committed=True started=True run=<id>` | n/a (task path unchanged) |
  | P4 | prior `correct` **without** `resume` of the tool capability | `committed=True started=False C7_REJECTED (C7AuthorityHalted)`, no run | denied too |

  P1/P2 now start; P4 (a genuine prior halt) still refuses at the C7 receipt step. This is exactly the boundary N3 was about: a *prior correction that was resumed* no longer poisons the start; a *live halt* still does.
- The new committed test `test_prior_tool_capability_correction_does_not_deny_valid_start` is genuinely falsifying: copied into a temp worktree at parent `64842ffa` it **fails** with `AssertionError: assert False is True … denial_reason=START_REJECTED detail='TaskConfigurationDenied'`; at `e10aea1c` it passes. (r3's N3 is therefore proven, not merely asserted.)
- Residual (non-blocking, test coverage only): the committed regression test covers the tool capability but not the config capability (my P2 confirms the config case by probe). A one-line parameterization would close the gap.

### N4 [was LOW — CI gate] — unused `import pytest` broke `ruff`

**Status: CLOSED.**

- The import is gone (`test_srl_execution_bridge.py:9-12` now starts directly at `from agent_os_contracts import (...)`).
- `ruff check packages/os_core/src/agent_os_core/task_configuration.py tests/product/test_srl_execution_bridge.py` → **All checks passed!** (r3 reported 1 `F401`; now 0.)

### F1 [was HIGH] — tool-capability C7 halt in the verify→start window permitted `RUN_STARTED`

**Status: STILL CLOSED; not regressed by this fix.**

- The fix changes only *where the baseline comes from* (own epoch vs config's sealed epoch), not the guard's halt coverage: `guard_unchanged` still returns `unchanged = (snapshot == observed) and not halted(...)` (`governance.py:150-153`), and `_nested_correction_guards` still raises `TaskConfigurationDenied` when a guard is not unchanged (`task_configuration.py:102-105`).
- Probe P8 (tool capability `workspace.read` halted *after* the bridge's verify, inside the wrapped `start_run`): `committed=True started=False START_REJECTED (TaskConfigurationDenied)`, `run=None`. Because the config path's `_require_original_correction_epochs` only checks task/run/config epochs, this denial can only come from the per-capability tool guard — the guard actually fires.
- Probes P5/P6/P7 (mid-window halt of the **task**, **run**, and **config-capability** scopes) all → `committed=True started=False START_REJECTED (TaskConfigurationDenied)`, `run=None`.
- The reentrant same-thread path (a `correct` executed while the guard is held) is unchanged: `_advance_and_abort_reentrant_guard` raises `CorrectionGuardConflict` (`governance.py:188-202`), mapped to `C7_REJECTED` in the bridge (`srl_execution.py:219-228`).

### N1 [was HIGH] — ABBA deadlock (authority→config) from the reverted bridge-side guard

**Status: NOT REINTRODUCED. No inversion; no deadlock path; not reproduced.**

- The fix touched only `_nested_correction_guards` internals; the lock acquisition order is unchanged and remains uniformly **config → authority**: `start_run` takes `_locked(self._configuration_lock)` (`task_configuration.py:327`) and only then enters `_nested_correction_guards` (authority `RLock`). `seal` (`:205`) and `assert_runtime_binding` (`:392`) are the same. The `snapshot()` calls added inside `_nested_correction_guards` happen *after* the config lock is already held (same path), and the bridge still holds no authority guard before calling `start_run` (`srl_execution.py` has no `guard_unchanged`; only the port docstring mentions it).
- Probe P10 (concurrent real `seal` on task B + real bridge `commit_and_start` on task A, real `CorrectionAuthority`, 15 s joins): `start_alive=False seal_alive=False errors=0`, bridge `started=True run=<id>`, seal returned a snapshot. No hang.
- The new per-capability `snapshot()` additions acquire the *same* authority lock that `guard_unchanged` will immediately acquire reentrantly (RLock) — they do not add a second lock, so no new order edge exists.

## NEW bypass attempts this round

| # | Attack | Result |
|---|---|---|
| P1 | Prior `correct`+`resume` of the tool capability, then valid start | `started=True run=<id>` — correctly allowed (N3 closed) |
| P2 | Prior `correct`+`resume` of the config capability, then valid start | `started=True run=<id>` — correctly allowed (N3 closed) |
| P3 | Prior `correct`+`resume` of the task scope, then valid start | `started=True run=<id>` — allowed |
| P4 | Prior `correct` (no resume) of the tool capability | `C7_REJECTED (C7AuthorityHalted)`, no run — blocked |
| P5 | Task-scope halt in the verify→start window | `START_REJECTED (TaskConfigurationDenied)`, no run — blocked |
| P6 | Run-scope halt in the window (reserved run id) | `START_REJECTED (TaskConfigurationDenied)`, no run — blocked |
| P7 | Config-capability halt in the window | `START_REJECTED (TaskConfigurationDenied)`, no run — blocked |
| P8 | Tool-capability halt in the window | `START_REJECTED (TaskConfigurationDenied)`, no run — blocked (F1) |
| P9a | `plan.capability_id == TASK_CONFIGURATION_CAPABILITY` while the workflow TOOL node is `workspace.read` | `committed=False PLAN_BINDING_MISMATCH`, no mutation — blocked |
| P9b | Workflow TOOL node capability **is** `TASK_CONFIGURATION_CAPABILITY` and the plan matches | `started=True` — **not a bypass**: the config capability is already a required, granted, C7-guarded scope; `start_run` dedups it out of `additional_capability_ids` (`task_configuration.py:341-348`) and the receipt verify is duplicated for the same scope. No elevation over the existing config guard. |
| P10 | Concurrent real `seal` + bridge `start_run` | both complete, no deadlock — no inversion |

No start bypass, no effect execution, no halt missed, no false denial (N3), and no deadlock were found. All probes passed.

## Residual / carry-over items (not re-adjudicated, unchanged severity)

- **N5 [LOW]** `test_tool_capability_midwindow_halt_blocks_start` still asserts `denial_reason in {C7_REJECTED, START_REJECTED}` rather than the exact intended `START_REJECTED`; the new committed regression test covers only the tool capability, not the config capability; still no committed cross-thread (non-reentrant) halt or `seal`-vs-`start_run` concurrency test.
- **F3** no production entry point/wiring → evidence class remains `implemented + tested`, not `integrated/verified`.
- **F4** `test_commit_succeeds_but_wrong_scope_is_denied_before_start` (`:332-342`) is still mis-named/non-falsifying.
- **F5/F6/F7** cast drift, self-issued receipt, inconsistent exception→denial envelope — unchanged.

## Verdict

**APPROVE**

- **N3 CLOSED** with concrete fresh-DB evidence: a prior resumed correction of the tool capability (P1), the config capability (P2) and the task scope (P3) all now allow a valid start (`started=True`), while a prior *live halt* (P4) and any mid-window halt of task/run/config/tool scopes (P5-P8) still fail closed with no run. The new committed regression test is genuinely falsifying (fails at parent `64842ffa`, passes at `e10aea1c`).
- **N4 CLOSED**: the unused `import pytest` is removed; `ruff check` on the changed files is clean.
- **F1 STILL CLOSED / not regressed**: the tool-capability guard still fires on a mid-window halt (`START_REJECTED`, no run).
- **N1 NOT reintroduced**: lock order is uniformly `config → authority`, and a concurrent real `seal` + `start_run` completed without a hang.
- Tests 12 pass, ruff clean, pyright clean on the changed source.
- Not blocking this fix: N5 (test assertion tightness / coverage), F3/F4/F5/F6/F7 are pre-existing and unchanged; they remain before integration/promotion, not before this correction.
- Independence limitation: **I am the same model (opencode / deepseek-flash) as the builder; this is a self-review and does NOT satisfy the cast's G6 cross-provider independent review/approval.**
