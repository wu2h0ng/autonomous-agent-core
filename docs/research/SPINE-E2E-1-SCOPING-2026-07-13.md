# SPINE-E2E-1 — Scoping (Gate-P instrument for the B1 sandbox)

> Date: 2026-07-13 · Track: product_eval · Status: `SCOPING / NOT_PREREGISTERED / NOT_RUN`
> Authority: `docs/research/AGENT-OS-PRODUCT-GROUNDED-EXPERIMENT-MATRIX.yaml` (SPINE-E2E-1), `../../docs/research/founder-decision-2026-07-13-reopen-b1-sandbox-only.md` (Gate P)
> Role here: SPINE-E2E-1 is the **Gate P** ("SPINE product pull") instrument for the bounded B1 reopen. It runs in **parallel** to the B1-0 sandbox line and is physically separate from it.

## 1. Status correction (Freshness Gate)

The matrix records SPINE-E2E-1 as `BLOCKED_UNTIL_T_P_OS_SPINE_0_IMPLEMENTED`. **That dependency label is stale.** `CURRENT_STATE.yaml` records SPINE-0 as `SPINE_0_IMPLEMENTED_AND_PM_ACCEPTED_LOCAL` (canonical contracts, durable event store, leases, idempotency, recovery, evaluator, API/CLI/Task Workspace), so the SPINE-0 prerequisite is satisfied.

This does **not** mean SPINE-E2E-1 is operationally ready to run. The task-local source of execution truth, `.agent_runs/spine-e2e-1-20260712/status.md`, currently records `PLAN_AND_INSTRUMENT_REVISION / NOT_FROZEN / NOT_STARTED`; its Task 1 time-attestation and live-runtime contract remain `REVISE`, with Tasks 2–5 paused pending revised-plan/artifact-kernel review. The matrix `authorization_boundary` (`run: false`) also holds until preregistration. Therefore the accurate state is: `PREREQUISITE_UNBLOCKED / EXECUTION_NOT_READY / NOT_PREREGISTERED / NOT_RUN`.

## 2. What already exists vs. what the experiment adds

The real end-to-end path is implemented and tested in `tests/product/test_spine0_golden_path.py`:
`AgentOSApplication.create_task → commit_task(commitment + WorkflowGraph + ExpectedOutcome) → run_task(stop_after_node) → WorkerInterrupted → recover_stale_lease → WAITING_APPROVAL → record_approval → run_task → COMPLETED + ObservedOutcome=VERIFIED`, with a durable SQLite event store, `IdempotencyMode` on TOOL nodes, restart-survival across new service instances, zero file effects on malformed provider output, and retry-never-duplicates.

That test proves the *mechanism*. SPINE-E2E-1 as an **experiment** adds, on top of it:

1. **Baselines** (matrix): (a) direct model-plus-tools run without the durable spine; (b) single-process non-resumable workflow. Both must run the same tasks so the spine's value is *measured*, not asserted.
2. **A metric sweep, not a single assertion**, over a small held-out task set with injected failures (worker kill, provider timeout/malformed, stale lease), producing the four primary metrics: `verified_outcome_success_rate`, `duplicate_side_effect_count`, `rehydrated_state_equivalence`, `human_intervention_minutes`.
3. **Pass-gate adjudication** (matrix): every accepted outcome resolves to an `ExpectedOutcome` evaluator + evidence refs; zero duplicate side effects under retry/restart; rehydrated run reaches the same terminal state. Kill/revise if any success is producible without the ActionContract/policy path, or a restart replays a committed side effect.

## 3. The Gate-P measurement — and an honest limit

Gate P must answer: *is multi-organ orchestration a real latency/cost/consistency bottleneck?* — the PARK's own "measured product bottleneck" reopen trigger.

**Honest limit:** SPINE-0's golden path has **one** `PROVIDER` node (`provider.chat`). A single-organ path **cannot** exhibit a multi-organ orchestration bottleneck. So SPINE-E2E-1 as specified measures **durable-spine value**, not multi-organ cost. It establishes the *instrument and the baselines*; the Gate-P orchestration-cost signal requires a **multi-organ variant** (≥2 distinct model/organ calls in the workflow — e.g., a plan organ + a verify organ, or the `LH-RECOVERY-1` long-horizon path) measuring per-outcome `model_calls`, `p50/p95 latency`, `cost`, and planner-verifier `consistency`.

**Therefore Gate P is a two-step measurement:**
- **P-a (SPINE-E2E-1):** durable spine works and the metric instrument + baselines exist. Its SPINE-0 dependency is satisfied, but its current plan/instrument blockers and preregistration gate remain open.
- **P-b (multi-organ variant):** on a ≥2-organ workflow, orchestration cost is measured against a unified-call alternative. This is what actually qualifies (or falsifies) the B1 architecture-cost hypothesis. Do **not** report P-a alone as satisfying Gate P.

## 4. Build boundary

- product_eval touching product runtime ⇒ **feature branch + PR**, not direct-to-main (CLAUDE Git Finalization Gate). The harness reuses `AgentOSApplication` and the canonical contracts; it must not add domain semantics to core, and it binds a real `ProductFailureRef` + current-product baseline (matrix global_rules).
- Physically separate from the B1 sandbox (`sandbox/unified_agent_model/`); no data flows between them. SPINE-E2E-1 measures the product; the sandbox measures the model. They meet only at the Gate-P/Gate-R decision, never in code or data.

## 5. Next action

First close the task-local Task 1 `REVISE` items and obtain independent acceptance of the revised plan/artifact kernel. Then preregister SPINE-E2E-1 P-a (task set, injected-failure schedule, baselines, effect floors, evaluator version) before any result-bearing run, and implement the measurement harness on a feature branch reusing the golden-path scaffolding. Scope P-b (multi-organ variant) as a separate product-eval packet and the actual Gate-P qualifier once P-a lands; P-a does not authorize or imply P-b.
