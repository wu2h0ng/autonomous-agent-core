# Independent adversarial review — P0-3 Increment 1 SRL execution half-loop

> Reviewer: opencode / deepseek-flash
> **Independence limitation: I am the SAME MODEL/provider as the builder (opencode / deepseek-flash).** This is a self-review; it does NOT satisfy the cast's G6 cross-provider independent review. Treat per-condition verdicts as interim.
> Head under review: `9aa9ee17` (branch tip `3ba7ac50`, docs-only). Base: `origin/main` `456b6279`.
> Scope: `git diff 456b6279..9aa9ee17` (4 files, +629).
> READ-ONLY on source/test. Scratch probes written to `/tmp` only.

## Verification performed

- `git diff 456b6279..9aa9ee17` (cast, `__init__.py`, `srl_execution.py` +241, `test_srl_execution_bridge.py` +295).
- Read `srl_execution.py`, `c7_receipt.py`, `task_service.py` (`create_task`/`commit_task`/`seal_configuration_snapshot`/`start_run`), `task_configuration.py` (`seal`/`start_run`/`_require_original_correction_epochs`/`_derive_bindings`), `task_aggregate.py` (`_validate_commitment_bindings`/`_validate_run_projection_bindings`/`_validate_configuration_snapshot_bindings`), `governance.py` (`halted`/`guard_unchanged`/`correct`), `capability.py` (`CapabilityBroker.invoke`), `apps/api_server/app.py` wiring, test file.
- `uv run --extra product-test pytest tests/product/test_srl_execution_bridge.py -q` → **10 passed**.
- `ruff check` (changed files) → **All checks passed**; `pyright srl_execution.py` → **0 errors, 0 warnings**.
- Scratch adversarial probes in `/tmp/opencode/p03_attack.py` (not committed) — results below.

## Condition verdicts

### Condition 1 — trusted plan only + binding validated — **PASS (with one MEDIUM binding gap)**
- Plan can only come from the injected `TrustedSrlExecutionPlanPort.resolve(task_id)`. `commit_and_start` accepts only `task_id` + optional `TaskConfigurationSnapshotCommand` (sole field `prior_selector`, `task_configuration.py:101`); no `Commitment`/`WorkflowGraph`/`ExpectedOutcome` argument exists, so no caller/organ execution-contract injection surface in the public API. `srl_execution.py:121-152`, `:66-69`.
- `_plan_binds` (`srl_execution.py:229-241`) binds task / commitment.task / commitment.goal / tenant / workspace / workflow tenant+workspace / expected_outcome task+tenant+workspace / capability∈TOOL-node set; the aggregate backstops task/goal/tenant/workspace/evaluator (`task_aggregate.py:468-495`). Probes A4/A6/A7/A8 all fail closed.
- **Gap:** tenant/workspace are bound to the *caller-created goal*, not to the bridge `principal` (`srl_execution.py:229-241`). See Finding F2.

### Condition 2 — pre-reserved run identity + C7 verified before start — **PARTIAL / NOT STRICTLY MET**
- Run identity is the trusted pre-reserved `snapshot.reserved_run_id`, used verbatim as the C7 scope run id (`srl_execution.py:172`) and enforced end-to-end by `TaskService.start_run` (`task_service.py:422`) and `_validate_run_projection_bindings` (`task_aggregate.py:540-545`). No placeholder ids. Probe: run id == reserved (`test_result_run_id_equals_reserved_run_id`).
- C7 is verified with the reserved run id *before* start (`srl_execution.py:179-192`). Mid-window halts of the **task** scope (A3) and the **run** scope (A2) are both blocked → `START_REJECTED`, `COMMITTED`, no run. The config-capability verify→append race is closed by `guard_unchanged` on `snapshot.observed_correction_epochs` (`task_configuration.py:309-314`).
- **NOT met:** a mid-window halt of the **plan's tool capability** (A1) still permits `RUN_STARTED`. CTO condition 2 says *"C7 change between commit and start must forbid the start and leave an auditable COMMITTED state."* The run starts; no COMMITTED state without a run is produced for this scope. See Finding F1.

### Condition 3 — tests are real behavioural falsification — **MOSTLY PASS**
- 10 tests against a real `AgentOSApplication` (SQLite), no constant-return doubles except the plan port. The key invariants are falsifiable: removing the reserved-run-id path breaks `test_result_run_id_equals_reserved_run_id`; removing the C7 verify breaks `test_capability_scope_halt_blocks_start`; removing `_plan_binds` breaks `test_plan_scope_mismatch_fails_closed`. The condition-3 required replacement test ("commit succeeds but start rejected") is present and behavioural (`test_c7_change_before_start_leaves_committed_without_effect`, `:218-233`: committed=True, started=False, COMMITTED, `run is None`).
- Weaknesses: F4 (a mis-named, non-falsifying test) and no committed test for a **run-scope** mid-window halt (only my scratch A2).

### Condition 4 — narrow acceptance boundary — **PASS**
- `srl_execution.py` performs no effect execution, no provider call, no learning, no knowledge-candidate work, and accepts no organ-authored contract. It only delegates to the governed Task/Snapshot services. ✔
- Caveat: the module has **no production wiring** (see F3), so the evidence class is "implemented + unit-tested", not "integrated/verified".

## Findings (severity, file:line)

- **F1 [HIGH] Tool-capability C7 change in the verify→append window does not forbid start; the CTO-condition boundary was self-documented by the builder.** The bridge verifies `plan.capability_id` (`srl_execution.py:179-183`) but the guarded start re-checks only `TASK_CONFIGURATION_CAPABILITY` (`task_configuration.py:309-314`; `halted()` expands to task/run/capability of *that* capability, `governance.py:129-138`). Probe A1: a `correct("capability","workspace.read")` landing inside `start_run` yields `committed=True started=True` and a RUNNING run — violating the literal condition-2 requirement of a COMMITTED state with no run. The re-interpretation to a "defense-in-depth boundary" lives in `cast:85`, which `git log -p` shows was **added by the builder in `9aa9ee17`**, not part of the original CTO gate text. The no-effect invariant *is* preserved at dispatch (`capability.py:154`), so this is not an effect-execution hole, but it needs explicit CTO ratification or code closure.
- **F2 [MEDIUM] `_plan_binds` does not bind the plan to the bridge principal's tenant/workspace, so an out-of-scope plan is committed before it is rejected.** Probe A11: goal created with `tenant_id="tenant:other"` + matching plan → `_plan_binds` passes (anchored to `aggregate.goal`), `commit_task` succeeds (aggregate only checks tenant vs goal, `task_aggregate.py:484-487`), and only `seal` rejects → result `committed=True`, `denial=SNAPSHOT_REJECTED`, task left `COMMITTED` with a foreign-tenant commitment and no run. Two defects: state mutation outside the principal scope, and a misleading denial reason (should be `PLAN_BINDING_MISMATCH` before any mutation).
- **F3 [MEDIUM] No production entry point / integration.** `SrlTaskExecutionBridge` / `TrustedSrlExecutionPlanPort` appear only in `srl_execution.py`, `__init__.py`, and the test file (grep repo-wide). No composition-root wiring, no trusted-port implementation, no real caller. Under AGENTS §14 this is `implemented/tested`, not `integrated/verified`; the review/claim text must not imply more.
- **F4 [LOW] `test_commit_succeeds_but_wrong_scope_is_denied_before_start` is mis-named and non-falsifying.** `test_srl_execution_bridge.py:285-295` asserts `committed is False` / `status is DRAFT` (commit does *not* succeed) and asserts no `denial_reason`; it duplicates the scope check and would still pass if `_plan_binds` were deleted (it would just get `COMMIT_REJECTED` from the aggregate). Condition 3 asks for falsifying tests.
- **F5 [LOW] Cast drift.** `cast:41-45` orders the bridge `seal → verify → commit → re-verify → start`, which is infeasible (`seal` requires a COMMITTED task, `task_configuration.py:525-529`) and contradicts the implemented `commit → seal → verify → start` (`srl_execution.py:98-101`). `cast:52-61` lists test names that no longer exist. The cast is the CTO gate artifact and should match reality.
- **F6 [LOW] Self-issued receipt.** The bridge holds a `C7ReceiptIssuer` and issues the very receipt it then verifies (`srl_execution.py:182-183`). Not a bypass — `issue()` reads live correction state and refuses a halted scope (`c7_receipt.py:79-86`) — but it is a self-attestation pattern; a `CorrectionSnapshotPort` read would be more honest about authority.
- **F7 [LOW] Inconsistent fail-closed envelope.** `seal` failures catch broad `Exception` and map anything to `SNAPSHOT_REJECTED` (`srl_execution.py:159-166`), while `start_run` catches only `AgentOSCoreError` (`:201-208`); a non-core exception after commit propagates, leaving `committed=True` with no typed `ExecutionDenialReason`.

## Bypass / attack attempts and results

| # | Attack | Result |
|---|---|---|
| A1 | Mid-window halt of plan tool capability (`workspace.read`) inside `start_run` | **BYPASS of literal cond. 2**: `committed=True started=True` RUNNING; effect still blocked at dispatch (`capability.py:154`) |
| A2 | Mid-window halt of **run** scope | Blocked → `START_REJECTED`, COMMITTED, no run |
| A3 | Mid-window halt of **task** scope | Blocked → `START_REJECTED`, COMMITTED, no run |
| A4 | `plan.capability_id = TASK_CONFIGURATION_CAPABILITY` | `PLAN_BINDING_MISMATCH` |
| A5 | Commitment missing config authority scope | `SNAPSHOT_REJECTED`, no run |
| A6 | `expected_outcome.task_id` mismatch | `PLAN_BINDING_MISMATCH` |
| A7 | Commitment workspace mismatch | `PLAN_BINDING_MISMATCH` |
| A8 | Workflow TOOL capability without a grant | `SNAPSHOT_REJECTED`, no run |
| A10 | Task pre-committed before bridge | `TASK_NOT_DRAFT` |
| A11 | Cross-tenant goal + plan (bridge principal is local) | **committed=True** `SNAPSHOT_REJECTED`, COMMITTED foreign-tenant task, no run (F2) |

No effect execution, no provider call, no organ-authored contract, and no start bypass for task/run/config scopes were found.

## Required changes

1. Resolve F1: either obtain explicit CTO ratification of the per-capability boundary (recorded in the cast as CTO-accepted, not builder-authored), or close the window by holding a correction guard on `plan.capability_id` across the start append / re-verifying it inside the guarded start.
2. Fix F2: add the bridge principal's tenant/workspace to `_plan_binds` so an out-of-scope plan is denied with `PLAN_BINDING_MISMATCH` before any commit.
3. Reconcile the cast (§2 order, §3 test list, §5 provenance) with the implemented flow (F5).
4. Fix/rename `test_commit_succeeds_but_wrong_scope_is_denied_before_start` and assert the denial reason; add a committed run-scope mid-window halt test (F4).
5. Record the evidence class as implemented/tested, not integrated, until a composition-root wiring + a trusted plan-port implementation exist (F3).

Non-blocking: unify the exception→denial envelope (F7); consider reading a `CorrectionSnapshotPort` instead of self-issuing a receipt (F6).

## Final verdict

**APPROVE_WITH_CHANGES**

- Condition 4 (narrow boundary) and the core of Conditions 1 and 3 are satisfied; Condition 2's run-identity and C7-before-start mechanics are correct and the config/task/run scopes are race-safe.
- Blocking-on-promotion: F1 requires CTO ratification or closure (literal condition 2 is not met for a tool-capability mid-window halt); F2 is a real out-of-principal-scope commit; F3/F5 are claim/evidence-integrity issues.
- **Independence limitation: reviewer == builder model. This is not the G6 cross-provider approval.**
