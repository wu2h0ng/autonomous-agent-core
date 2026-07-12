# Agent OS E0/E1/E2 Long-Horizon Convergence Implementation Plan

> **Founder ownership amendment (2026-07-12):** Codex owns architecture, engineering
> governance, primary review and final verification. Claude Code is the primary writer for
> important acceptance/runtime integration work. OpenCode, Kimi and Cursor may implement
> bounded simple-code/test/research slices in separate worktrees with non-overlapping file
> scopes. Every behavior still observes RED before production edits. Claude/Cursor lanes are
> reported blocked, never silently substituted, when their authenticated CLI is unavailable.

**Goal:** Extend the verified SPINE-0 Product Track with one bounded, durable long-horizon
vertical: typed external signals, wait/commitment deadlines, dependency blocking, one
human-authorized workflow rebind, restart-safe patch compensation, and an event-derived
recovery projection.

**Architecture:** Preserve the current modular monolith and append-only Task aggregate.
`TaskEvent` remains the only signal/replan/compensation truth. API and CLI call the same
`AgentOSApplication -> TaskService/RunCoordinator` path. Replanning replaces only the
uncompleted suffix with a validated immutable `WorkflowGraph` version; no LLM or provider
receives rebind authority. Compensation is a typed internal capability and still crosses
PolicyKernel, permit, broker and receipt gates.

**Tech stack:** Python 3.12, Pydantic 2, SQLite, pytest, Ruff, Pyright, stdlib HTTP/CLI.

## Fixed constraints

- Worktree: `autonomous-agent-core/.worktrees/agent-os-e2e-long-horizon-20260712`
- Branch: `codex/agent-os-e2e-long-horizon-20260712`
- Baseline: `065ff8b`; `96 passed, 1 skipped`; Ruff/Pyright clean.
- Do not modify `src/aac`, `experiments`, SPINE-1 migration state or Research Track verdicts.
- Do not add a signal table, scheduler service, external framework, automatic LLM replan,
  general shell or cross-system rollback claim.
- A Commitment deadline is immutable. No extend-deadline endpoint.
- Only `workspace.apply_patch` receives automatic compensation in this slice.
- C7 halt blocks automatic compensation as well as ordinary dispatch. Only an external
  principal may resume the correction epoch and then request explicit governed compensation.
- A durable snapshot must complete before a patch writes the target file.
- `LH-RECOVERY-1` is not run or adjudicated by this plan.
- After each task: targeted test, full `tests/product`, Ruff, Pyright, then a scoped commit.

## Task 0: Preserve the verified E0 baseline

**State:** completed before implementation.

- [x] Created `codex/spine0-convergence-checkpoint-20260712`.
- [x] Excluded all `experiments/` changes and `.DS_Store`.
- [x] Re-ran product pytest, Ruff and Pyright.
- [x] Committed `065ff8b feat(product): checkpoint Agent OS SPINE-0 runtime`.
- [x] Created clean feature worktree and re-ran the same baseline checks.

---

## Task 1: Freeze long-horizon contracts and honest capability guarantees

**Files:**

- Create: `tests/product/test_long_horizon_contracts.py`
- Modify: `tests/product/test_authority_contracts.py`
- Modify: `packages/contracts/src/agent_os_contracts/workflow.py`
- Modify: `packages/contracts/src/agent_os_contracts/runtime.py`
- Modify: `packages/contracts/src/agent_os_contracts/capability.py`
- Modify: `packages/contracts/src/agent_os_contracts/__init__.py`
- Modify: `packages/os_core/src/agent_os_core/capability.py`

### Step 1.1 — write contract RED tests

Add tests equivalent to:

```python
def test_wait_event_requires_signal_name_and_correlation_key():
    with pytest.raises(ValidationError, match="wait_event"):
        NodeSpec(node_id="wait", kind=NodeKind.WAIT_EVENT)

def test_non_wait_node_rejects_wait_binding():
    with pytest.raises(ValidationError, match="only for wait_event"):
        NodeSpec(
            node_id="done", kind=NodeKind.TERMINAL,
            wait_signal_name="build.finished", wait_correlation_key="build:7",
        )

def test_external_signal_canonicalizes_object_payload(now):
    signal = ExternalSignal(..., payload_json='{ "ok": true }', occurred_at=now)
    assert signal.payload_json == '{"ok":true}'

def test_workflow_replan_budget_is_bounded(workflow_factory):
    with pytest.raises(ValidationError):
        workflow_factory(max_replans=4)

def test_sandbox_idempotent_does_not_claim_compensation(now):
    spec = CapabilitySpec(..., side_effect_guarantee=SideEffectGuarantee.SANDBOX_IDEMPOTENT,
                          idempotency_supported=True, cancellation_supported=True,
                          compensation_supported=False, created_at=now)
    assert not spec.compensation_supported
```

Run:

```bash
uv run --extra product-test pytest \
  tests/product/test_long_horizon_contracts.py \
  tests/product/test_authority_contracts.py -q
```

Expected RED: missing enum/contracts/fields.

### Step 1.2 — implement the minimal contracts

In `workflow.py`:

```python
class NodeSpec(ContractModel):
    ...
    wait_signal_name: NonEmptyStr | None = None
    wait_correlation_key: NonEmptyStr | None = None

class WorkflowGraph(ContractModel):
    ...
    max_replans: int = Field(default=1, ge=0, le=3)
```

Extend the model validator so exactly WAIT_EVENT owns both wait fields.

In `runtime.py`, add immutable `WaitCondition`, `ExternalSignal`, `RunPlanRebound` and
`RunRecoverySnapshot`; add `AgentRun.wait_condition` and `AgentRun.replan_count`; add the
event enum values frozen in the design.

In `capability.py`, add `SideEffectGuarantee.SANDBOX_IDEMPOTENT` and validate that it
requires idempotency + cancellation but does not require compensation. Change
`workspace.run_tests` and `artifact.write` specs to that guarantee; only
`workspace.apply_patch` remains `SANDBOX_COMPENSATABLE`.

### Step 1.3 — run GREEN and regression checks

```bash
uv run --extra product-test pytest \
  tests/product/test_long_horizon_contracts.py \
  tests/product/test_authority_contracts.py \
  tests/product/test_workflow_graph.py -q
uv run --extra product-test pytest tests/product -q
uv run --extra product-test ruff check packages tests/product
uv run --extra product-test pyright packages tests/product
```

### Step 1.4 — commit

```bash
git add packages/contracts packages/os_core/src/agent_os_core/capability.py \
  tests/product/test_long_horizon_contracts.py tests/product/test_authority_contracts.py
git commit -m "feat(product): add bounded long-horizon contracts"
```

---

## Task 2: Add event-sourced wait, signal, deadline and workflow rebind commands

**Files:**

- Create: `tests/product/test_long_horizon_task_service.py`
- Modify: `packages/os_core/src/agent_os_core/task_service.py`
- Modify: `packages/os_core/src/agent_os_core/task_aggregate.py`
- Modify: `packages/os_core/src/agent_os_core/errors.py`
- Modify: `packages/os_core/src/agent_os_core/__init__.py`

### Step 2.1 — write TaskService RED tests

Cover:

```python
def test_register_wait_sets_task_and_run_waiting(...):
    result = service.register_wait(task_id, wait_node)
    assert result.status is TaskStatus.WAITING
    assert result.run.status is RunStatus.WAITING_EVENT

def test_record_signal_atomically_satisfies_wait_and_completes_node(...):
    result = service.record_signal(task_id, matching_signal)
    types = [event.event_type for event in store.read(task_id)][-3:]
    assert types == [EXTERNAL_SIGNAL_RECORDED, WAIT_SATISFIED, NODE_COMPLETED]
    assert result.run.wait_condition is None

def test_duplicate_signal_is_idempotent(...):
    first = service.record_signal(task_id, signal)
    second = service.record_signal(task_id, signal)
    assert second.sequence == first.sequence

def test_wrong_or_late_signal_persists_no_success(...): ...
def test_expired_commitment_cannot_start(...): ...
def test_replan_rejects_completed_node_change_and_budget_increase(...): ...
def test_replan_rebinds_only_uncompleted_suffix(...): ...
```

Run:

```bash
uv run --extra product-test pytest tests/product/test_long_horizon_task_service.py -q
```

Expected RED: TaskService methods/events do not exist.

### Step 2.2 — implement event batches and aggregate replay

Add a private TaskService batch helper that builds causally chained `TaskEventDraft`s and
uses one store append with the current sequence. Implement:

```python
register_wait(task_id, node) -> TaskAggregate
record_signal(task_id, signal) -> TaskAggregate
expire_wait(task_id, reason="wait deadline exceeded") -> TaskAggregate
expire_commitment(task_id) -> TaskAggregate
replan_task(task_id, workflow, requested_by, reason) -> TaskAggregate
now() -> datetime
```

`record_signal` checks existing `signal_id` before current run status so exact retries remain
idempotent after satisfaction. A concurrent sequence failure must re-read and classify the
request as duplicate or conflict; it must not blindly retry a second completion.

`replan_task` computes `RunPlanRebound`, clears approval/wait, increments `replan_count`,
and writes one `RUN_PLAN_REBOUND` event containing the new workflow and updated run.

Update `TaskAggregate._apply()` explicitly for every new event. Never put new events in a
generic ignored set. `RUN_PLAN_REBOUND` replaces the current workflow/run projection but
does not erase any historical field or event.

### Step 2.3 — run GREEN and regression checks

```bash
uv run --extra product-test pytest \
  tests/product/test_long_horizon_task_service.py \
  tests/product/test_task_service.py \
  tests/product/test_task_aggregate.py \
  tests/product/test_event_store.py -q
uv run --extra product-test pytest tests/product -q
uv run --extra product-test ruff check packages tests/product
uv run --extra product-test pyright packages tests/product
```

### Step 2.4 — commit

```bash
git add packages/os_core/src/agent_os_core tests/product/test_long_horizon_task_service.py
git commit -m "feat(product): persist wait signals and bounded replans"
```

---

## Task 3: Consume waits and rebinds in the durable coordinator

**Files:**

- Create: `tests/product/test_long_horizon_execution.py`
- Modify: `packages/os_core/src/agent_os_core/execution.py`

### Step 3.1 — write coordinator RED tests

```python
def test_run_stops_at_wait_and_does_not_execute_downstream(...): ...
def test_run_while_still_waiting_is_a_noop(...): ...
def test_matching_signal_then_new_process_resumes_from_completed_wait(...): ...
def test_wait_timeout_fails_without_downstream_action(...): ...
def test_rebind_drops_invalidated_provider_action_and_approval(...): ...
```

Assert exact event counts and file contents, not only statuses.

Run:

```bash
uv run --extra product-test pytest tests/product/test_long_horizon_execution.py -q
```

Expected RED: current WAIT_EVENT can be bypassed by generic resume and has no typed signal.

### Step 3.2 — implement coordinator behavior

- After lease acquisition, if the run is still WAITING_EVENT and deadline is live, release
  the lease and return unchanged.
- If wait/Commitment is expired, append the typed failure and release the lease.
- Replace the current WAIT_EVENT branch with `TaskService.register_wait()`.
- On signal satisfaction, `NODE_COMPLETED` already exists; normal `_completed_nodes()` skips
  the wait and continues through the DAG.
- Process `RUN_PLAN_REBOUND` while restoring context and delete invalidated node outputs,
  provider proposals, action contexts and approvals from the executable projection.
- Keep LOOP/PARALLEL_MAP/SUBWORKFLOW explicitly unsupported.

### Step 3.3 — run GREEN and commit

```bash
uv run --extra product-test pytest \
  tests/product/test_long_horizon_execution.py \
  tests/product/test_spine0_golden_path.py -q
uv run --extra product-test pytest tests/product -q
uv run --extra product-test ruff check packages tests/product
uv run --extra product-test pyright packages tests/product
git add packages/os_core/src/agent_os_core/execution.py \
  tests/product/test_long_horizon_execution.py
git commit -m "feat(product): execute durable wait and rebind states"
```

---

## Task 4: Make patch compensation durable, governed and restart-safe

**Files:**

- Create: `tests/product/test_long_horizon_compensation.py`
- Modify: `tests/product/test_spine0_security_and_persistence.py`
- Modify: `tests/product/test_authority_contracts.py`
- Modify: `packages/contracts/src/agent_os_contracts/runtime.py`
- Modify: `packages/contracts/src/agent_os_contracts/__init__.py`
- Modify: `packages/os_core/src/agent_os_core/capability.py`
- Modify: `packages/os_core/src/agent_os_core/execution.py`
- Modify: `packages/os_core/src/agent_os_core/governance.py`
- Modify: `packages/os_core/src/agent_os_core/persistence.py`
- Modify: `packages/os_core/src/agent_os_core/postgres.py`
- Modify: `packages/os_core/src/agent_os_core/task_aggregate.py`
- Modify: `apps/api_server/app.py`

The first read-only compensation audit found that restart-safe snapshots alone would still
overclaim governed compensation: persistent C7 state can be stale across processes, correction
epoch writes are not atomic, the connector does not recheck halt/permit expiry, and an internal
compensation capability would otherwise receive an ordinary application grant. Task 4 is split
into three independently testable gates; no coordinator compensation claim is allowed until all
three are green.

### Step 4.1 — harden the correction authority and final execution boundary (RED first)

Add tests proving:

```python
def test_second_authority_observes_external_halt_without_restart(...): ...
def test_concurrent_correction_advances_are_monotonic(...): ...
def test_connector_rejects_expired_permit_before_idempotency_replay(...): ...
def test_connector_rejects_halt_between_permit_and_dispatch(...): ...
def test_forged_current_epoch_permit_cannot_bypass_halt(...): ...
```

Implement a persistence port method `advance_correction(...) -> tuple[int, bool, str]` as one
transaction (`BEGIN IMMEDIATE` for SQLite; row lock/upsert for PostgreSQL). A persisted
`CorrectionAuthority` reads live state for every snapshot/halt check and uses the atomic advance
method for correct/resume. `WorkspaceSandbox.invoke()` rechecks permit expiry, live halted state,
and exact action/permit/current epoch equality before consulting idempotency or touching files.

### Step 4.2 — write durable snapshot and typed-record RED tests

```python
def test_patch_snapshot_survives_new_sandbox_instance(tmp_path):
    first = WorkspaceSandbox(tmp_path)
    output = first._dispatch("workspace.apply_patch", {...}, "run:apply")
    second = WorkspaceSandbox(tmp_path)
    second._dispatch("workspace.compensate_patch", {
        "path": "fixture.txt", "original_action_key": "run:apply",
        "compensation_ref": output["compensation_ref"],
    }, "run:compensate:apply")
    assert fixture.read_text() == "before\n"

def test_compensation_refuses_to_overwrite_later_user_edit(...): ...
def test_snapshot_write_failure_has_zero_patch_effect(...): ...
def test_compensation_is_idempotent(...): ...
def test_missing_or_tampered_snapshot_fails_closed(...): ...
def test_same_idempotency_key_with_changed_intent_is_rejected(...): ...
```

Run:

```bash
uv run --extra product-test pytest tests/product/test_long_horizon_compensation.py -q
```

Expected RED: snapshot is memory-only, missing snapshots silently pass, and idempotency is not
bound to stable action intent.

### Step 4.3 — implement durable snapshot and typed internal compensation capability

- Persist opaque snapshot metadata and optional before bytes beneath
  `.agent-os-artifacts/compensation/<sha256(action_key)>/`.
- Freeze an immutable manifest binding version, action-key digest, path, before existence/digest,
  applied digest and manifest digest; keep `PREPARED/APPLIED/COMPENSATED` as a separate atomic
  state marker.
- Write and fsync the snapshot through a staging directory and atomic rename before touching the
  target; write the target via same-directory temporary file + `os.replace()`. Snapshot I/O
  failure must leave target and idempotency unchanged.
- Return `compensation_ref`, `manifest_sha256`, `before_sha256`, and `applied_sha256`; bind the
  ref into `ActionReceipt.detail_ref` so a crash after dispatch but before NODE_COMPLETED remains
  recoverable.
- Add `workspace.compensate_patch` to `WorkspaceSandbox.specs()` and `_dispatch()`.
- Validate action-key/ref/path binding and current target digest before restore.
- Make apply/restore crash-window replay converge from snapshot state + target digest; a third
  digest is a hard conflict and missing/tampered material is never a silent no-op.
- Bind idempotency storage to a stable intent fingerprint, not only the caller-supplied key.
- Emit an `ActionReceipt` with `ReceiptStatus.COMPENSATED`.
- Add a typed `PatchCompensationRecord` for compensation events and make aggregate replay reject
  malformed payloads.
- Mark the capability coordinator-only: do not include it in ordinary grants, provider allowed
  capability lists, or workflow dispatch; only the coordinator's internal path can select it.

### Step 4.4 — add coordinator trigger/restart/C7 RED tests, then implement

```python
def test_not_met_after_worker_restart_compensates_completed_patch(...): ...
def test_node_failure_preserves_failure_and_compensates_reverse_topology(...): ...
def test_missing_ref_records_manual_intervention_without_fake_success(...): ...
def test_c7_halt_blocks_automatic_and_manual_compensation(...): ...
def test_principal_resume_then_explicit_compensation_succeeds_once(...): ...
def test_workflow_and_provider_cannot_call_internal_compensation(...): ...
```

- In `RunCoordinator`, persist the original failure/NOT_MET first, then reverse completed nodes
  and compensate only `workspace.apply_patch` nodes declared `COMPENSATABLE` with a durable ref.
- Build compensation as a new ActionContract with key
  `{run_id}:compensate:{node_id}` and pass PolicyKernel/permit/broker.
- Use a dedicated compensation call that accepts only `ReceiptStatus.COMPENSATED`; do not weaken
  ordinary `_call_tool()` success rules.
- If correction is halted, emit typed `COMPENSATION_BLOCKED` with
  `manual_intervention_required=true`; never special-case a bypass. Other failures emit typed
  `COMPENSATION_FAILED` and stop the reverse pass fail-closed.
- Expose one explicit coordinator compensation command. It fails while correction is halted;
  after the external principal increments a non-halted correction epoch, it follows the same
  policy/permit/broker path as automatic compensation.

### Step 4.5 — run GREEN and commit

```bash
uv run --extra product-test pytest \
  tests/product/test_long_horizon_compensation.py \
  tests/product/test_spine0_security_and_persistence.py \
  tests/product/test_spine0_golden_path.py -q
uv run --extra product-test pytest tests/product -q
uv run --extra product-test ruff check packages tests/product
uv run --extra product-test pyright packages tests/product
git add packages/os_core/src/agent_os_core/capability.py \
  packages/os_core/src/agent_os_core/execution.py \
  packages/os_core/src/agent_os_core/governance.py \
  packages/os_core/src/agent_os_core/persistence.py \
  packages/os_core/src/agent_os_core/postgres.py \
  packages/os_core/src/agent_os_core/task_aggregate.py \
  packages/contracts/src/agent_os_contracts \
  apps/api_server/app.py \
  tests/product/test_long_horizon_compensation.py \
  tests/product/test_spine0_security_and_persistence.py \
  tests/product/test_authority_contracts.py
git commit -m "feat(product): add governed restart-safe patch compensation"
```

---

## Task 5: Add the E1 recovery projection

**Files:**

- Create: `tests/product/test_recovery_projection.py`
- Create: `packages/os_core/src/agent_os_core/recovery.py`
- Modify: `packages/os_core/src/agent_os_core/__init__.py`
- Modify: `apps/api_server/app.py`

### Step 5.1 — write projection RED tests

Build a synthetic but valid event stream and assert:

```python
snapshot = build_recovery_snapshot(events)
assert snapshot.wait_registered_count == 1
assert snapshot.signal_satisfied_count == 1
assert snapshot.replan_count == 1
assert snapshot.compensation_count == 1
assert snapshot.action_receipt_count >= snapshot.unique_logical_action_count
assert snapshot.event_sequence == events[-1].sequence
```

Run:

```bash
uv run --extra product-test pytest tests/product/test_recovery_projection.py -q
```

Expected RED: no recovery projection module.

### Step 5.2 — implement a pure event-derived projection

The projection may count only facts present in typed events. It must not infer physical
exactly-once or long-horizon superiority. `AgentOSApplication.recovery_json(task_id)` returns
`RunRecoverySnapshot.model_dump(mode="json")`.

### Step 5.3 — run GREEN and commit

```bash
uv run --extra product-test pytest tests/product/test_recovery_projection.py -q
uv run --extra product-test pytest tests/product -q
uv run --extra product-test ruff check apps packages tests/product
uv run --extra product-test pyright apps packages tests/product
git add packages/os_core/src/agent_os_core apps/api_server/app.py \
  tests/product/test_recovery_projection.py
git commit -m "feat(product): expose event-derived recovery projection"
```

---

## Task 6: Wire the public HTTP and CLI surfaces

**Primary implementation owner:** Codex for the already-landed adapter checkpoint. OpenCode owns
the follow-up real-persistence/negative-path test hardening in a separate file and worktree.

**Files:**

- Modify: `tests/product/test_api_surface.py`
- Create: `tests/product/test_cli_surface.py`
- Modify: `apps/api_server/app.py`
- Modify: `apps/api_server/server.py`
- Modify: `apps/cli/__main__.py`

### Step 6.1 — write API/CLI RED tests

Add HTTP assertions for:

```text
POST /v1/tasks/{id}/signals
POST /v1/tasks/{id}/replan
POST /v1/tasks/{id}/correction/resume
POST /v1/tasks/{id}/compensate
GET  /v1/tasks/{id}/recovery
```

Test exact idempotent signal replay, wrong scope as 400, late signal as 400 with persisted
timeout state, and replan budget denial. CLI tests invoke `main()` with patched argv and
the same SQLite/workspace, then validate task events rather than stdout only.

Run:

```bash
uv run --extra product-test pytest \
  tests/product/test_api_surface.py tests/product/test_cli_surface.py -q
```

Expected RED: routes/subcommands absent.

### Step 6.2 — implement thin adapters

Add application methods:

```python
signal_task(task_id, payload)
replan_task(task_id, payload)
resume_correction(task_id, reason)
compensate_task(task_id)
recovery_json(task_id)
```

The HTTP and CLI layers only validate JSON/file presence and delegate. They must not append
events or mutate graphs themselves.

### Step 6.3 — run GREEN and commit

```bash
uv run --extra product-test pytest \
  tests/product/test_api_surface.py tests/product/test_cli_surface.py -q
uv run --extra product-test pytest tests/product -q
uv run --extra product-test ruff check apps packages tests/product
uv run --extra product-test pyright apps packages tests/product
git add apps tests/product/test_api_surface.py tests/product/test_cli_surface.py
git commit -m "feat(product): expose signal replan and recovery surfaces"
```

---

## Task 7: Prove the bounded E2 vertical end to end

**Primary implementation owner:** Claude Code. Codex provides the frozen acceptance scenario,
reviews the diff and runs final verification. Kimi owns a separate partial-evidence/rebind
regression file. Neither OpenCode nor Kimi may edit Claude's E2 file or production runtime.

**Files:**

- Create: `tests/product/test_e2_long_horizon_recovery.py`

### Step 7.1 — write the end-to-end RED tests

Test A — success after wait + restart + one replan:

1. real file + real pytest fixture;
2. v1 runs `read -> wait` and stops;
3. new `AgentOSApplication` receives matching signal;
4. authorized v2 replaces only the uncompleted suffix;
5. task resumes through provider, approval, patch, pytest and evaluator;
6. result is VERIFIED, patch receipt logical key is unique, recovery projection matches.

Test B — failure after patch + worker interruption + restart-safe compensation:

1. provider writes a deliberately failing patch;
2. interrupt after completed apply node;
3. new Application resumes, pytest produces NOT_MET;
4. durable compensation restores the original file;
5. task remains FAILED/NOT_MET; `ACTION_COMPENSATED` exists exactly once.

Test C — C7 stays sovereign without making recovery impossible:

1. interrupt after a compensatable patch;
2. external correction halts the task;
3. automatic and manual compensation are both blocked and leave an explicit intervention flag;
4. ordinary run resume does not clear correction;
5. external principal resumes the correction epoch, then requests compensation;
6. the governed compensation restores the file exactly once.

Run:

```bash
uv run --extra product-test pytest tests/product/test_e2_long_horizon_recovery.py -q
```

Expected RED before the complete slice; do not weaken the scenario.

### Step 7.2 — make only integration fixes required by the test

No new architecture is allowed here. If the test exposes a missing contract or authority
path, Claude Code reports the gap and, after Codex architecture review, is the primary writer
for the narrowly approved runtime fix. Do not add a test-only shortcut.

### Step 7.3 — full verification and commit

```bash
uv run --extra product-test pytest tests/product -q
uv run --extra product-test ruff check apps packages/os_core/src packages/contracts/src tests/product
uv run --extra product-test pyright apps packages/os_core/src packages/contracts/src tests/product
git diff --check
git add tests/product/test_e2_long_horizon_recovery.py
git commit -m "test(product): verify bounded long-horizon recovery vertical"
```

---

## Task 8: Reconcile truth, independently review, and hand off

**Files:**

- Modify: `docs/CURRENT_STATE.yaml`
- Modify: `docs/PROJECT_PLAN.md`
- Modify: `codebase_index.md`
- Create: `implementation-log.md`
- Create: `verification.md`
- Update: `.agent_runs/agent-os-e2e-long-horizon-20260712/*` via runner ledgers

### Step 8.1 — update only evidenced claims

Record:

- exact new product capabilities and public entry points;
- exact test count and commands from fresh output;
- local/controlled sandbox envelope;
- no scheduler, general loop, CWM/Belief/SelfModel or LH-RECOVERY verdict;
- checkpoint commit and feature branch Git state.

Use the goal-audit authoring gate before editing `docs/CURRENT_STATE.yaml`, then verify it.

### Step 8.2 — cross-model diff review

Give Kimi/OpenCode/Claude the final diff for independent review, with the final-review pass
read-only even when that agent authored an earlier isolated slice. Cursor participates once its
CLI authentication is available. Review asks:

- signal/resume races and event replay;
- replan authority, completed-prefix immutability and stale approval leakage;
- compensation policy/C7/idempotency/digest checks;
- API/CLI second-path or secret leakage;
- overclaim in docs.

Fix only validated findings, re-run targeted tests, then full checks.

### Step 8.3 — final verification artifact

`verification.md` must include:

```text
Entry point
Contracts
Failure paths
Test validity
Integration
Boundary
Observability
Product/process/research claim separation
Git status / commits / branch / push / PR state
```

Run fresh:

```bash
uv run --extra product-test pytest tests/product -q
uv run --extra product-test ruff check apps packages/os_core/src packages/contracts/src tests/product
uv run --extra product-test pyright apps packages/os_core/src packages/contracts/src tests/product
git diff --check
git status --short
```

### Step 8.4 — final scoped commit

```bash
git add docs/CURRENT_STATE.yaml docs/PROJECT_PLAN.md codebase_index.md \
  implementation-log.md verification.md \
  docs/superpowers/specs/2026-07-12-agent-os-e2e-long-horizon-convergence-design.md \
  docs/superpowers/plans/2026-07-12-agent-os-e2e-long-horizon-implementation.md
git commit -m "docs(product): record bounded long-horizon verification"
```

Do not push, open a PR or merge without a new explicit founder instruction.
