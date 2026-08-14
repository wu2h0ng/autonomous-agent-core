# Review Specification

Authoritative inputs:

- `docs/product/GC-REALTIME-COLLAB-SURFACE-M1B-2026-08-14.md`
- `docs/product/CP-REALTIME-COLLAB-SURFACE-M1B-2026-08-14.md`
- `docs/architecture/T-P-REALTIME-COLLAB-SURFACE-M1B-2026-08-14.md`
- `docs/adr/ADR-0059-merged-capability-execution-authority.md`
- `packages/contracts/src/agent_os_contracts/workspace_collaboration.py`
- `domain_packs/developer_agent/workspace_collaboration.py`

Required invariants:

1. **Single dispatch path** (unchanged): `CapabilityBroker.invoke` remains the only
   production dispatch; no second broker, no new authority source.
2. **Producer holds no authority**: `WorkspaceEventProducer` only appends
   coordination events; it cannot authorize, dispatch, or write effect truth.
3. **Append-only events**: producer events use monotonic sequences derived from the
   fence high-water; duplicate sequence is rejected; no INSERT OR REPLACE.
4. **Cursor advance fail-safe**: `_install_run_work_lease` reads the fence high-water
   for the new lease cursor; on fence-read failure it falls back to 0 without
   weakening the preflight (the preflight still fails closed on a missing/incomplete
   batch at dispatch time).
5. **Projection is read-only**: `SurfaceConflictProjection.from_decision` derives a
   typed view without mutating authority or fence state; suggested_action mapping is
   exhaustive for REPLAN/CONFLICT/CANCEL.
6. **Scope consistency**: producer derives file scope as `file:///ws/{path}`,
   matching the M1a `_file_scope_from_action` convention.
7. **Claims local**: unpushed, unmerged, unreleased; no production/commercial/
   autonomy claim.

Deliverable is a verdict plus findings, not implementation edits.
