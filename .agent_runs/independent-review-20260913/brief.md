# Independent Review Brief — SRL TaskActivationGate

> Subject: `feature/srl-closed-loop-1-20260913`
> Base: `0045aeea`  Head: `5923fa32` (commits `066f631e`, `5923fa32`)
> Builder: `opencode/deepseek-v4-flash` (builder_id)
> Reviewer: must be a different model/provider (no self-review, no silent fallback)
> Status: `IMPLEMENTED_TESTED / NOT_INTEGRATED / NOT_VERIFIED / NOT_PUSHED`

## Scope of the change

| File | Change |
|---|---|
| `packages/os_core/src/agent_os_core/srl_activation_gate.py` | NEW: `TrustedTaskActivationGate`, `TaskServiceCreationAdapter`, `ActivationDenialReason`, `C7ClearanceRef`, `TaskRequirements`, `CreatedTask`, `TaskActivationDecision` |
| `packages/os_core/src/agent_os_core/srl_runtime.py` | `activate_goal` now delegates to the injected `TaskActivationPort` after the I-23 producer!=acceptor check (was an unconditional hardcoded rejection) |
| `tests/product/test_srl_task_activation_gate.py` | NEW: 13 tests |

## Claim boundary

- implemented + targeted-tested only; **not** integrated-to-production, **not** verified.
- C7 semantics are **not** implemented: the gate consumes a `C7ClearanceRef` and compares its epoch to the Mandate's `correction_epoch`.
- The adapter only materializes a durable Task via `TaskService.ensure_task`; it does **not** commit, run, grant a capability or execute an effect.
- No push/merge/release; default M0 `InMemoryTaskActivation` remains fail-closed.

## Exact commands

```bash
git diff 0045aeea..5923fa32
git show 5923fa32 --stat && git show 066f631e --stat
uv run --extra product-test pytest tests/product/test_srl_task_activation_gate.py tests/product/test_srl_runtime_invariants.py -q
uv run --extra product-test ruff check packages/os_core/src/agent_os_core/srl_activation_gate.py packages/os_core/src/agent_os_core/srl_runtime.py tests/product/test_srl_task_activation_gate.py
uv run --extra product-test pyright packages/os_core/src/agent_os_core/srl_activation_gate.py packages/os_core/src/agent_os_core/srl_runtime.py tests/product/test_srl_task_activation_gate.py
```

## Required focus

1. Authority bypass: can a caller-minted `ActivationAuthority`, a mismatched goal binding, an expired/suspended Mandate, a missing/epoch-mismatched C7 clearance, or a missing ExpectedOutcome/Commitment reach `TaskService`?
2. I-23 separation: is producer!=acceptor enforced in both `SrlRuntime.activate_goal` and the gate?
3. Idempotency: is repeated activation of the same `ProposedGoal` truly idempotent through `TaskService.ensure_task` (event_id/occurred_at stability)?
4. Regression: does the `srl_runtime.activate_goal` delegation change any previously-passing behavior (39 invariants)?
5. Tests that would fail if the gate returned constant success or bypassed a required check.
6. Over-broad refactor / unnecessary abstraction / scope creep beyond the stated boundary.

## Required output

Write findings to `review.md` in this directory: findings first (severity + `file:line`), open questions, required changes, approval status (`APPROVE` / `APPROVE_WITH_*` / `NO_APPROVE`). Do not modify any source or test file.
