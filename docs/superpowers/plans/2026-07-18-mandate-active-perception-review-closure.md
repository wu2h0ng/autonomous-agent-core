# Mandate Active Perception Review Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three exact-head review defects in bounded Mandate active perception without adding TaskActivation, capability grants, external effects, a second scheduler, or a new authority spine.

**Architecture:** Keep the existing one-shot service and the existing Data Agent report outbox. Make dispatch completion lease-fenced in the same SQLite transaction as the outbox update, require the completed outcome's authoritative `SituatedAssessmentRecord` to remain resolvable on every read/replay, and bind the schedule config to the exact adapter and situated runtime composition rather than scope labels alone.

**Tech Stack:** Python 3.12, stdlib `sqlite3`, Pydantic contracts already in the repository, pytest, Ruff, Pyright.

## Global Constraints

- Product Track only; no import from `src/aac` or `experiments`.
- RED test must be observed before each production change.
- The production startup composition uses one SQLite database for report state, situated authority, and active perception. Fail closed if that identity is not exact.
- A stale or expired lease holder must not persist `COMPLETED`, even if it already produced an assessment.
- A completed dispatch is trusted only while its exact scoped `SituatedAssessmentRecord` remains present and digest-equal.
- `activation_authorized`, `capability_grant_authorized`, and `external_effects_authorized` remain `False`.
- No release, freeze, provider result run, research claim, or autonomy claim.

---

### Task 1: Atomic Lease-Fenced Dispatch Completion

**Files:**
- Modify: `apps/api_server/data_agent_report_adapter.py`
- Modify: `apps/api_server/mandate_active_perception.py`
- Test: `tests/product/test_mandate_active_perception.py`

**Interfaces:**
- Consumes: `ActivePerceptionLease`, `MandateActivePerceptionConfig`, `DataAgentReportDispatch`, `SituatedAssessmentRecord`.
- Produces: `DataAgentReportAdapter.complete_active_perception_dispatch(..., schedule_id: str, config_digest: str, worker_id: str, lease_fence: int, completed_at: datetime, authority_snapshot_digest: str) -> DataAgentReportDispatch`.

- [ ] **Step 1: Add the stale-holder RED test**

Add a test that acquires lease A, advances the clock beyond A expiry, acquires lease B, then attempts completion through A. Assert `DataAgentReportAdapterError` or `RuntimeError` with `lease fence` and assert the outbox row remains `PENDING`.

First update the local `_service` test helper so its report adapter and `SQLiteMandateActivePerceptionStore` use the same `runtime.sqlite3` path, matching production startup. Add one separate constructor test proving two different database paths fail closed.

```python
def test_stale_lease_holder_cannot_complete_after_takeover(tmp_path: Path) -> None:
    service, runtime, adapter = _service(tmp_path)
    service.ensure_schedule(first_wake_at=NOW)
    adapter.poll_once(limit=1)
    dispatch = adapter.pending_dispatches()[0]
    stale = service.store.acquire_due_lease(
        service.config, worker_id="worker-stale", now=NOW, force_pending=True
    )
    assert not isinstance(stale, ActivePerceptionDisposition)
    current = service.store.acquire_due_lease(
        service.config,
        worker_id="worker-current",
        now=NOW + timedelta(seconds=service.config.lease_seconds + 1),
        force_pending=True,
    )
    assert not isinstance(current, ActivePerceptionDisposition)
    with pytest.raises((DataAgentReportAdapterError, RuntimeError), match="lease fence"):
        adapter.complete_active_perception_dispatch(
            dispatch,
            outcome_record=runtime.propose_record(
                dispatch.environment_event_id,
                dispatch.projection_id,
                f"receipt:{dispatch.environment_event_id}",
            ),
            schedule_id=service.config.schedule_id,
            config_digest=service.config.config_digest,
            worker_id=stale.worker_id,
            lease_fence=stale.fence,
            completed_at=NOW + timedelta(seconds=service.config.lease_seconds + 1),
            authority_snapshot_digest=runtime.authority_digest,
        )
    assert adapter.pending_dispatches() == (dispatch,)
```

- [ ] **Step 2: Run the RED test**

Run: `.venv/bin/python -m pytest tests/product/test_mandate_active_perception.py::test_stale_lease_holder_cannot_complete_after_takeover -q`

Expected: FAIL because `complete_active_perception_dispatch` does not exist.

- [ ] **Step 3: Implement one-transaction fencing**

Implement the new adapter/state-store method only for `SQLiteDataAgentReportStateStore`. Inside one `BEGIN IMMEDIATE` transaction on the shared database:

```sql
SELECT config_digest, lease_owner, lease_fence, lease_expires_at
FROM mandate_active_perception_schedule
WHERE schedule_id = ?
```

Require exact `config_digest`, `lease_owner`, `lease_fence`, and `completed_at < lease_expires_at`; then run the existing observation/outcome validation and conditional `PENDING -> COMPLETED` update before commit. The service constructor must reject a non-SQLite durable store or a schedule store whose canonical database path differs from the report store. Replace the service's call to `complete_dispatch` with this method.

- [ ] **Step 4: Run targeted tests**

Run: `.venv/bin/python -m pytest tests/product/test_mandate_active_perception.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api_server/data_agent_report_adapter.py apps/api_server/mandate_active_perception.py tests/product/test_mandate_active_perception.py
git commit -m "fix(product): fence active perception completion"
```

### Task 2: Completed Dispatch Depends on Live Assessment Provenance

**First reviewer amendment (2026-07-18, superseded):** The first implementation exposed an
optional caller-supplied resolver. That preserved a bypass: a caller could cache
the exact record, delete the authoritative row, then inject the cached value.
Task 2 is therefore revised to remove the resolver argument entirely and bind one
scope-bound assessment authority only through the situated composition seal.

**Second reviewer amendment (2026-07-18, controlling):** The module seal and
adapter setter still allowed a same-scope reader backed by a copied SQLite
database to replace live authority. Task 2 provenance and Task 3 exact binding
are therefore one inseparable closure. Delete the outcome seal/setter and public
runtime resolver. A completed read derives the canonical SQLite path only from
the adapter's own report state, constructs the scoped reader on that same path,
and validates the exact record. Bootstrap and service require report, situated
authority and schedule canonical database identity to match. Service restart
validates only the adapter namespace's latest bounded `feed_limit` completions
via the real completed-dispatch path; it does not scan historical outbox state
or rely on a schedule time window that can miss completion-before-finish crashes.
Each run drains at most the first stable-ordered `feed_limit` pending dispatches,
so one crash batch cannot exceed the bounded restart replay set; later pending
work remains explicit in `pending_remaining`.

**Files:**
- Modify: `apps/api_server/data_agent_report_adapter.py`
- Modify: `apps/api_server/data_agent_situated_bootstrap.py`
- Modify: `apps/api_server/mandate_active_perception.py`
- Modify: `packages/os_core/src/agent_os_core/situated_persistence.py`
- Modify: `packages/os_core/src/agent_os_core/situated.py`
- Test: `tests/product/test_mandate_active_perception.py`
- Test: `tests/product/test_data_agent_situated_bootstrap.py`
- Test: `tests/product/test_data_agent_report_dispatch_outbox.py`
- Test: `tests/product/test_data_agent_provider_relevance_e2e.py`

**Interfaces:**
- Consumes: adapter-owned canonical SQLite report path and the private scoped
  record-ID lookup on `ScopedSituatedAssessmentReader`.
- Produces: `completed_dispatch(dispatch_id)` with no authority/resolver
  injection; no public runtime or unscoped-store record-ID lookup.

- [ ] **Step 1: Add cached-injection and trusted-restart RED tests**

Complete one dispatch, cache its exact assessment, delete the authoritative row,
and prove caller injection is rejected. Copy the valid database, delete the live
row, and prove the copy cannot restore trust. Separately restart the real service
over the same SQLite database and prove bounded latest-completion replay validates
through `completed_dispatch` before returning `NOT_DUE` and after a crash between
dispatch completion and schedule finish.

- [ ] **Step 2: Run the RED test**

Run: `.venv/bin/python -m pytest tests/product/test_mandate_active_perception.py -k 'cached_record_injected or composed_scoped_authority' -q`

Expected: FAIL because the public resolver accepts cached state and the runtime lookup is digest-based rather than exact record-ID based.

- [ ] **Step 3: Bind every completed read to the authoritative record**

Keep exact `assessment_record_id` lookup only on the scoped situated reader and
its private store implementation. `completed_dispatch` derives the canonical DB
from its concrete SQLite report store, creates the reader at that path, and then
independently verifies record ID, canonical digest, event, projection, mandate,
environment binding and scope. Missing, tampered, copied-DB, foreign-scope,
non-SQLite, or authority failure must raise a typed fail-closed error.

- [ ] **Step 4: Run targeted tests**

Run: `.venv/bin/python -m pytest tests/product/test_mandate_active_perception.py tests/product/test_data_agent_situated_bootstrap.py -q`

Expected: all tests pass.

Then run the related adapter/provider expansion and the full Product suite. The
provider active-perception fixture must use the same canonical SQLite database
for report outbox, situated assessment authority and schedule fencing.

- [ ] **Step 5: Commit**

```bash
git add apps/api_server/data_agent_report_adapter.py apps/api_server/data_agent_situated_bootstrap.py apps/api_server/mandate_active_perception.py packages/os_core/src/agent_os_core/situated_persistence.py packages/os_core/src/agent_os_core/situated.py tests/product/test_mandate_active_perception.py tests/product/test_data_agent_situated_bootstrap.py tests/product/test_data_agent_report_dispatch_outbox.py tests/product/test_data_agent_provider_relevance_e2e.py docs/superpowers/plans/2026-07-18-mandate-active-perception-review-closure.md
git commit -m "fix(product): seal live assessment provenance"
```

### Task 3: Exact Adapter/Runtime/Config Binding and Type Closure (closed with Task 2)

**Files:**
- Modify: `apps/api_server/data_agent_report_adapter.py`
- Modify: `apps/api_server/data_agent_situated_bootstrap.py`
- Modify: `apps/api_server/mandate_active_perception.py`
- Test: `tests/product/test_mandate_active_perception.py`

**Interfaces:**
- Consumes: adapter's frozen source binding and runtime's deployment-internal composition.
- Produces: `active_perception_binding_digest` on both adapter and runtime, derived from principal, tenant, workspace, mandate, environment binding, state namespace, admission-policy digest, and canonical database identity.

- [ ] **Step 1: Add mismatched composition RED tests**

Construct same-scope adapters/runtimes with a different mandate, environment binding, admission policy digest, or database and assert `MandateActivePerceptionService(...)` raises `TypeError` with `binding` before schedule creation or polling.

- [ ] **Step 2: Run the RED tests**

Run: `.venv/bin/python -m pytest tests/product/test_mandate_active_perception.py -k 'binding and mismatch' -q`

Expected: at least one case FAIL because the constructor currently compares only principal scope.

- [ ] **Step 3: Implement exact binding validation**

Derive the digest from canonical typed values owned by the adapter and bootstrap runtime; do not accept a caller-provided digest. Require adapter/runtime digest equality and require config fields to equal the corresponding frozen binding fields. Keep the runtime protocol explicit so Pyright sees every required property and method.

The digest covers principal, tenant, workspace, mandate, environment binding,
state namespace, admission-policy digest and canonical database identity. This
step is part of the same commit as the controlling Task 2 amendment; neither task
may be accepted independently.

- [ ] **Step 4: Verify targeted and static gates**

Run:

```bash
.venv/bin/python -m pytest tests/product/test_mandate_active_perception.py tests/product/test_data_agent_situated_startup.py tests/product/test_data_agent_provider_relevance_e2e.py -q
.venv/bin/ruff check apps/api_server/mandate_active_perception.py apps/api_server/data_agent_report_adapter.py apps/api_server/data_agent_situated_bootstrap.py tests/product/test_mandate_active_perception.py
.venv/bin/pyright apps/api_server/mandate_active_perception.py apps/api_server/data_agent_report_adapter.py apps/api_server/data_agent_situated_bootstrap.py tests/product/test_mandate_active_perception.py
```

Expected: tests pass, Ruff exits 0, Pyright reports 0 errors.

- [ ] **Step 5: Run Product regression suite**

Run: `.venv/bin/python -m pytest tests/product -q`

Expected: zero failures; existing environment-dependent skips remain explicit.

- [ ] **Step 6: Commit**

```bash
git add apps/api_server/data_agent_report_adapter.py apps/api_server/data_agent_situated_bootstrap.py apps/api_server/mandate_active_perception.py tests/product/test_mandate_active_perception.py
git commit -m "fix(product): bind active perception composition"
```

## Final Review Gate

- Exact-head reviewer must reproduce the original three attacks.
- Reviewer must inspect the transaction boundary, not infer safety from green tests.
- `git diff --check`, targeted tests, full Product tests, Ruff, and Pyright must be fresh.
- A clean verdict authorizes integration review only; it does not authorize release or an Agent OS/Autonomy claim.
