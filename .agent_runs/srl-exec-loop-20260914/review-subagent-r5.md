# Independent adversarial RE-REVIEW (round 5) — P0-3 Increment 1 SRL execution half-loop (production wiring / F3)

> Reviewer: opencode / deepseek-flash
> Builder: opencode / deepseek-flash (SAME MODEL — **self-review / interim only**; does NOT satisfy the cast's G6 cross-provider independent review/approval)
> Worktree: `/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/srl-exec-loop`
> Branch: `feature/srl-execution-half-loop-20260914`
> Fix commit under review: `ed57aeb9` (parent `e10aea1c`)
> Scope: `git diff e10aea1c..ed57aeb9` (4 code/test files + cast/r3/r4 docs)
> READ-ONLY on source/test. Scratch probes written to the pre-approved temp dir only; a temporary detached worktree at `e10aea1c` was used for the base-parity falsification and removed afterwards. `git status --short` / `git diff --check` on the review worktree are clean.

## Verification performed

- `git show ed57aeb9 --stat` / `git diff e10aea1c..ed57aeb9`:
  - `apps/api_server/app.py` +45 (composition of `SrlExecutionPlanRegistry` + `SrlTaskExecutionBridge` at `:584-601`; public `register_srl_execution_plan` at `:1531-1538`; public `commit_and_start_srl_task` at `:1540-1549`).
  - `packages/os_core/src/agent_os_core/srl_execution.py` +17 (`SrlExecutionPlanRegistry` at `:73-87`).
  - `packages/os_core/src/agent_os_core/__init__.py` +2 (import + `__all__`).
  - `tests/product/test_srl_execution_integration.py` +129 (3 app-level integration tests).
  - cast doc line flip + r3/r4 review docs.
- Read `apps/api_server/app.py` (composition at `:440-619`, methods at `:1531-1549`), `srl_execution.py` (full), `c7_receipt.py` (full), `server.py` (full route table), `surface_routes.py` (dispatch), `__main__.py` (CLI), `governance.py` (`correct`/`resume`/`_advance_and_abort_reentrant_guard`), prior reviews r3/r4.
- `uv run --extra product-test pytest tests/product/test_srl_execution_integration.py tests/product/test_srl_execution_bridge.py -q` → **15 passed** (3 integration + 12 bridge).
- `ruff check` on the 4 changed files → **All checks passed!**
- `pyright` on the 3 changed source files → **2 errors**, both the pre-existing `app.py:2478`/`:2495` `key_source` `Literal` errors, outside the diff (unchanged from base). `srl_execution.py` and `__init__.py` clean.
- `uv run --extra product-test pytest tests/product -q` → **23 failed, 2572 passed, 1 skipped**.
- Base-parity falsification at parent `e10aea1c` (temporary detached worktree, since removed): the same failing files → `test_task_configuration_application.py` + `test_task_configuration_api.py` + `test_wave2_renderer_conformance.py` = **20 failed**; `test_data_agent_situated_fullstack.py` + `test_provider_relevance_assessor.py` + `test_surface_stream_http.py` = **3 failed** → **23**, identical count. **Zero new failures.**
- App-composition-root probes (fresh SQLite per scenario) and a live HTTP probe against a booted `ThreadingHTTPServer`.

## Prior finding status

### F3 [was MEDIUM] — bridge had no production wiring / real caller

**Status: CLOSED (wiring + public entry point).**

- The bridge is now composed by the product composition root: `AgentOSApplication.__init__` builds `self.srl_execution_plans = SrlExecutionPlanRegistry()` and `self.srl_execution = SrlTaskExecutionBridge(task_service=self.tasks, plan_port=self.srl_execution_plans, task_snapshots=self.task_configurations, principal=self.principal, correction=self.correction, c7_issuer=C7ReceiptIssuer(...), c7_verifier=C7ReceiptVerifier(self.correction))` (`app.py:584-601`). The real ports are wired: the task service, the configuration-snapshot service (sealer/guarded start), and the correction authority.
- It is reached through a public product entry point: `app.register_srl_execution_plan(plan)` (`:1531-1538`) and `app.commit_and_start_srl_task(task_id, *, snapshot_command=None)` (`:1540-1549`), calling `self.srl_execution.commit_and_start(...)`.
- The new integration test drives the app entry points end to end: `test_application_wires_and_runs_the_srl_execution_bridge` (`:103-114`) starts a run and asserts `aggregate.run.run_id == result.run_id`; `test_commit_and_start_without_registered_plan_denies` (`:117-122`) asserts `PLAN_UNAVAILABLE`.
- **Residual (non-blocking, precision):** there is still no *non-test* production caller — no in-repo SRL organ invokes `register_srl_execution_plan`. The honest evidence class is therefore `wired at the composition root + tested through the public app entry point`; true end-to-end (`integrated/verified` with a live organ) remains gated on the deferred Increment 2 (organ-authored flow). The cast's `implemented + tested` line should be updated to reflect the wiring, but the claim must not be inflated to "organ-integrated".

## Verification of the three explicit conditions

### (a) F3 closed — composed by the product, reached through a public app method
Confirmed above: composition at `app.py:584-601`; public methods `:1531`/`:1540`; integration tests hit them (3 passed).

### (b) Plan source is composition-root-owned and NOT caller-injectable via HTTP/CLI — CONFIRMED
- `SrlExecutionPlanRegistry` is instantiated in `__init__` and owned by the app (`app.py:587`), passed as `plan_port` (`:590`); the bridge `SrlTaskExecutionBridge.commit_and_start` takes **no plan argument** (`srl_execution.py:143-148`). Condition 1's "bridge must not accept an organ-authored plan" holds at the bridge signature.
- `server.py` route table is fully static; `do_GET`/`do_POST` contain no `getattr`/reflection and no branch referencing `srl`, `register_srl_execution_plan`, or `commit_and_start_srl_task`. `surface_routes.py` dispatch likewise calls only fixed surface methods (no dynamic dispatch). `__main__.py` exposes no CLI flag for plan registration.
- Live HTTP probe (server booted, `GET /v1/tasks` → 200 to prove liveness): every guessed registration/start route returned **404** — `POST /v1/srl/plans`, `/v1/srl-execution-plans`, `/v1/tasks/task:x/srl-execution-plan`, `/v1/tasks/task:x/srl:register`, `/v1/srl:register`, `/v1/srl/commit-and-start`, `/v1/tasks/task:x/srl:commit-and-start`, `/v1/tasks/task:x/execution:start`.

### (c) C7 still gates the start — CONFIRMED
- The wiring uses the real `C7ReceiptIssuer`/`C7ReceiptVerifier` over `self.correction` (`app.py:594-600`), and the bridge still (i) verifies both `TASK_CONFIGURATION_CAPABILITY` and the plan's tool capability before start, then (ii) calls the C7-guarded `start_run(..., additional_capability_ids=(plan.capability_id,))` (`srl_execution.py:190-227`).
- Probe P4 (halt of `TASK_CONFIGURATION_CAPABILITY` before start via the app method): `committed=True, started=False, SNAPSHOT_REJECTED`, no run. Fail-closed. (The denial surfaces at the seal step rather than the explicit issuer/verifier loop because the config capability halt also blocks sealing — still no run.)
- Mid-window task/run/config/tool halts remain covered by the bridge tests (15 passing), whose fix (per-capability baseline) was adjudicated in r4 and is untouched by this commit.

### (d) No new bypass or regression — CONFIRMED
- App-composition-root probes (fresh DB each): P1 foreign-tenant goal → `PLAN_BINDING_MISMATCH`, task stays `DRAFT`, no mutation; P2 foreign-workspace → `PLAN_BINDING_MISMATCH`; P3 commitment task_id swap → `PLAN_BINDING_MISMATCH`; P5 plan capability not a workflow TOOL node → `PLAN_BINDING_MISMATCH`; P6 unregistered plan → `PLAN_UNAVAILABLE`; P7 happy path → `committed=True, started=True`, reserved/aggregate run ids match.
- Full `tests/product` 23 failures are **identical to the parent `e10aea1c`** (20+3 confirmed by running the same failing files at the base worktree). Zero new failures; ruff clean; pyright unchanged (2 pre-existing out-of-diff errors).

## NEW bypass attempts this round

| # | Attack | Result |
|---|---|---|
| P1 | HTTP/CLI reach of plan registration (8 route guesses on a live server) | all **404** — not reachable |
| P2 | Foreign-tenant goal + plan registered for it, via app method | `PLAN_BINDING_MISMATCH`, `DRAFT`, no mutation — blocked |
| P3 | Foreign-workspace goal (same tenant), via app method | `PLAN_BINDING_MISMATCH`, no mutation — blocked |
| P4 | Plan with `commitment.task_id` swapped to another task | `PLAN_BINDING_MISMATCH` — blocked |
| P5 | `plan.capability_id` not among workflow TOOL nodes | `PLAN_BINDING_MISMATCH` — blocked |
| P6 | No registered plan | `PLAN_UNAVAILABLE` — blocked |
| P7 | Config capability halted, then start | `SNAPSHOT_REJECTED`, no run — blocked (C7 gate holds) |
| P8 | Happy path | `started=True`, run id matches — correct |

No start bypass, no foreign-scope start, no halt missed, no effect execution found.

## NEW findings (non-blocking)

### N6 [LOW] `register_srl_execution_plan` is a public in-process method — "trusted plan only" is enforced by convention, not by type/authority
`AgentOSApplication.register_srl_execution_plan` is public and accepts an arbitrary `SrlExecutionPlan`; the registry cannot distinguish a trusted organ from an SRL organ. It is correctly **not** HTTP/CLI-reachable (verified), and the bridge still enforces `_plan_binds`, so there is no current exploit or authority escalation. But if/when an SRL organ shares the same app instance (Increment 2), it could register/replace a plan for a task. Recommendation before Increment 2: give the registry a provenance/issuer check, or expose it via a narrower trusted-organ seam rather than a bare public app method.

### N7 [LOW] Registry is in-memory and unpersisted; wiring is not restart-durable
`SrlExecutionPlanRegistry` holds a plain dict. A plan must be re-registered after every process restart, and a task left `COMMITTED` by a snapshot/C7 failure cannot be retried from the same plan across a restart. Acceptable for Increment 1 (no effect execution); note it before Increment 2.

### N8 [LOW — test quality] The composition test does not falsify the "not caller-injectable" claim
`test_srl_execution_bridge_is_composed` (`:125-129`) only asserts `app.srl_execution is not None` and `resolve("missing") is None`. There is no committed test that (i) a cross-tenant plan is denied through the new app method, or (ii) no HTTP route registers plans. My probes P2-P7 confirm the behavior, so this is a coverage gap, not a defect.

### Carry-over (unchanged, not re-adjudicated)
- **F4** `test_commit_succeeds_but_wrong_scope_is_denied_before_start` still mis-named/non-falsifying.
- **F5** cast drift (now partly addressed by the wiring; the cast status line still says "no production wiring").
- **F6** self-issued receipt — made concrete by this wiring: the composition root wires `C7ReceiptIssuer` and `C7ReceiptVerifier` over the *same* in-process `CorrectionAuthority`, so "external C7" is still an in-process object. Known and unchanged.
- **F7** inconsistent exception→denial envelope (e.g., a config-capability halt surfaces as `SNAPSHOT_REJECTED`, not `C7_REJECTED`; both fail-closed).

## Verdict

**APPROVE**

- **F3 CLOSED**: the bridge is composed by the product composition root (`app.py:584-601`) and reached through public app methods (`register_srl_execution_plan`, `commit_and_start_srl_task`), with integration tests exercising the app entry points (15 passed). Residual, stated honestly: no non-test organ caller yet; true end-to-end integration remains Increment 2.
- Condition (b) **preserved**: the plan source is composition-root-owned and not caller-injectable via HTTP/CLI (static route table, no CLI flag, live-probe 404s).
- Condition (c) **preserved**: C7 still gates the start through the app method (config-capability halt → no run; bridge window tests green).
- Condition (d) **no regression**: 23 `tests/product` failures identical to parent `e10aea1c`; ruff clean; pyright unchanged.
- New findings N6/N7/N8 are LOW and non-blocking for Increment 1; they should be resolved before Increment 2 (organ caller) lands.
- Independence limitation: **I am the same model (opencode / deepseek-flash) as the builder; this is a self-review and does NOT satisfy the cast's G6 cross-provider independent review/approval.**
