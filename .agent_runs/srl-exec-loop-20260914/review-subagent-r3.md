# Independent adversarial RE-REVIEW (round 3) — P0-3 Increment 1 SRL execution half-loop

> Reviewer: opencode / deepseek-flash
> Builder: opencode / deepseek-flash (SAME MODEL — **self-review / interim only**; does NOT satisfy the cast's G6 cross-provider independent review)
> Worktree: `/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/srl-exec-loop`
> Branch: `feature/srl-execution-half-loop-20260914`
> Fix commit under review: `64842ffa` (parent `d5220329`)
> Scope: `git diff d5220329..64842ffa` (3 files: cast doc, `srl_execution.py`, `task_configuration.py`, `test_srl_execution_bridge.py`)
> READ-ONLY on source/test. Scratch probes written to the pre-approved temp dir only (a temporary detached worktree at `d5220329` was used only for a base comparison and was removed afterwards).

## Verification performed

- `git diff d5220329..64842ffa` (service-level `additional_capability_ids` + `_nested_correction_guards`; bridge passes `(plan.capability_id,)`; cast note flips F1 to OPEN then the fix closes it; test drops the `xfail`).
- Read `task_configuration.py` (`_nested_correction_guards`, `seal`, `start_run`, `_require_original_correction_epochs`, `_derive_bindings`), `srl_execution.py`, `governance.py` (`CorrectionAuthority.snapshot/halted/guard_unchanged/_advance_and_abort_reentrant_guard`), `c7_receipt.py`, `task_service.py` guarded-append sites, `apps/api_server/app.py` (`CorrectionAuthority` persistence, `_configuration_lock` sites, `start_run`).
- `uv run --extra product-test pytest tests/product/test_srl_execution_bridge.py -q` → **11 passed**.
- `uv run --extra product-test pytest tests/product/test_srl_execution_bridge.py tests/product/test_task_configuration_application.py -q` → **13 passed, 17 failed** (the 17 are the pre-existing base failures; not in scope).
- `ruff check` (changed source + test) → **1 error (F401)**; `pyright` (changed source) → **0 errors, 0 warnings**.
- Adversarial probes (fresh SQLite per scenario, temp dir only) + a base-commit (`d5220329`) comparison.

## Prior finding status

### F1 [was HIGH] — Tool-capability C7 halt in the verify→start window permitted `RUN_STARTED`

**Status: CLOSED. Confirmed by concrete evidence.**

- The service now guards the tool capability inside its existing `config->authority` region: `start_run` takes `additional_capability_ids` (`task_configuration.py:316-323`) and, after `_assert_snapshot_matches_bindings`, wraps the append in `_nested_correction_guards(...)` for `(TASK_CONFIGURATION_CAPABILITY, *additional)` (`:338-352`), which holds `guard_unchanged` for each capability across `self._tasks.start_run` (`:372-376`). The bridge passes `additional_capability_ids=(plan.capability_id,)` (`srl_execution.py:204-210`).
- `guard_unchanged` checks both epoch equality **and** `not halted` (`governance.py:150-153`) and holds the authority lock across the yield (`:149-168`), so any tool-capability halt landing before guard entry is refused at entry, and any halt landing reentrantly while the guard is held is refused by `_advance_and_abort_reentrant_guard` (`:188-202`).
- Probes (fresh DB):
  - **Window A** — a halt of the plan tool capability (`capability:workspace.read`) landing after the bridge's verify and before the guarded append → `committed=True started=False START_REJECTED (TaskConfigurationDenied)`, `run=None`. No run. (Same as the committed test `test_tool_capability_midwindow_halt_blocks_start`, `test_srl_execution_bridge.py:266-284`.)
  - **Window B (reentrant)** — a halt invoked inside the guarded append on the same thread → `committed=True started=False C7_REJECTED (CorrectionGuardConflict)`, `run=None`.
  - The committed test is genuinely falsifying: without the additional tool guard the run would start (the halt is on `workspace.read`, which `_require_original_correction_epochs` does not check), so the test would fail.

### N1 [was HIGH] — ABBA deadlock (authority→config) introduced by the reverted bridge-side guard

**Status: NOT reintroduced. No inversion; no deadlock path found; not reproduced.**

- The only lock acquisition order is **config → authority**: `start_run` takes `_locked(self._configuration_lock)` (`task_configuration.py:324`) and only then enters `_nested_correction_guards` (authority RLock) (`:346-352`). `seal` (`:202`) and `assert_runtime_binding` (`:390`) are the same. The bridge holds **no** authority guard before calling `start_run` (`srl_execution.py` has no `guard_unchanged`; the string appears only in the port docstring). It therefore never waits for the configuration lock while holding the authority lock.
- I checked every other `guard_unchanged` call site (`proposal_engine`, `materialization`, `capability`, `materialization_promotion`, `agent_loop`, `execution`, `task_service`, `materialization_evaluation`) and every `_configuration_lock` site in `app.py` (`:663, :669, :818, :1001, :1600, :1763, :1788`): none acquires the configuration lock while holding an authority guard. The order is uniform.
- Probe P5 (concurrent real `seal` on task B + real bridge `commit_and_start` on task A, real `CorrectionAuthority`): both threads completed, `bridge alive=False seal alive=False`, bridge `started=True`, seal returned a snapshot. No hang.
- Residual: no dedicated concurrency regression test was added for the fixed lock order. Because `seal` and `start_run` both take the configuration lock first, a `seal`-vs-`start_run` ABBA is not constructible with the current code.

### F2 [was MEDIUM] — `_plan_binds` did not bind the plan to the bridge principal's tenant/workspace

**Status: CLOSED (unchanged from round 2).** Probe P6: a goal created in `tenant:other` → `committed=False PLAN_BINDING_MISMATCH`, task stays `DRAFT`, no mutation. `_plan_binds` (`srl_execution.py:256-272`) anchors goal/commitment/workflow/expected_outcome to `self._principal.tenant_id/workspace_id`.

## Other scopes still forbid the start

Probe P8 (halts landed in the verify→start window, fresh DB per scope):

| Scope halted in window | Result | Run |
|---|---|---|
| `task` (`task_id`) | `committed=True started=False START_REJECTED (TaskConfigurationDenied)` | none |
| `run` (reserved run id) | `committed=True started=False START_REJECTED (TaskConfigurationDenied)` | none |
| `capability` (`task.configuration.snapshot`) | `committed=True started=False START_REJECTED (TaskConfigurationDenied)` | none |
| `capability` (`workspace.read`) | `committed=True started=False START_REJECTED (TaskConfigurationDenied)` | none |

## NEW findings (this round)

### N3 [HIGH] — The service-level tool guard reuses the **configuration capability's** epoch vector as the baseline for the tool capability, permanently denying valid starts after any prior correction

`_nested_correction_guards` guards every capability with the single `observed_epochs = snapshot.observed_correction_epochs` (`task_configuration.py:346-352`). That vector was captured at seal for **`TASK_CONFIGURATION_CAPABILITY`** (`:230-234`, `:998`). But `CorrectionEpochVector.capability_epoch` is **per-capability** (`governance.py:121-127`), so for the additional (tool) capability the guard compares the tool capability's live vector against the config capability's sealed vector. Those vectors are only equal when the two capability epochs happen to coincide (e.g. both `0`, the state all existing tests run in).

Consequence: as soon as the config capability **or** the plan's tool capability has ever been corrected (halt/**resume**) before the run, the epochs diverge, `guard_unchanged` returns `False` for the tool capability, and `_nested_correction_guards` raises `TaskConfigurationDenied` → `START_REJECTED`. The start is refused even though **no** correction landed in the verify→start window. The epoch is persisted in SQLite (`app.py:443-448` hands `self.store` to `CorrectionAuthority`), so the denial survives restarts; the capability scope is global per capability id, so one correction poisons every plan using that capability.

Probes (fresh DB, no mid-window halt at all):

| Probe | Scenario | Result at `64842ffa` | Result at base `d5220329` |
|---|---|---|---|
| P1 | prior `correct`+`resume` of tool `workspace.read`, then normal start | `committed=True started=False START_REJECTED (TaskConfigurationDenied)`, `run=None` | **started=True** |
| P2 | prior `correct`+`resume` of `task.configuration.snapshot`, then normal start | `committed=True started=False START_REJECTED (TaskConfigurationDenied)`, `run=None` | **started=True** |
| P7 | P1, then a second `AgentOSApplication` on the same DB | still `START_REJECTED`, `run=None` | n/a |

This is a **regression introduced by `64842ffa`**, not present at base. It is **fail-closed** (no bypass, no halt is missed — the `not halted(...)` clause in `guard_unchanged` is what actually closes F1) but it is a real availability defect on the C7 start path: it makes the bridge unable to start any run whose config or tool capability has ever been corrected. Severity is latent only because the bridge still has no production wiring (F3).

Correct direction (for the builder, not prescriptive): guard each additional capability against its **own** live baseline captured after the verify step (or pass a per-capability baseline map, or capture the tool capability's `snapshot(...)` at guard entry while also requiring `not halted`). Whichever is chosen must keep F1 closed and must include a regression test with a **nonzero prior epoch**.

### N4 [LOW — CI gate] — `ruff check` now fails: `import pytest` is unused

The `xfail` decorator was removed from `test_tool_capability_midwindow_halt_blocks_start` but `import pytest` remains (`test_srl_execution_bridge.py:12`). `ruff check` reports `F401 'pytest' imported but unused` (1 error). This breaks the Product Track basic gate `uv run --extra product-test ruff check apps packages/contracts/src packages/os_core/src tests/product`. (Rounds 1/2 had ruff green.) Fix: drop the import or restore a `pytest` usage.

### N5 [LOW] — Test quality regressions

- `test_srl_execution_bridge.py:280-283` accepts `denial_reason in {C7_REJECTED, START_REJECTED}`; it would not distinguish the intended service-guard path from an unrelated denial. Assert the exact reason (`START_REJECTED` here).
- No test exercises a **nonzero prior epoch** (would have caught N3), a cross-thread (non-reentrant) halt, or the `seal`-vs-`start_run` lock order.

## Carry-over items (unchanged from round 1/2, not re-adjudicated)

- **F3** no production entry point/wiring → evidence class remains `implemented + tested`, not `integrated/verified`.
- **F4** `test_commit_succeeds_but_wrong_scope_is_denied_before_start` (`:319-329`) is still mis-named and non-falsifying.
- **F5** cast drift; **F6** self-issued receipt; **F7** inconsistent exception→denial envelope (the reverted N2 `assert plan_receipt` pop is gone with the revert).

## Adversarial bypass attempts (fresh DB per scenario)

| # | Attack | Result |
|---|---|---|
| A1 | Tool-capability halt in the verify→start window (window A) | `START_REJECTED`, no run — **blocked** |
| A2 | Reentrant tool-capability halt inside the guarded append (window B) | `C7_REJECTED (CorrectionGuardConflict)`, no run — **blocked** |
| A3 | Task-scope halt in window | `START_REJECTED`, no run — **blocked** |
| A4 | Run-scope halt in window (reserved run id) | `START_REJECTED`, no run — **blocked** |
| A5 | Config-capability halt in window | `START_REJECTED`, no run — **blocked** |
| A6 | Cross-tenant goal + plan | `PLAN_BINDING_MISMATCH`, DRAFT, no mutation — **blocked** |
| A7 | Concurrent real `seal` + bridge `start_run` | both complete, no deadlock — **no inversion** |
| A8 | Prior correction of config/tool capability, then normal start | `START_REJECTED` though no window halt — **false denial (N3)** |

No effect execution, no provider call, no start bypass for task/run/config/tool scopes, and no deadlock were found. The security property F1 is genuinely closed; the new defect is the fail-closed false denial N3.

## Required changes

1. **Fix N3 (blocking before integration/promotion):** guard each additional capability against its own epoch baseline; add a regression test with a nonzero prior `correct`/`resume` on (a) the tool capability and (b) `TASK_CONFIGURATION_CAPABILITY`, asserting the run **starts**.
2. **Fix N4 (blocking the basic gate):** remove the unused `pytest` import (or restore a `pytest` marker usage).
3. Tighten `test_tool_capability_midwindow_halt_blocks_start` to assert the exact denial reason, and add the missing cross-thread/concurrency coverage (N5).

## Verdict

**APPROVE_WITH_CHANGES**

- **F1 CLOSED** with concrete fresh-DB evidence: a tool-capability halt in the verify→start window (before entry and reentrantly during the append) forbids the start with no run; task/run/config/tool scopes all still deny.
- **N1 NOT reintroduced**: the lock order is uniformly `config -> authority`, the bridge holds no authority guard across `start_run`, no other authority→config path exists, and a concurrent real `seal`+`start_run` completed without a hang.
- **F2 CLOSED** (unchanged).
- **Not an unconditional approval:** `64842ffa` introduces **N3 [HIGH]**, a fail-closed availability regression that permanently denies valid starts once the config or tool capability has ever been corrected (persisted across restart), plus **N4** breaking the `ruff` basic gate. These must be fixed (with a nonzero-prior-epoch regression test) before the bridge is wired or this increment is promoted.
- Independence limitation: **I am the same model (opencode / deepseek-flash) as the builder; this is a self-review and does NOT satisfy the cast's G6 cross-provider approval.**
