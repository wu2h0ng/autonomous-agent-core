# Final Adversarial Review — P0-3 SRL Increment 1 (`feature/srl-execution-half-loop-20260914` @ `900ab1e8`)

> Reviewer: opencode / `deepseek-flash` (provider family **DeepSeek**, model family **DeepSeek Flash**)
> Builder of the code under review: opencode / `deepseek-flash` (SAME model family/provider — see §8 Independence)
> Worktree: `/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/srl-exec-loop`
> Branch HEAD: `900ab1e8`; merge-base with `origin/main` = `456b6279`
> Scope reviewed: `git diff 456b6279..900ab1e8` (5 code/test files + cast/review docs)
> Method: read-only on source/test; a temporary detached worktree at `456b6279` (in the pre-approved temp dir) was used solely for base-parity falsification and removed afterwards. `git status --short` / `git diff --check` on this worktree are clean.

---

## 0. What was delivered

- `packages/os_core/src/agent_os_core/srl_execution.py` (+455): `SrlTaskExecutionBridge` (commit → seal → C7 verify → guarded start), `SrlExecutionPlan`, `TrustedSrlExecutionPlanPort`, `SrlExecutionPlanRegistry`, `SQLiteSrlExecutionPlanStore`, `plan_binds`, typed denial enums.
- `packages/os_core/src/agent_os_core/task_configuration.py`: `start_run(..., additional_capability_ids=())` + `_nested_correction_guards` (per-capability observed-epoch baseline inside the existing config→authority lock region).
- `apps/api_server/app.py`: composition-root wiring of store + registry + bridge; public `register_srl_execution_plan(plan, *, registered_by)` and `commit_and_start_srl_task(task_id, ...)`.
- `__init__.py` exports; tests `test_srl_execution_bridge.py` (12) and `test_srl_execution_integration.py` (10).

---

## 1. Required test run (step 3)

```
uv run --extra product-test pytest tests/product/test_srl_execution_bridge.py \
    tests/product/test_srl_execution_integration.py -q
=> 22 passed in 1.37s
```

- `ruff check` on all 6 changed files → **All checks passed!**
- `pyright` on `srl_execution.py`, `task_configuration.py`, `apps/api_server/app.py` → **2 errors**, both the pre-existing `app.py` `key_source: Literal[...]` errors at `:2517`/`:2534` (line numbers shifted by the +47-line diff; outside the diff, unchanged from base). `srl_execution.py` / `task_configuration.py` clean.
- Full `tests/product` → **23 failed, 2578 passed, 1 skipped**. Independently reproduced the failing 5 files at the true merge-base `456b6279` (temporary detached worktree): **23 failed**, and the sorted failure-name sets are **byte-identical** (`diff` empty) → **zero new failures**. (A one-off 24th failure appeared on the first full run and did not reproduce; consistent with the 2 known flaky tests documented in review r5.)

---

## 2. Verification of claim (a) — C7 non-writable/non-bypassable; verify→start race closed

**Holds for the bridge path.** Mechanism, confirmed by reading `srl_execution.py`, `task_configuration.py`, `governance.py`, `c7_receipt.py`:

- C7 is read-only from Runtime code: the bridge depends on `CorrectionReadPort`/`CorrectionSnapshotSource` (`snapshot`/`halted`/`guard_unchanged` only); `correct`/`resume` exist only on `CorrectionAdminView`. The bridge never writes an epoch. ✓
- Receipt scope is mandatory and complete (`C7VerificationScope` requires tenant/workspace/task/run/capability; `C7ReceiptVerifier` rejects scope mismatch, halted, authority-unavailable, and stale epoch). ✓
- Reserved run identity: the bridge seals first (`reserved_run_id`) and verifies/start with that id; no placeholder. ✓
- **Race window is closed at the service**, not at the bridge: `TaskConfigurationSnapshotService.start_run` re-reads the observed epoch vector *per capability at guard entry* (`_nested_correction_guards`, `task_configuration.py:76-108`, `:341-354`) and `guard_unchanged` fails when `snapshot != observed or halted(...)` (`governance.py:149-168`). Therefore:
  - a config/tool capability pre-halted before start → denied (`guard_unchanged` `unchanged=False`);
  - a halt landing after the bridge's verify but before/at guard entry → denied (observed read at entry + `halted` check);
  - a halt landing *during* the guarded region → blocked by the authority `RLock`; a reentrant same-thread `correct` → `CorrectionGuardConflict` → mapped to `C7_REJECTED`;
  - task/run scopes are covered because `halted()` checks all three scopes (`governance.py:129-138`).
- The `additional_capability_ids` tuple is deduped against `TASK_CONFIGURATION_CAPABILITY`; `ExitStack` exits LIFO; lock order is uniformly **config → authority**, so the previously-reverted ABBA deadlock (N1) is not reintroduced. ✓
- Denial before start leaves an auditably `COMMITTED` task with no run (tests assert `run is None`). ✓

**Gap found (MEDIUM) — the bridge is not the sole start authority.** `AgentOSApplication.start_run` (`app.py:1663-1690`), reached by HTTP `POST /v1/tasks/{id}/start` (`server.py:902-918`), calls `task_configurations.start_run(principal, task_id, snapshot_id)` **without** `additional_capability_ids`. It therefore guards only `TASK_CONFIGURATION_CAPABILITY`, never the workflow's TOOL capabilities. Because the bridge deliberately leaves a **sealed `COMMITTED`** task when a tool-capability C7 denial occurs, a subsequent generic start can start the Run even though the plan's tool capability is halted.

- Static evidence is unambiguous: `server.py:913` → `app.py:1674` → `task_configuration.py:341-354` (guarded set = config capability only unless the caller passes `additional_capability_ids`, which only the SRL bridge does at `srl_execution.py:417-422`).
- I could not execute a runtime probe for this one path: `uv run ... python -c` / stdin in this worktree intermittently dropped the project env (`ModuleNotFoundError: agent_os_contracts`) for the long script while short scripts resolved; rather than write a scratch file (write scope limited to this report) I relied on the static path, which is complete and unambiguous.
- Actual impact is bounded: this is **not** an effect-level bypass. The tool effect is still gated at dispatch by `PolicyKernel` (`governance.py:372`, `CORRECTION_HALTED`) and Increment 1 executes no effects. But the branch's stated framing “no path starts without a valid receipt” and the cast's F1 claim (“a tool-capability halt forbids start”) are true **only for the bridge path**, not globally.

---

## 3. Verification of claim (b) — plan registry cannot be caller-injected; N6/N7/N8

- **No HTTP/CLI plan path.** `grep -rn "srl"` over `apps/api_server/server.py`, `__main__.py`, `surface_routes.py` → **0 hits**; the route table is static; `AgentOSApplication.start_run` accepts only `configuration_snapshot_id` (`server.py:903`). ✓
- **N6 (registrant + validation + no silent overwrite).** `SrlExecutionPlanRegistry.register` requires a non-empty `registered_by` (`MISSING_REGISTRANT`) and refuses a second plan for the same task (`DUPLICATE_PLAN`); the store uses `INSERT` with `task_id` PRIMARY KEY, so no overwrite. `AgentOSApplication.register_srl_execution_plan` validates live-task existence, `DRAFT` status, and `plan_binds(...)` before accepting. ✓ (see LOW-1 for the residual seam).
- **N7 (restart durability).** `SQLiteSrlExecutionPlanStore` persists to the canonical DB with the same connection pattern as sibling stores; the registry reloads `(plan, registrant)` on construction. `test_durable_registry_survives_restart` closes and reopens the store and re-asserts resolve + registrant + duplicate refusal. ✓ (LOW-2: store is never closed by the app; `exists()` is unused.)
- **N8 (cross-tenant test).** `test_app_registration_refuses_foreign_tenant_binding` commits a forged foreign-tenant commitment and asserts `BINDING_MISMATCH`; `plan_binds` also anchors the goal tenant/workspace to the bridge principal (`srl_execution.py:255-282`), so a foreign-scope plan is denied before any mutation at both registration and commit. ✓ (It exercises commitment/tenant incoherence rather than a foreign-tenant *goal*, but it does falsify the cross-tenant binding path.)
- Bridge also re-validates at commit time, so even a plan inserted into the registry/seam without app-level validation cannot start without passing `plan_binds`.

---

## 4. Verification of claim (c) — failure paths typed / fail-closed / effect-free on denial

- Pre-commit denials (`TASK_UNAVAILABLE`, `TASK_NOT_DRAFT`, `PLAN_UNAVAILABLE`, `PLAN_BINDING_MISMATCH`, `COMMIT_REJECTED`) leave the task `DRAFT` and create no run.
- Post-commit seal failure → `SNAPSHOT_REJECTED`, task `COMMITTED`, no run. Post-commit C7 failure / reentrant guard conflict → `C7_REJECTED`, no run. `start_run` `AgentOSCoreError` → `START_REJECTED`, no run.
- Registration denials are enumerable (`PlanRegistrationDenialReason`) and fail closed (`MISSING_REGISTRANT`/`TASK_UNAVAILABLE`/`TASK_NOT_DRAFT`/`BINDING_MISMATCH`/`DUPLICATE_PLAN`).
- LOW-3: a non-`AgentOSCoreError` exception escaping `start_run` (e.g., a raw sqlite error) is not caught, and a store PK collision during a concurrent register raises an untyped `sqlite3.IntegrityError` rather than `DUPLICATE_PLAN`. Both still fail closed (exception), but are not typed.

---

## 5. Verification of claim (d) — no agent-framework outsourcing of the authority core

Confirmed. `srl_execution.py` imports only stdlib (`json`, `sqlite3`, `enum`, `pathlib`, `threading`) plus first-party `agent_os_contracts` and internal `.c7_receipt` / `.governance` / `.task_service` / `.task_configuration`. No external agent framework, no provider/model call, no effect execution. The task/authority/evidence/correction spine remains self-developed and the bridge only composes existing governed ports.

---

## 6. Verification of claim (e) — tests are bypass-detecting, not constant-return

Mostly yes. The bridge tests use the real `AgentOSApplication`, real SQLite, and the real `CorrectionAuthority`; they assert typed denial reasons and, on denial, that `run is None` / status is `DRAFT` or `COMMITTED` (not just code coverage). Registration tests assert the original plan + registrant survive a duplicate attempt (falsifies silent overwrite), and the restart test closes/reopens the store (falsifies in-memory-only). The `_HaltingStartService` genuinely injects a mid-window correction rather than stubbing success. Weak spots (non-blocking):

- `test_tool_capability_midwindow_halt_blocks_start` asserts `denial_reason in {C7_REJECTED, START_REJECTED}` (N5) — a two-element set, weaker than the intended exact reason.
- `test_commit_succeeds_but_wrong_scope_is_denied_before_start` (bridge `:332`) is mis-named/non-falsifying for its name: it asserts `committed is False`/`DRAFT` (a pre-commit binding denial), not the claimed “commit succeeds, start rejected” (carry-over F4).
- No committed test covers the sibling HTTP start path (§2 gap) → the “no path starts” claim is not falsifiable by the suite.

---

## 7. Findings

| ID | Severity | Finding | Required? |
|---|---|---|---|
| **F-A** | **MEDIUM** | Sibling start path (`AgentOSApplication.start_run` / HTTP `/start`) starts a sealed+`COMMITTED` task with only the config-capability guard; after the bridge leaves a sealed `COMMITTED` task on a tool-capability C7 denial, the tool halt does not forbid start there. Not an effect bypass (dispatch still C7-gated), but falsifies the global “no path starts without a valid receipt” framing. | Yes (document or close) |
| **LOW-1** | LOW | `SrlExecutionPlanRegistry.register` does not itself validate the live task; N6 validation lives only in `AgentOSApplication.register_srl_execution_plan`, while the registry is a public attribute (`app.srl_execution_plans`) whose `register` is callable directly (the integration test does so at `:142`). No authority escalation (bridge re-checks `plan_binds`, no HTTP/CLI), but the “trusted plan” boundary is convention. No lock → memory-only concurrent register could last-writer-win, and store PK collision is untyped. | Before Increment 2 |
| **LOW-2** | LOW | `SQLiteSrlExecutionPlanStore` is never closed by the app (no app `close()`), and `exists()` is dead code. | Recommended |
| **LOW-3** | LOW | Non-`AgentOSCoreError` escapes `start_run` untyped; concurrent-register PK collision raises raw `sqlite3.IntegrityError`. | Recommended |
| **LOW-4** | LOW | Test-quality items §6 (set-membership assertion; mis-named non-falsifying test; no sibling-path test). | Yes (with F-A) |
| INFO | — | Self-issued in-process C7 receipt (F6, known): issuer/verifier share the same `CorrectionAuthority`; the receipt is defense-in-depth over the epoch guards and `start_run` does not consume it, so the enforcing gate is the epoch guard, not the receipt object. Unchanged and in-scope-consistent. | No |
| INFO | — | `additional_capability_ids` is a public optional parameter on `TaskConfigurationSnapshotService.start_run`; currently only the bridge uses it. Watch that future callers cannot inject an untrusted capability id. | No |

---

## 8. Independence limitation (stated honestly)

I am **opencode running `deepseek-flash` (DeepSeek provider family, DeepSeek Flash model family)** — the **same model family/provider as the builder** of this branch and of the earlier subagent reviews r1–r5 (`review-subagent*.md` / `review-deepseek-interim*.md`). This is therefore a **same-family self-review, not a cross-provider independent review**. It does **not** satisfy the cast's G6 “cross-provider APPROVE at the exact head”, and the promotion gate remains open. The builder commit author is `wu2h0ng`; no identity claim is made that this review is independent in the G6 sense.

---

## 9. Verdict

**APPROVE_WITH_CHANGES**

The Increment 1 bridge is real, wired at the composition root, and its own C7 boundary is correct: the verify→start race is closed at the service level, denials are typed and fail-closed, the authority core is self-developed and not outsourced, and there are **zero new test failures** (independently reproduced at merge-base `456b6279`). It is not a NO_APPROVE: the MEDIUM finding is a scope/completeness gap that does not permit an effect (dispatch remains C7-gated) and is not a regression.

Required changes before this branch is treated as the SRL start authority / before Increment 2:

1. **F-A** — Either explicitly document in the cast and `CURRENT_STATE.yaml` that the SRL bridge is **not** the sole start authority and that the tool-capability start guard is **bridge-scoped** (effects remain C7-gated at dispatch), **or** close the gap by having the generic/sibling start derive and guard the workflow's TOOL capabilities (or refuse generic start of a sealed SRL task).
2. **LOW-4 / F-A test** — Add a committed regression test for the tool-capability-halt → generic-start path asserting the chosen behavior; tighten `test_tool_capability_midwindow_halt_blocks_start` to the exact denial; rename/repair the mis-named `test_commit_succeeds_but_wrong_scope_is_denied_before_start`.
3. **LOW-1** — Before any SRL organ shares the app instance, move N6 live-task/binding validation into the registry (or a narrower trusted-organ seam) and add synchronization so concurrent registration cannot overwrite; map store PK collisions to `DUPLICATE_PLAN`.

Non-blocking follow-ups: close the plan store on teardown (LOW-2); type the `_nested_correction_guards` `correction` parameter instead of `object` + `type: ignore`; type the rare untyped failure paths (LOW-3).

G6 cross-provider review and release/merge authorization remain outstanding and outside this review's authority.
