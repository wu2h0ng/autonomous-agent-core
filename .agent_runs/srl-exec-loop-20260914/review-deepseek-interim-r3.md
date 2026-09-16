# Independent adversarial RE-REVIEW — P0-3 Increment 1 SRL execution bridge (round 3)

> Reviewer: opencode / deepseek-v4-pro
> Builder: opencode / deepseek-v4-flash (SAME PROVIDER — **interim review only**; cross-provider review still required per G6 before promotion)
> Head: `9aa9ee17` (parent `d5934fce`; base `origin/main` = `456b6279`)
> Scope: `git diff d5934fce..9aa9ee17` (3 files)
> Read-only. No source/test changes.

## Verification performed

- `git diff d5934fce..9aa9ee17` → `srl_execution.py` (C7 scope loop + `NodeKind.TOOL` filter), `test_srl_execution_bridge.py` (+`test_capability_scope_halt_blocks_start`), cast doc (per-capability boundary note).
- Read `srl_execution.py`, `test_srl_execution_bridge.py`, `task_configuration.py` (`TASK_CONFIGURATION_CAPABILITY`, `seal`, `start_run`, `_derive_bindings`), `governance.py` (`halted`/`guard_unchanged`/`_advance_and_abort_reentrant_guard`, `:372` dispatch halt), `c7_receipt.py`.
- `uv run --extra product-test pytest tests/product/test_srl_execution_bridge.py -q` → **10 passed** (was 9).
- `ruff check` changed files → **All checks passed**; `pyright` → **0 errors, 0 warnings**.
- Scratch adversarial probes (`/tmp` only, not committed) — see bypass section.

## Residuals from round 2 — confirmation

### (R2-1) Capability-scope C7 halt was not re-checked before start — CLOSED (with documented boundary)

The bridge's own pre-start verify now iterates **both** scopes (`srl_execution.py:179-192`):

```python
for capability_id in (TASK_CONFIGURATION_CAPABILITY, plan.capability_id):
```

- A **pre-existing** capability-scope halt (halt on `plan.capability_id`, e.g. `workspace.read`) is now caught at the verify step → `committed=True, started=False, denial_reason=C7_REJECTED`. New falsification `test_capability_scope_halt_blocks_start` (`test_srl_execution_bridge.py:253-265`) confirms this; run is absent.
- The start-authorizing scope (`TASK_CONFIGURATION_CAPABILITY`) is now the *primary* verify scope and is fully redundant with the C7-guarded `start_run` (`guard_unchanged` on `snapshot.observed_correction_epochs`, `task_configuration.py:309-314`), so that scope is race-free.
- The **mid-window** capability-scope halt (a halt on `plan.capability_id` landing *after* the verify but *before* the guarded append) still permits `RUN_STARTED`, because `start_run`'s guard re-checks only `TASK_CONFIGURATION_CAPABILITY`. This is now **explicitly documented** as the defense-in-depth boundary in both the code comment (`srl_execution.py:174-178`) and the cast (`P0-3-execution-half-loop-cast.md`): *"a per-capability halt landing after this point still blocks the effect at dispatch, not the start … No effect is ever executed under a halt."* Empirically confirmed below (BYPASS1).

This satisfies round-2's recommendation (b) (document the defense-in-depth boundary) plus the (a) half (verify the config scope as the start-authorizing scope). The strict CTO-condition-2 wording is not met for a capability-scope halt in the narrow verify→append window, but the C7 security invariant — **no effect executes under a halt** — is preserved, because dispatch consults `correction.halted(action.task_id, action.run_id, action.capability_id)` (`governance.py:372` → `CORRECTION_HALTED`). No high-consequence action can occur.

### (R2-2) `_plan_binds` capability membership used all node kinds — CLOSED

`_plan_binds` now filters to tool nodes only (`srl_execution.py:224-228`):

```python
workflow_capabilities = {
    node.capability
    for node in workflow.nodes
    if node.kind is NodeKind.TOOL and node.capability
}
```

A `plan.capability_id` present only on a `TERMINAL` node now fails binding (empirically confirmed: `PLAN_BINDING_MISMATCH`). This aligns the pre-check with the authoritative `_derive_bindings` (`task_configuration.py:407-413`), which derives execution grants from `NodeKind.TOOL` nodes only.

## Adversarial bypass attempts (scratch, /tmp only)

- **BYPASS1 — mid-window capability-scope halt** (`_HaltingStartService` halts `capability=workspace.read` inside `start_run`, after verify, before guarded append) → `committed=True started=True denial=None run_present=True`. The run starts, as documented; the effect is blocked at dispatch by `governance.py:372`. No effect executes under a halt. (Documented boundary, not a new gap.)
- **BYPASS2 — capability only on a TERMINAL node** (`plan.capability_id="admin.execute"`, present on `done` node only) → `committed=False denial=PLAN_BINDING_MISMATCH`. R2 minor observation fixed.
- **BYPASS3 — `plan.capability_id == TASK_CONFIGURATION_CAPABILITY`** (config capability is not a TOOL-node capability) → `committed=False denial=PLAN_BINDING_MISMATCH`. Fail-closed, no config-capability elevation via plan.
- No new privilege escalation, effect execution, or start bypass found.

## Verdict

**APPROVE**

Both round-2 residuals are CLOSED with evidence: the pre-start verify now re-checks the tool capability scope (new `C7_REJECTED` falsification) and verifies the start-authorizing `TASK_CONFIGURATION_CAPABILITY` as the primary scope; the mid-window capability-scope boundary is explicitly documented and preserves the C7 invariant (effect blocked at dispatch); and `_plan_binds` now restricts capability membership to `NodeKind.TOOL` nodes (empirically confirmed). Tests (10), ruff, and pyright are green. Remaining note (non-blocking): the strict CTO-condition-2 wording is not met for a capability-scope halt landing in the verify→append window, but this is documented and carries no effect-execution risk. Cross-provider review remains required before promotion (this is same-provider/interim).
