# Verification Record Supplied to Reviewer (Round 2)

## Head under review

- Target: `d0afc3a6106809c2736d5e5f780151f8ff55f1b3`
- Base: `c819f75b9ad01850a90850d72da2b621129308a2` (spec head)
- First review `84b41e2c` (REVISE / P1=5) is an ancestor via `b2428eee` (packet).

## Test results

- Collaboration tests (fence seam + commit fence + entry-point): **35 passed**.
- Full Product: **2200 passed, 1 skipped, 1 failed**.
- The single failure `test_product_entrypoint.py::test_installed_product_package_contains_api_surface_resources`
  reproduces on base `c819f75` (editable-install environment debt). Pre-existing.

## Static checks

- Ruff (changed files + full canonical scope): PASS (all checks passed).
- Pyright (changed files): 0 errors, 0 warnings.
- Pyright (full scope): 110 errors, identical to pre-existing baseline (zero new).

## P1 closure spot-checks

1. Registry fail-closed: `capability.py::_lookup_spec` raises on registry exception
   and on missing spec; tests `test_registry_exception_fails_closed_not_noop`,
   `test_missing_spec_fails_closed` assert `execute_calls == 0`.
2. Real wiring: `workspace.edit`/`workspace.apply_patch` marked
   `collaboration_required=True` in `DeveloperWorkspaceAdapter.specs()`;
   `AgentOSApplication` builds `workspace_fence` + `collaboration_preflight` and
   injects into `RunCoordinator`, `AgentLoop`, `agent_cli`, `responsibility_surface`;
   `_install_run_work_lease` installs an authoritative lease at `start_run`;
   `test_production_registry_marks_*`, `test_production_composition_root_wires_*`,
   `test_collaboration_required_write_without_lease_fails_closed` cover it.
3. Same-origin: preflight checks action `task_id`/`run_id`/`tenant_id`/
   `workspace_id`/`principal_id` against the lease; `test_task_id_mismatch_fails_closed`,
   `test_tenant_id_mismatch_fails_closed`, `test_preflight_cancel_on_execution_claim_run_mismatch`.
4. Scope fail-closed: `_file_scope_from_action` returning empty → CANCEL;
   `test_unresolvable_write_scope_fails_closed`. `ResourceScope.covers/overlaps`
   gained directory-prefix semantics (`file:///ws` covers `file:///ws/a.txt`).
5. Complete batch + linearization: `WorkspaceEventBatch` built via `build_batch`
   with contiguity validation; append-only (`INSERT`, duplicate rejected by
   `WorkspaceEventSequenceConflict`); `read_coordination` atomic snapshot; POSIX
   `flock`; tests for duplicate rejection and gap fail-closed.

Verification is necessary but not approval. Reviewer must inspect the diff and source.
