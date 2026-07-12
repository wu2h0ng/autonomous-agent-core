# Agent OS bounded long-horizon verification

- Date: 2026-07-12
- Branch: `codex/agent-os-e2e-long-horizon-20260712`
- Scope: local Product Track acceptance only
- Status: `FINAL_LOCAL_PRODUCT_GATE_PASSED`

## Fresh machine evidence

```text
uv run --extra product-test pytest tests/product -q
166 passed, 1 skipped in 11.34s

uv run --extra product-test pytest \
  tests/product/test_e2_long_horizon_recovery.py \
  tests/product/test_public_long_horizon_negative_paths.py \
  tests/product/test_rebind_partial_evidence_regression.py -q
12 passed in 5.64s

uv run --extra product-test ruff check \
  apps packages/os_core/src packages/contracts/src tests/product
All checks passed

uv run --extra product-test pyright \
  apps packages/os_core/src packages/contracts/src tests/product
0 errors, 0 warnings, 0 informations

git diff --check
clean
```

The default skip is the opt-in live-provider smoke; no live provider result is claimed by this
task. The whole-repository Product+Research suite was not rerun on this branch; the previous
1321-passed result remains a dated historical baseline, not current-branch evidence.

## Engineering reality gates

### Entry point

- `AgentOSApplication.signal_task`
- `AgentOSApplication.replan_task`
- `AgentOSApplication.resume_correction`
- `AgentOSApplication.compensate_task`
- `AgentOSApplication.recovery_json`
- matching HTTP routes and CLI commands

All adapters delegate to TaskService/RunCoordinator; they do not append success events or mutate
workflow graphs independently.

### Contracts

The slice consumes or produces `Goal`, `Commitment`, `WorkflowGraph`, `AgentRun`,
`ExternalSignal`, `WaitCondition`, `RunPlanRebound`, `ActionContract`, `ActionPermit`,
`ActionReceipt`, `PatchCompensationRecord`, `ObservedOutcome` and `RunRecoverySnapshot`.

### Failure paths

Verified denials include wrong task/run/tenant/workspace/correlation scope, duplicate signal with
changed content, late signal, wait/Commitment expiry, replan budget/scope/completed-prefix drift,
stale approval, lease CAS conflict, expired/stale/halted permits, snapshot/manifest drift, user
post-edit, original or compensation capability halt, active-run/manual-role denial and missing
compensation binding.

### Test validity

- Tests assert append-only event counts/order, aggregate state and physical file contents.
- Public-surface tests use real SQLite plus real HTTP/CLI adapters, not only fake routing.
- The `LH_PRODUCT_SLICE_E2` suite uses a real pytest subprocess and reconstructs
  `AgentOSApplication` from the same
  database/workspace.
- The partial-evidence test executes real tools; it does not fabricate `ARTIFACT_RECORDED`.
- Returning constants, skipping signal/rebind, bypassing C7 or omitting compensation would fail
  at least one status, event-order, digest, receipt or file-content assertion.

### Integration

The new behavior is connected from Application, HTTP and CLI through TaskService,
RunCoordinator, PolicyKernel, CapabilityBroker, WorkspaceSandbox, evaluator and the event store.
The recovery projection is derived only from typed events.

### Boundary

- No `src/aac`, `experiments` or research verdict files changed.
- No cross-repo imports or external Agent framework runtime dependencies were added.
- C7 remains non-writable/non-bypassable by providers and final at the connector boundary.
- The model/provider may propose typed actions but never holds final execution authority.

### Observability

Wait registration/satisfaction, signals, rebinds, receipts, artifacts, outcomes, correction
writes, compensation start/block/result and terminal state are durable typed events. Recovery
counts are projections, not exactly-once claims.

### Product/process/research separation

- Product runtime claim: one bounded local durable recovery slice is implemented and accepted.
- Internal process claim: Hermes/run ledgers and multi-agent reviews governed development; these
  are not product features.
- Research claim: none. `LH-RECOVERY-1` is not preregistered, frozen or run.

## Independent reviews

- Coordinator/rebind audit: `ACCEPT`, no P0/P1.
- Compensation/C7 audit: `ACCEPT`, no P0/P1.
- Supporting-agent commits were not trusted on self-report: Codex reviewed diffs, returned
  `REVISE` where assertions or public-path coverage were insufficient, then reran targeted gates
  after author repair.

## Git state

- Feature branch only; no push, PR or merge.
- Implementation commits are listed in `implementation-log.md`.
- Documentation/verification files remain to be committed in the final scoped docs commit.

## Final post-documentation gate

Fresh verification after the authoritative document edits completed on 2026-07-12:

```text
Product suite: 166 passed, 1 skipped in 11.34s
Focused multi-agent acceptance: 12 passed in 5.64s
Ruff: All checks passed
Pyright: 0 errors, 0 warnings, 0 informations
CURRENT_STATE YAML: OK
git diff --check: clean
Product-only boundary (065ff8b..HEAD): no src/aac, experiments or docs/research changes
```

This is the final local Product gate for the scoped branch. It is not a whole-repository
regression, production-readiness gate, `LH-RECOVERY-1` result or generalized long-horizon
claim.
