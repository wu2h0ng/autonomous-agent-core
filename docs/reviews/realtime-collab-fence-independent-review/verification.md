# Verification Record Supplied to Reviewer

## Head under review

- Target: `34d2d376431adb69817c1ed66f0e862801e453e6`
- Base: `c819f75b9ad01850a90850d72da2b621129308a2` (spec head, CTO_IMPLEMENTATION_AUTHORIZED)
- Target is exactly base + 1 commit (9 files, +1206/-1). Not pushed.

## Test results

- New tests: `tests/product/test_workspace_collaboration_fence.py` (13) +
  `tests/product/test_workspace_commit_fence.py` (9) = **22 passed**.
- Full Product: **2187 passed, 1 skipped, 1 failed**.
- The single failure `test_product_entrypoint.py::test_installed_product_package_contains_api_surface_resources`
  reproduces on base `c819f75` (editable-install environment debt; `index.html`
  exists in source but not in the editable install). Pre-existing, not introduced.

## Static checks

- Ruff (changed scope + full canonical scope): PASS on changed files. Two
  pre-existing `F401` in `domain_packs/developer_agent/workspace_capability.py`
  (untouched by this change).
- Pyright (changed files): **0 errors, 0 warnings**.
- Pyright (full scope): 110 errors, identical to pre-existing baseline (zero new).

## P1 closure spot-checks

- REPLAN blocks: `capability.py` `_enforce_collaboration` raises `ReplanRequired`
  before `outcomes.reserve`; test `test_replan_blocks_dispatch_with_zero_connector_calls`
  asserts `execute_calls == 0`. PASS.
- No effect truth in fence: `WorkspaceCommitFence`/`SQLiteWorkspaceCommitFence` expose
  only `install_lease`/`append_event`/`current_lease`/`read_after`; `test_fence_holds_no_effect_truth`
  asserts no PREPARED/COMMITTED/UNKNOWN attr and no `dispatch`. PASS.
- Trusted registry: `_lookup_spec` reads `connector.specs()`; `test_collaboration_required_reads_trusted_registry_not_caller_args`
  proves caller args cannot downgrade. PASS.
- Replay before preflight: `invoke` calls `replay()` before `_enforce_collaboration`;
  `test_replay_before_preflight_returns_sealed_outcome_unchanged` asserts the hostile
  preflight is never invoked (`seen_claim is None`). PASS.
- Same-origin binding: `WorkspaceCollaborationPreflight.preflight` checks
  `claim.run_id/owner/fence` vs lease; `test_preflight_cancel_on_fence_token_mismatch`. PASS.

Verification is necessary but not approval. Reviewer must inspect the diff and source.
