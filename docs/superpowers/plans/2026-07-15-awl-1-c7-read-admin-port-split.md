# AWL-1 C7 Read/Admin Port Split Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Ensure generic Runtime code can only read and guard against C7 correction state while authenticated operator/admin code alone receives correction mutation methods.

**Architecture:** Preserve the current persistence, epoch and in-process linearization implementation behind `CorrectionAuthority`, then expose two least-authority views: `CorrectionSnapshotPort` for Runtime consumers and `CorrectionAdminPort` for operator mutation. The modular-monolith composition root owns both views but injects only the snapshot view into policy, dispatch, candidate and execution services. This is a logical trust-boundary step; process, DB-role and signature separation remain a later production gate.

**Tech Stack:** Python 3.12, Pydantic contracts, stdlib `Protocol`/context managers/`RLock`, pytest, Ruff, Pyright.

**Track / claim:** Product Track, behavior-preserving security seam. `IMPLEMENTATION_ONLY / NO_PHYSICAL_C7_ISOLATION / NO_RELEASE`.

**Base requirement:** Start from an exact reviewed Product head that includes the currently accepted candidate lifecycle. Record the base hash and baseline Product test result before editing. Do not implement from this docs-only architecture branch.

---

## Immutable scope

This packet may change only C7 interfaces, injections, composition wiring and directly affected tests. It must not:

- change correction epoch semantics, event payloads, DB schema or canonical digests;
- change policy verdicts, grants, approvals or action authority;
- add process/network services, signatures or DB roles;
- refactor `RunCoordinator` beyond constructor/type injection;
- change ADM candidate/evaluation/promotion/configuration behavior;
- change public HTTP/CLI correction semantics;
- add a model, provider call, experiment or result claim.

## Acceptance gates

1. Runtime-facing correction objects have `snapshot`, `halted` and `guard_unchanged` but no `correct` or `resume` method.
2. Operator/admin objects have `correct` and `resume`; generic Runtime constructors do not accept or retain that object.
3. Correction writes remain monotonic, durable and linearized against guarded effects.
4. Unauthorized principal, scope mismatch and terminal-run paths remain mutation-free.
5. Existing C7 halt, resume, permit invalidation, recovery and compensation behavior remains equivalent.
6. Targeted and full Product tests, Ruff, Pyright, compileall and `git diff --check` pass against the recorded baseline.
7. An independent reviewer accepts the exact implementation HEAD before integration.

### Task 1: Freeze the read/write capability boundary in failing tests

**Files:**

- Create: `tests/product/test_correction_port_separation.py`
- Inspect only: `packages/os_core/src/agent_os_core/governance.py`
- Inspect only: `apps/api_server/app.py`

**Step 1: Write the failing view-separation test**

Add tests equivalent to:

```python
def test_snapshot_view_has_no_mutation_capability() -> None:
    authority = CorrectionAuthority()
    snapshot, admin = split_correction_authority(authority)

    assert hasattr(snapshot, "snapshot")
    assert hasattr(snapshot, "halted")
    assert hasattr(snapshot, "guard_unchanged")
    assert not hasattr(snapshot, "correct")
    assert not hasattr(snapshot, "resume")
    assert hasattr(admin, "correct")
    assert hasattr(admin, "resume")
    assert not hasattr(admin, "snapshot")


def test_admin_write_is_observed_only_through_snapshot_view() -> None:
    authority = CorrectionAuthority()
    snapshot, admin = split_correction_authority(authority)
    before = snapshot.snapshot("task-1", "run-1", "capability-1")

    assert admin.correct("task", "task-1", "operator halt") == 1

    after = snapshot.snapshot("task-1", "run-1", "capability-1")
    assert after.task_epoch == before.task_epoch + 1
    assert snapshot.halted("task-1", "run-1", "capability-1")
```

Also add a composition test asserting `app.correction` is the read-only view and the real `RunCoordinator`/`PolicyKernel` wiring does not expose `correct` or `resume` through its injected correction dependency.

**Step 2: Run the new test and confirm RED**

Run:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. python -m pytest tests/product/test_correction_port_separation.py -q
```

Expected: collection/import or attribute failures because the protocols, views and splitter do not exist.

**Step 3: Record the RED receipt**

Record command, exit code and concise failure in the task-local message bus. Do not weaken the assertion to make current `CorrectionAuthority` pass.

**Step 4: Commit the test-only RED**

```bash
git add tests/product/test_correction_port_separation.py
git commit -m "test(product): freeze C7 port separation"
```

### Task 2: Introduce least-authority C7 protocols and views

**Files:**

- Modify: `packages/os_core/src/agent_os_core/governance.py`
- Modify: `packages/os_core/src/agent_os_core/__init__.py`
- Test: `tests/product/test_correction_port_separation.py`

**Step 1: Define the ports**

Replace the ambiguous Runtime protocol name with explicit contracts:

```python
class CorrectionSnapshotPort(Protocol):
    def snapshot(
        self, task_id: str, run_id: str, capability_id: str
    ) -> CorrectionEpochVector: ...

    def halted(self, task_id: str, run_id: str, capability_id: str) -> bool: ...

    def guard_unchanged(
        self,
        task_id: str,
        run_id: str,
        capability_id: str,
        observed_epochs: CorrectionEpochVector,
    ) -> AbstractContextManager[bool]: ...


class CorrectionAdminPort(Protocol):
    def correct(self, scope: str, scope_id: str, reason: str) -> int: ...
    def resume(self, scope: str, scope_id: str, reason: str = "resumed") -> int: ...
```

Keep `CorrectionGuard = CorrectionSnapshotPort` as a temporary compatibility alias only if required by already reviewed branches. New code must use the explicit name.

**Step 2: Implement narrow views over one authority**

Implement immutable wrapper objects whose public methods contain only their declared capability:

```python
@dataclass(frozen=True)
class CorrectionSnapshotView:
    _authority: CorrectionAuthority

    def snapshot(...):
        return self._authority.snapshot(...)

    def halted(...):
        return self._authority.halted(...)

    def guard_unchanged(...):
        return self._authority.guard_unchanged(...)


@dataclass(frozen=True)
class CorrectionAdminView:
    _authority: CorrectionAuthority

    def correct(...):
        return self._authority.correct(...)

    def resume(...):
        return self._authority.resume(...)
```

Add `split_correction_authority(authority)` returning the two views. Do not duplicate state, locks or persistence connections.

**Step 3: Export only the named contracts and views**

Update `agent_os_core.__init__` so callers can import the two ports, two views and splitter. Retain `CorrectionAuthority` temporarily for compatibility and direct authority unit tests; mark it as composition-internal in its docstring.

**Step 4: Run the focused tests**

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. python -m pytest tests/product/test_correction_port_separation.py tests/product/test_spine0_security_and_persistence.py -q
```

Expected: all tests pass; no correction semantics changed.

**Step 5: Commit**

```bash
git add packages/os_core/src/agent_os_core/governance.py packages/os_core/src/agent_os_core/__init__.py tests/product/test_correction_port_separation.py
git commit -m "feat(product): split C7 snapshot and admin ports"
```

### Task 3: Inject only the snapshot port into generic Runtime code

**Files:**

- Modify: `packages/os_core/src/agent_os_core/governance.py`
- Modify: `packages/os_core/src/agent_os_core/capability.py`
- Modify: `packages/os_core/src/agent_os_core/execution.py`
- Modify: `packages/os_core/src/agent_os_core/materialization.py`
- Modify: `packages/os_core/src/agent_os_core/materialization_evaluation.py`
- Modify: `packages/os_core/src/agent_os_core/materialization_promotion.py`
- Modify only if required by the accepted base: the task-configuration service module that consumes C7
- Test: `tests/product/test_correction_port_separation.py`
- Test: `tests/product/test_materialization_service.py`
- Test: `tests/product/test_materialization_evaluation_service.py`
- Test: `tests/product/test_materialization_promotion_service.py`
- Test: the accepted-base task-configuration service tests

**Step 1: Add a reader-only fake**

Create a fake implementing only `CorrectionSnapshotPort`; do not give it `correct` or `resume`. Add a test that constructs `PolicyKernel`, `CapabilityBroker`, `RunCoordinator` and each candidate/configuration service with that fake. The test must fail before the type/injection cleanup if any constructor still requires concrete `CorrectionAuthority` behavior.

**Step 2: Narrow annotations and retained dependencies**

- `PolicyKernel` accepts `CorrectionSnapshotPort`.
- `CapabilityBroker` and `WorkspaceSandbox.invoke` accept `CorrectionSnapshotPort`.
- `RunCoordinator` accepts and retains `CorrectionSnapshotPort` only.
- candidate sealing, evaluation, promotion and configuration services use `CorrectionSnapshotPort`.
- no generic module imports `CorrectionAdminPort`, `CorrectionAdminView` or calls `correct`/`resume`.

Do not refactor workflow dispatch or move files in this task.

**Step 3: Run Runtime and candidate-chain tests**

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. python -m pytest \
  tests/product/test_correction_port_separation.py \
  tests/product/test_spine0_security_and_persistence.py \
  tests/product/test_materialization_service.py \
  tests/product/test_materialization_evaluation_service.py \
  tests/product/test_materialization_promotion_service.py \
  -q
```

Add the exact task-configuration test file from the accepted base. Expected: all targeted tests pass and the fake proves mutation methods are unnecessary.

**Step 4: Run static boundary search**

```bash
rg -n "CorrectionAdmin|\.correct\(|\.resume\(" packages/os_core/src/agent_os_core
```

Expected: admin symbols and mutation calls exist only in the authority implementation; generic Runtime modules have no admin dependency.

**Step 5: Commit**

```bash
git add packages/os_core/src/agent_os_core tests/product/test_correction_port_separation.py
git commit -m "refactor(product): make Runtime C7 dependency read-only"
```

### Task 4: Rewire the composition and authenticated admin path

**Files:**

- Modify: `apps/api_server/app.py`
- Modify: directly affected API/CLI tests under `tests/product/`
- Test: `tests/product/test_api_surface.py`
- Test: `tests/product/test_public_long_horizon_negative_paths.py`
- Test: `tests/product/test_e2_long_horizon_recovery.py`
- Test: `tests/product/test_long_horizon_compensation.py`

**Step 1: Split composition ownership**

Build one internal `CorrectionAuthority`, split it, and wire it explicitly:

```python
self._correction_authority = CorrectionAuthority(...)
self.correction, self.correction_admin = split_correction_authority(
    self._correction_authority
)
self.policy = PolicyKernel(self.correction)
```

`self.correction` is the compatibility name for the read-only snapshot view. Runtime and candidate services receive it. `correct_task` and `resume_correction` call `self.correction_admin` only after the existing principal/scope/terminal-state validation.

**Step 2: Migrate tests that intentionally emulate the external authority**

Tests that currently call `app.correction.correct(...)` must use one of:

- the public `app.correct_task(...)` path when task-scope behavior is under test; or
- `app.correction_admin.correct(...)` only when a lower-level run/capability-scope authority race is the subject.

Do not add a mutation method back to `app.correction` for test convenience.

**Step 3: Preserve audit ordering and mutation-free denial**

Add or retain assertions that:

- failed role/scope/reason/terminal checks do not advance an epoch or append `CORRECTION_WRITTEN`;
- a successful admin write advances the epoch before the audit event is observed;
- ordinary run resume does not clear C7;
- only the explicit correction-resume command clears the halt.

**Step 4: Run public-surface and recovery tests**

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. python -m pytest \
  tests/product/test_api_surface.py \
  tests/product/test_public_long_horizon_negative_paths.py \
  tests/product/test_e2_long_horizon_recovery.py \
  tests/product/test_long_horizon_compensation.py \
  tests/product/test_correction_port_separation.py \
  -q
```

Expected: all targeted tests pass with unchanged public behavior.

**Step 5: Commit**

```bash
git add apps/api_server/app.py tests/product
git commit -m "refactor(product): isolate C7 admin composition"
```

Before committing, inspect `git diff --cached --name-only` and unstage any unrelated test file.

### Task 5: Prove persistence and linearization equivalence

**Files:**

- Modify: `tests/product/test_correction_port_separation.py`
- Modify only if a real defect is exposed: `packages/os_core/src/agent_os_core/governance.py`

**Step 1: Add restart equivalence**

Create an authority over `SQLiteTaskEventStore`, write through the admin view, reconstruct a new authority/view over the same DB, and assert the read view observes the same epoch/halt state.

**Step 2: Add guarded-effect interleaving test**

Hold `snapshot.guard_unchanged(...)` in one thread and attempt `admin.correct(...)` in another. Assert the correction blocks until the guard exits, then advances exactly once. Repeat the existing stale-authority monotonicity case through the views.

**Step 3: Run concurrency/persistence regressions repeatedly**

```bash
for i in 1 2 3 4 5; do
  PYTHONPATH=packages/contracts/src:packages/os_core/src:. python -m pytest \
    tests/product/test_correction_port_separation.py \
    tests/product/test_spine0_security_and_persistence.py \
    tests/product/test_long_horizon_compensation.py -q || exit 1
done
```

Expected: five clean repetitions, no deadlock and no flaky epoch count.

**Step 4: Commit**

```bash
git add tests/product/test_correction_port_separation.py packages/os_core/src/agent_os_core/governance.py
git commit -m "test(product): prove C7 port linearization"
```

If production code did not change, omit it from `git add`.

### Task 6: Full verification and exact-head review

**Files:**

- Modify: `docs/CURRENT_STATE.yaml` only after implementation evidence is final
- Modify: task-local `messages.jsonl` / review receipt outside tracked Runtime scope as required by the message-bus policy

**Step 1: Run the full Product suite**

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. python -m pytest tests/product -q
```

Expected: no new failure relative to the recorded exact-base baseline. Any time-dependent pre-existing failure must be named with exact test and proven outside this diff; do not silently call the suite green.

**Step 2: Run static and repository gates**

```bash
python -m ruff check packages/os_core/src apps/api_server tests/product/test_correction_port_separation.py
python -m ruff format --check packages/os_core/src apps/api_server tests/product/test_correction_port_separation.py
python -m pyright packages/os_core/src apps/api_server
python -m compileall -q packages/os_core/src apps/api_server
git diff --check
git status --short
```

Expected: all static commands exit 0; only scoped task files are changed.

**Step 3: Verify architecture boundary mechanically**

```bash
rg -n "CorrectionAdmin|\.correct\(|\.resume\(" packages/os_core/src/agent_os_core
rg -n "CorrectionSnapshotPort" packages/os_core/src/agent_os_core apps/api_server
```

Manually classify every hit. Runtime modules may depend on `CorrectionSnapshotPort`; admin mutation must remain in the authority implementation and authenticated composition path.

**Step 4: Update live truth conservatively**

Record separate states:

```text
implemented / tested / exact-head-reviewed / integrated / merged / released
```

Do not claim physical C7 isolation, production readiness or release. If exact review is pending, use `IMPLEMENTED_LOCAL / REVIEW_PENDING`.

**Step 5: Create one final evidence commit**

```bash
git add docs/CURRENT_STATE.yaml
git commit -m "docs: record AWL-1 C7 port evidence"
```

Only create this commit if `CURRENT_STATE.yaml` changed and all recorded evidence exists.

**Step 6: Request independent exact-head review**

Reviewer receives:

- exact base and head hashes;
- the immutable scope and acceptance gates above;
- full diff and all verification receipts;
- explicit questions about mutation reachability, guard linearization, public compatibility and overclaiming.

Verdicts:

- `TECHNICAL_APPROVE`: eligible for a separately authorized integration;
- `REVISE`: fix on the same branch, rerun all affected gates and review the new exact HEAD;
- timeout/no explicit verdict: `NOT_ACCEPTED`.

No push, merge, release or production activation is authorized by this plan.
