# ADR-0059: Merged main Capability Execution Authority Reconciliation

- Status: Proposed (merge-design task deliverable, awaiting founder confirmation)
- Date: 2026-08-13
- Deciders: founder (merge route A authorized 2026-08-13); architecture decision requested here
- Context: `docs/adr/ADR-0058` accepted; merge assessment `.agent_runs/native-surface-wave2a-20260812/merge-assessment.md`

## Context

`main` (terminal-coding-agent lineage, `cf2af7ee`) and the wave lineage (`codex/native-surface-wave2a-macos-shell-20260812`, `5256c566`) both implement the capability execution authority, but with complementary rather than competing mechanisms:

- **main** `CapabilityBroker.invoke(action, permit, attempt)` (capability.py, 101 lines): permit/epoch/correction checks inside the broker, then `connector.execute(action) -> CapabilityEffect` and builds an `ActionReceipt`. Heavy durable machinery lives in `RunCoordinator` (execution.py): run leases, effect custody, automatic compensation, interrupt handling — for the long-horizon Task workflow path.
- **wave** `WorkspaceSandbox.invoke(action, permit, correction, execution_lease=...)` (~1175 lines): the durable reservation → lease-fenced dispatch → receipt/outcome seal spine (`DurableActionOutcomeRepository`), typed `CapabilityEffectUnknown` fail-closed, and C7 dispatch linearization (`guard_unchanged`) — built for the chat/approval path to satisfy the Wave 1 plan's exactly-once and restart-fail-closed constraints.

Neither lineage alone covers both requirements: main's thin broker has no durable reservation/UNKNOWN semantics for the approval path; wave's spine does not include RunCoordinator's run-level custody/compensation.

## Options Considered

1. **Union by duplication**: keep both `invoke` paths and route by caller. Rejected: creates two execution paths for the same spine — a bypass risk that violates the authority invariants.
2. **Wave spine wins**: `WorkspaceSandbox.invoke(action, permit, correction, ...)` becomes the only dispatch path; main's RunCoordinator re-targets it; `CapabilityBroker` keeps the `execute` connector contract only for internal use. Cost: RunCoordinator and its tests (main's custody/compensation machinery) must be re-verified against the wave spine; the thin-broker public call sites in main's agent_loop change.
3. **Main shape wins, wave spine grafted in (RECOMMENDED)**: keep the stable public `CapabilityPort.execute(action) -> CapabilityEffect` connector contract and `CapabilityBroker.invoke(action, permit, attempt, execution_lease=None)` signature as the canonical entry; move the durable reservation/lease/UNKNOWN/C7-linearization spine INTO the broker path so every dispatch (run workflow AND chat/approval) flows through it; wave's `WorkspaceSandbox` implements `CapabilityPort.execute` and exposes its outcome repository to the broker; RunCoordinator's run-level custody/compensation stays at the coordinator layer. Cost: capability.py grows; the wave sandbox's `invoke(action, permit, correction, ...)` public method is removed (tests updated); `execution_lease` remains an explicit broker parameter for the approval-continuation single-owner path.

## Decision

**Option 3**: merged main keeps `CapabilityPort.execute` and `CapabilityBroker.invoke(action, permit, attempt, *, execution_lease=None)` as the ONLY capability dispatch path, with the wave durable spine (reservation, lease-fenced insert, replay, typed UNKNOWN, C7 `guard_unchanged` linearization) executed inside the broker. `WorkspaceSandbox` becomes the `execute` connector with a `surface_broker_invoke`-compatible outcome repository; RunCoordinator retains run-level leases/compensation unchanged. Approval continuation passes `execution_lease` explicitly; every other caller uses the default.

Concrete invariants (unchanged from both lineages, now enforced on ONE path):
- typed ActionContract/ActionPermit match before any effect;
- **deterministic deny checks (argument allowlist/path preflight) run BEFORE durable reservation** — a deterministic DENIED raises `CapabilityDenied` without creating a reservation; only exceptions after reservation begins become typed UNKNOWN (no deny-to-UNKNOWN promotion);
- durable reservation before dispatch; reservation-without-outcome is typed UNKNOWN and never resent;
- lease-fenced reservation insert; execution ownership only via an explicit lease;
- C7 correction linearized against dispatch (`guard_unchanged`); reentrant correction aborts dispatch;
- receipts/outcomes sealed once and **the sealed receipt reuses the reservation's `receipt_id`** (no fresh uuid at seal time); known replays return the original receipt/output;
- **fail-closed**: if the connector has no durable outcome repository, the broker refuses dispatch;
- RunCoordinator run-level custody/compensation unchanged.

## Amended merge file list (supersedes the merge assessment list)

The lease-fenced idempotency primitives are wave-lineage additions and must be carried into merged main, or the approval path raises `TypeError`:

- `packages/os_core/src/agent_os_core/persistence.py` — `acquire_lease_if_idempotency_absent`, `put_idempotency_guarded_by_lease`, `_lease_active`, `_held_leases` release/close semantics
- `packages/os_core/src/agent_os_core/postgres.py` — the Postgres equivalents (advisory lock + guarded insert)
- `packages/os_core/src/agent_os_core/_action_outcome.py` — `DurableActionOutcomeRepository`, `ExecutionLease`, `ExecutionLeaseConflict`
- `packages/os_core/src/agent_os_core/governance.py` — `guard_unchanged` + `CorrectionGuardConflict`
- `packages/os_core/src/agent_os_core/capability.py` — the merged broker + connector (this ADR)
- then execution.py, action_pipeline.py, task_service.py, agent_loop.py, app.py, cli, and test reconciliation in the order below.

## Recorded behavioral reconciliations (intended, not regressions)

- **R1 legacy outcome scope**: records already in the legacy `"capability"` idempotency scope are judged `LEGACY_OUTCOME_WITHOUT_RECEIPT → UNKNOWN`; crash-window double-write between the adapter's internal idempotency and the durable repo is accepted and fail-closed.
- **R2 run-path C7**: after the merge, a reentrant correction during run-path dispatch changes from "silently continues" to "aborts dispatch → UNKNOWN". This is an intentional strengthening of the main lineage behavior; the change is recorded, not hidden as "unchanged".
- **R3 receipt identity**: receipt_id is taken from the reservation (single identity), not freshly generated at seal.
- **R4 test reconciliation**: terminal_chat_loop.py (1078-line diff) and long_horizon_compensation.py require a bidirectional assertion checklist (each lineage's assertions preserved on the merged path) before the merge commit; recorded as an explicit gate item.

## Consequences

- `capability.py` becomes ~700+ lines (the merged broker); `WorkspaceSandbox.invoke(action, permit, correction)` is removed in favor of `execute` + broker; affected tests on both sides are updated to the single path.
- agent_loop (merged), task_service (merged), app.py (merged), action_pipeline (merged), execution.py (RunCoordinator unchanged except broker call shape) follow the single dispatch path.
- The merged test surface must pass: Python ~1800 (both lineages), Rust 21, Vitest 25, plus the Wave 1 E2E restart gate.
- This ADR does not authorize push, release, or any claim change; C7/evidence boundaries are preserved.

## Execution order (merge-design task)

1. capability.py reconciliation (this ADR) + its unit tests, independently reviewed.
2. execution.py (RunCoordinator call-shape), action_pipeline.py, task_service.py, agent_loop.py, app.py, cli — one file per gate, full regression, independent review.
3. Test-file reconciliation (terminal_chat_loop, long_horizon_compensation, surface suites).
4. Full suites + Wave 1 E2E + independent exact-head review of merged main; then the merge commit (no push without separate authorization).
