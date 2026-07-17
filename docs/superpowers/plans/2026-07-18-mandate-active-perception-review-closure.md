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

**Files:**
- Modify: `apps/api_server/data_agent_report_adapter.py`
- Modify: `apps/api_server/data_agent_situated_bootstrap.py`
- Test: `tests/product/test_mandate_active_perception.py`

**Interfaces:**
- Consumes: `ScopedSituatedAssessmentReader` already held by `DataAgentSituatedRuntime`.
- Produces: runtime method `resolve_assessment_record(assessment_record_id: str) -> SituatedAssessmentRecord | None` and optional resolver argument on `completed_dispatch`.

- [ ] **Step 1: Add the deleted-assessment RED test**

Complete one dispatch, delete its exact row from `situated_assessment_records` using the same SQLite database, restart the adapter/runtime, and assert `completed_dispatch(dispatch_id)` fails closed with `outcome record` rather than returning trusted completion.

- [ ] **Step 2: Run the RED test**

Run: `.venv/bin/python -m pytest tests/product/test_mandate_active_perception.py -k completed_dispatch_rejects_deleted_assessment -q`

Expected: FAIL because completed dispatch validation currently checks only the copied digest/id.

- [ ] **Step 3: Bind every completed read to the authoritative record**

Expose a narrow runtime resolver over the already-scoped situated reader. Change the active-perception completion/replay path so a completed row is accepted only if the resolver returns the exact record and both `assessment_record_id` and `content_digest(record)` equal the outbox values. Missing, tampered, foreign-scope, or resolver failure must raise a typed fail-closed error.

- [ ] **Step 4: Run targeted tests**

Run: `.venv/bin/python -m pytest tests/product/test_mandate_active_perception.py tests/product/test_data_agent_situated_bootstrap.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api_server/data_agent_report_adapter.py apps/api_server/data_agent_situated_bootstrap.py tests/product/test_mandate_active_perception.py
git commit -m "fix(product): require live assessment provenance"
```

### Task 3: Exact Adapter/Runtime/Config Binding and Type Closure

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
