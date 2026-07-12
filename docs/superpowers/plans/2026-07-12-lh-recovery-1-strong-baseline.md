# LH-RECOVERY-1 Strong-Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a machine-verifiable fresh SPINE-E2E-1 PASS, preregister, freeze, and run a real multi-hour 180-pair evaluation of bounded explicit replanning against the strongest matched fixed-DAG, checkpoint-only, and restart-from-scratch baselines.

**Architecture:** Reuse the frozen common artifact/provider infrastructure and add four isolated public-surface arms per paired case. All arms receive the same frozen tasks, requirement changes, response bank, evaluator, retry/tool/provider budget, process restarts, and execution-order counterbalancing. `prepare`, `resume-change`, `resume-recovery`, and `adjudicate` are separate processes; r-final requires at least 7,560 real seconds from prepare to final recovery and a 360-second stale-lease window.

**Tech Stack:** Python 3.11+, stdlib statistics/math/json/hashlib, existing Agent OS Product contracts/runtime, local OpenAI-compatible frozen response bank, pytest 9, Ruff, Pyright, fixed workflow runner commit `0c87fb3`.

## Global Constraints

- Track is `translational_research`; claim class is `research-environment`; tested runtime remains Product Track.
- Final LH spec cannot freeze until it binds the fresh SPINE run ID, lock SHA-256, result SHA-256, and verdict `PASS`.
- Candidate is durable execution plus exactly one explicit Principal-authorized replan. It is not automatic hierarchical planning, continual learning, or autonomous self-modification.
- Strongest baseline is the same durable spine with a predeclared refresh suffix and `max_replans=0`. It receives the same two reads, two provider calls, two approvals, one apply, one pytest/evaluation, process restarts, tokens, tool budget, and context as the candidate.
- Other baselines are last-checkpoint replay without plan revision and restart-from-scratch through the same public Agent OS surface.
- Frozen response replay isolates runtime recovery; it does not prove live-model reliability. Monetary cost is `unavailable`; report tokens/tool calls and frozen cost units.
- Held-out set is 30 task templates × 3 failure schedules × 2 counterbalanced arm orders = 180 paired cases, 720 arm episodes.
- Real timing gates: prepare-to-change at least 7,200 seconds; post-apply interruption-to-recovery at least 360 seconds; prepare-to-final at least 7,560 seconds.
- Any severe policy/C7 violation, corpus/provider/evaluator/spec drift, missing arm/case, budget mismatch, private-runtime harness access, or timing shortfall makes the run `INVALID`.
- Complete but non-winning evidence is `NOT_MET`; do not rerun, retune, drop cases, or weaken the strongest baseline to rescue it.

---

## File Structure

- `product_evals/lh_recovery_1/__init__.py`: package marker.
- `product_evals/lh_recovery_1/protocol.py`: case expansion, four workflows, phase execution, metrics, exact test statistic, adjudicator.
- `product_evals/lh_recovery_1/cli.py`: four fresh-process commands.
- `product_evals/lh_recovery_1/frozen_tasks.json`: 30 held-out templates.
- `product_evals/lh_recovery_1/failure_schedule.json`: 180 immutable paired case assignments and two arm orders.
- `product_evals/lh_recovery_1/provider_responses.json`: v1/v2/restart exact prompt bank.
- `tests/product_eval/test_lh_protocol.py`: arm parity, failure injection, metrics, adjudication.
- `tests/product_eval/test_lh_cli.py`: phase/timing/integrity guards.
- `docs/research/LH-RECOVERY-1-preregistration-spec.yaml`: final SPINE-bound preregistration.
- `.agent_runs/lh-recovery-1-20260712/evaluation/*`: mutable phase/raw/result artifacts.

### Task 1: Freeze 30 Tasks, 180 Assignments, and Provider Responses

**Files:**
- Create: `product_evals/lh_recovery_1/__init__.py`
- Create: `product_evals/lh_recovery_1/frozen_tasks.json`
- Create: `product_evals/lh_recovery_1/failure_schedule.json`
- Create: `product_evals/lh_recovery_1/provider_responses.json`
- Test: `tests/product_eval/test_lh_protocol.py`

**Interfaces:**
- Consumes: common frozen artifact/provider helpers.
- Produces: `load_task_templates() -> tuple[TaskTemplate, ...]` and `expand_schedule() -> tuple[PairedCase, ...]`.

- [ ] **Step 1: Write corpus cardinality and parity tests**

```python
def test_frozen_schedule_has_180_unique_pairs() -> None:
    pairs = expand_schedule()
    assert len(pairs) == 180
    assert len({pair.pair_id for pair in pairs}) == 180
    assert Counter(pair.failure_mode for pair in pairs) == {
        "pre_change_process_restart": 60,
        "post_apply_worker_interrupt": 60,
        "correction_halt_before_apply": 60,
    }
    assert Counter(pair.order_id for pair in pairs) == {"A": 90, "B": 90}


def test_every_task_has_v1_v2_and_restart_frozen_prompts() -> None:
    bank = load_bank()
    assert all(template.required_prompt_digests <= bank.keys() for template in load_task_templates())
```

- [ ] **Step 2: Run RED**

Run: `uv run --extra product-test pytest tests/product_eval/test_lh_protocol.py -q`

Expected: missing LH package.

- [ ] **Step 3: Create the exact corpus**

Use six families with five tasks each: `string_transform`, `numeric_reducer`, `validator`, `formatter`, `record_filter`, and `small_state_machine`. Each template freezes:

```json
{
  "task_id": "lh-string-01",
  "family": "string_transform",
  "target_path": "subject.py",
  "goal_v1": "...",
  "goal_v2": "...",
  "initial_content": "...",
  "environment_changed_content": "...",
  "patched_v2_content": "...",
  "pytest_source": "..."
}
```

Order A is `candidate,fixed_dag,checkpoint,restart_scratch`; order B is the exact reverse. The schedule JSON, not runtime code, assigns all 180 pair IDs.

- [ ] **Step 4: Run tests and commit**

Run: `uv run --extra product-test pytest tests/product_eval/test_lh_protocol.py -q`

Expected: cardinality, balance, and prompt coverage tests pass.

```bash
git add product_evals/lh_recovery_1 tests/product_eval/test_lh_protocol.py
git commit -m "test(product-eval): freeze LH held-out schedule"
```

### Task 2: Four Matched Public-Surface Arms

**Files:**
- Create: `product_evals/lh_recovery_1/protocol.py`
- Modify: `tests/product_eval/test_lh_protocol.py`

**Interfaces:**
- Consumes: `PairedCase`, `AgentOSApplication`, and common provider server.
- Produces: `candidate_v1`, `candidate_v2`, `fixed_dag`, `checkpoint_graph`, `restart_graph`, and `prepare_pair(config: LHConfig, pair: PairedCase) -> PairState`.

- [ ] **Step 1: Write graph and budget parity tests**

```python
def test_strongest_fixed_dag_has_matched_refresh_budget() -> None:
    candidate = arm_budget(candidate_v1(), candidate_v2())
    fixed = arm_budget(fixed_dag())
    assert candidate == fixed == {
        "read": 2,
        "provider": 2,
        "approval": 2,
        "apply": 1,
        "tests": 1,
        "evaluate": 1,
    }
    assert candidate_v1().max_replans == 1
    assert fixed_dag().max_replans == 0


def test_protocol_source_uses_only_public_application_surface() -> None:
    forbidden = {"store", "tasks", "sandbox", "provider", "provider_configured"}
    assert not forbidden_attributes(Path("product_evals/lh_recovery_1/protocol.py"), forbidden)
```

- [ ] **Step 2: Run RED**

Run: `uv run --extra product-test pytest tests/product_eval/test_lh_protocol.py -q`

Expected: missing graph functions.

- [ ] **Step 3: Implement exact workflows**

Candidate v1:

```text
read_v1 -> provider_v1 -> approve_v1 -> wait_change -> stale_suffix
```

Candidate v2 preserves the completed prefix and replaces only the suffix:

```text
read_v1 -> provider_v1 -> approve_v1 -> wait_change
-> read_v2 -> provider_v2 -> approve_v2 -> apply_v2 -> tests_v2 -> evaluate_v2 -> done_v2
```

Strong fixed DAG predeclares the same full path from the start and never calls `replan_task`. Checkpoint keeps only the stale v1 suffix and must fail the bound `expected_sha256` after the environment change. Restart-scratch preserves episode 1 as evidence, creates a new episode-2 DB/task from the changed workspace, and charges `TASK_RECREATE`.

All workspaces and SQLite files are isolated by `pair_id/arm`; no arm shares mutable state.

- [ ] **Step 4: Run tests and commit**

Run: `uv run --extra product-test pytest tests/product_eval/test_lh_protocol.py -q`

Expected: graph parity and AST boundary tests pass.

```bash
git add product_evals/lh_recovery_1/protocol.py tests/product_eval/test_lh_protocol.py
git commit -m "feat(product-eval): add four matched LH arms"
```

### Task 3: Four Real-Time Process Phases and Frozen Failures

**Files:**
- Modify: `product_evals/lh_recovery_1/protocol.py`
- Create: `product_evals/lh_recovery_1/cli.py`
- Create: `tests/product_eval/test_lh_cli.py`

**Interfaces:**
- Consumes: evaluation root, frozen hashes, target HEAD, and current UTC.
- Produces: `prepare`, `resume-change`, `resume-recovery`, and `adjudicate` commands.

- [ ] **Step 1: Write timing and phase replay tests**

```python
def test_change_before_7200_real_seconds_is_denied(tmp_path: Path) -> None:
    state = frozen_prepared_state(tmp_path, prepared_at="2026-07-12T00:00:00Z")
    result = run_lh_cli("resume-change", state, now="2026-07-12T01:59:59Z")
    assert result.returncode == 2


def test_recovery_before_360_seconds_is_denied(tmp_path: Path) -> None:
    state = frozen_changed_state(tmp_path, interrupted_at="2026-07-12T02:00:00Z")
    result = run_lh_cli("resume-recovery", state, now="2026-07-12T02:05:59Z")
    assert result.returncode == 2


def test_replaying_completed_phase_is_denied_without_mutation(tmp_path: Path) -> None:
    before = tree_digest(tmp_path)
    assert run_lh_cli("resume-change", completed_change_state(tmp_path)).returncode == 2
    assert tree_digest(tmp_path) == before
```

- [ ] **Step 2: Run RED and implement phase CLI**

Run: `uv run --extra product-test pytest tests/product_eval/test_lh_cli.py -q`

Expected before implementation: missing CLI. Expected after implementation: all guards pass.

Phase behavior is fixed:

1. `prepare`: all 720 arms reach their frozen wait/checkpoint; process exits.
2. after 7,200 real seconds, `resume-change`: apply the identical environment change, signal each task exactly twice to test idempotency, perform the candidate's one Principal replan, advance fixed/checkpoint/restart arms according to their frozen definitions, and inject the assigned failure mode.
3. after at least 360 more real seconds, `resume-recovery`: recover stale leases in fresh application processes, explicitly resume correction only in correction cases, and finish all recoverable arms.
4. `adjudicate`: require at least 7,560 total seconds and all phase-ledger entries.

- [ ] **Step 3: Add failure-injection assertions**

```python
def test_candidate_has_exactly_one_rebound_and_fixed_has_zero() -> None:
    raw = completed_pair_raw()
    assert raw["candidate"]["run_plan_rebound_count"] == 1
    assert raw["fixed_dag"]["run_plan_rebound_count"] == 0


def test_correction_halt_has_zero_post_halt_apply_receipts() -> None:
    raw = correction_case_raw()
    assert raw["post_halt_apply_receipts_before_principal_resume"] == 0
```

- [ ] **Step 4: Run tests and commit**

Run: `uv run --extra product-test pytest tests/product_eval/test_lh_cli.py tests/product_eval/test_lh_protocol.py -q`

Expected: all phase, failure, replay, and correction tests pass in explicit short-timing test mode.

```bash
git add product_evals/lh_recovery_1 tests/product_eval/test_lh_cli.py tests/product_eval/test_lh_protocol.py
git commit -m "feat(product-eval): add real-time LH phase protocol"
```

### Task 4: Metrics, Strongest-Baseline Selection, and Exact Adjudication

**Files:**
- Modify: `product_evals/lh_recovery_1/protocol.py`
- Modify: `tests/product_eval/test_lh_protocol.py`

**Interfaces:**
- Consumes: 180 complete pair results.
- Produces: `adjudicate_lh(raw: dict[str, object]) -> LHResult`.

- [ ] **Step 1: Write strong-baseline and verdict tests**

```python
def test_adjudicator_compares_against_single_strongest_baseline() -> None:
    raw = synthetic_raw(candidate=.92, fixed=.91, checkpoint=.40, restart=.50)
    result = adjudicate_lh(raw)
    assert result.strongest_baseline == "fixed_dag"
    assert result.verdict == "NOT_MET"


def test_timing_or_budget_mismatch_is_invalid() -> None:
    raw = valid_synthetic_raw()
    raw["elapsed_seconds"] = 7559
    assert adjudicate_lh(raw).verdict == "INVALID"


def test_fixed_dag_tie_reports_schedule_reduction() -> None:
    raw = synthetic_raw(candidate=.95, fixed=.95, checkpoint=.30, restart=.50)
    result = adjudicate_lh(raw)
    assert result.verdict == "NOT_MET"
    assert result.explanation_code == "REDUCES_TO_SCHEDULE_ENGINEERING_WITHIN_FROZEN_ENVELOPE"
```

- [ ] **Step 2: Run RED**

Run: `uv run --extra product-test pytest tests/product_eval/test_lh_protocol.py -q`

Expected: missing adjudicator.

- [ ] **Step 3: Implement exact frozen metrics and floors**

Report per arm:

- accepted outcome success rate;
- recovery rate after injected failure;
- duplicate/noncontributing work ratio;
- logical duplicate side-effect count;
- approval/replan/task-recreate/correction-resume action counts;
- charged human minutes using `APPROVAL=0.5`, `REPLAN=2.0`, `TASK_RECREATE=2.0`, `CORRECTION_RESUME=1.0`;
- wall seconds, provider tokens, and tool calls;
- severe policy/correction violations.

`MET` requires all of:

```python
candidate_success >= 0.90
candidate_recovery >= 0.90
candidate_success - strongest_success >= 0.12
candidate_recovery - strongest_recovery >= 0.12
paired_exact_binomial_p < 0.05
candidate_duplicate_work <= strongest_duplicate_work - 0.20
candidate_human_minutes <= strongest_human_minutes
candidate_cost_units <= strongest_cost_units * 1.10
severe_policy_or_correction_violations == 0
```

Use a stdlib exact two-sided binomial test over discordant paired outcomes; do not add SciPy. If all artifacts are intact but any floor fails, verdict is `NOT_MET`. If fixed DAG ties/wins while candidate spends a replan, use `REDUCES_TO_SCHEDULE_ENGINEERING_WITHIN_FROZEN_ENVELOPE`.

- [ ] **Step 4: Run tests and commit**

Run: `uv run --extra product-test pytest tests/product_eval/test_lh_protocol.py -q`

Expected: strongest-baseline, floor, tie, and invalidity tests pass.

```bash
git add product_evals/lh_recovery_1/protocol.py tests/product_eval/test_lh_protocol.py
git commit -m "feat(product-eval): add frozen LH adjudication"
```

### Task 5: SPINE-Bound Preregistration, Freeze, Real Run, and Truth Update

**Files:**
- Create after SPINE PASS: `docs/research/LH-RECOVERY-1-preregistration-spec.yaml`
- Create after run: `docs/research/LH-RECOVERY-1-result.md`
- Modify after adjudication: `docs/CURRENT_STATE.yaml`
- Modify after adjudication: `codebase_index.md`

**Interfaces:**
- Consumes: fresh SPINE lock/result hashes and the complete LH implementation.
- Produces: one immutable prereg lock and one bounded `MET`, `NOT_MET`, or `INVALID` result.

- [ ] **Step 1: Write the final preregistration only after SPINE PASS**

The spec must bind exact values for:

- SPINE run ID, `prereg.lock` SHA-256, `result.json` SHA-256, and `PASS` verdict;
- 30-task, 180-pair schedule digest;
- provider bank/evaluator/failure schedule digests;
- four arms and exact matched budget table;
- 7,200/360/7,560 real-time gates;
- every metric, effect floor, invalidity rule, and maximum claim;
- all Product runtime/contracts plus LH/common harness files in `mechanism.files`;
- `builder_id: claude-builder` and explicit review identities.

- [ ] **Step 2: Commit a clean exact freeze candidate**

```bash
git add product_evals tests/product_eval docs/research/LH-RECOVERY-1-preregistration-spec.yaml
git commit -m "test(product-eval): preregister LH-RECOVERY-1"
git status --porcelain
```

Expected: clean output.

- [ ] **Step 3: Complete calibrated content/architecture review and freeze**

Use the fixed workflow runner branch and the independent `lh-independent-reviewer` RR-0031 chain. Bind the exact-content manifest and architecture packet, then run:

```text
prereg manifest-verify
-> prereg review --builder-id claude-builder --reviewed-by opencode-content-reviewer --verdict accept
-> prereg architecture-review --reviewed-by lh-independent-reviewer --verdict accept
-> prereg freeze --frozen-by codex-cto
```

Any mismatch stops the run. Record lock and canonical prereg hashes immediately.

- [ ] **Step 4: Start the real long-duration process**

Run `prepare` in a persistent terminal session, record its process exit and hashes, then keep the phase ledger untouched for at least 7,200 real seconds. Run `resume-change`, wait the frozen 360 seconds, run `resume-recovery`, and finally `adjudicate`. Poll the persistent process at intervals no longer than 60 seconds; do not replace real time with sleep mocks.

- [ ] **Step 5: Verify and independently adjudicate**

Run workflow-runner `prereg verify --result` before changing tracked docs. An independent reviewer checks strongest-baseline selection, timing, case completeness, budgets, policy/C7 events, and result hashes. Preserve `NOT_MET` or `INVALID` exactly as emitted.

- [ ] **Step 6: Update truth without overclaim**

Create `docs/research/LH-RECOVERY-1-result.md`, update `docs/CURRENT_STATE.yaml` and `codebase_index.md`, and state only the frozen bounded result. Commit the documentation separately from the frozen implementation.

```bash
git add docs/research/LH-RECOVERY-1-result.md docs/CURRENT_STATE.yaml codebase_index.md
git commit -m "docs(product-eval): record LH-RECOVERY-1 result"
```

