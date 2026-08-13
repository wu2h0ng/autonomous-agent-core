# ADR-0059: Merged main Capability Execution Authority Reconciliation

- Status: **Accepted** (founder decision 2026-08-13, merge route A; founder review verdict REVISE_TO_SPEC resolved)
- Date: 2026-08-13
- Deciders: founder (architecture decision confirmed at wave lineage head `f88d08e9`)
- Context: `docs/adr/ADR-0058` accepted; merge assessment `.agent_runs/native-surface-wave2a-20260812/merge-assessment.md`; independent review `.superpowers/sdd/2026-08-11-agent-os-native-surface-wave2a/adr-0059-review-2.md` (APPROVE with amendments); founder review (REVISE_TO_SPEC with 4 P1 + 1 P2, resolved below)

## Context

`main` (terminal-coding-agent lineage, `cf2af7ee`) and the wave lineage (`codex/native-surface-wave2a-macos-shell-20260812`, `5256c566`) both implement the capability execution authority, with complementary rather than competing mechanisms:

- **main** `CapabilityBroker.invoke(action, permit, attempt)` (capability.py, 101 lines): permit/epoch/correction checks inside the broker, then `connector.execute(action) -> CapabilityEffect` and builds an `ActionReceipt`. Repository/filesystem/subprocess implementations live in `domain_packs/developer_agent/DeveloperWorkspaceAdapter` (structure tests forbid WorkspaceSandbox in Core). Heavy durable machinery lives in `RunCoordinator` (execution.py): run leases, effect custody, automatic compensation, interrupt handling.
- **wave** `WorkspaceSandbox.invoke(action, permit, correction, execution_lease=...)`: the durable reservation → lease-fenced dispatch → receipt/outcome seal spine (`DurableActionOutcomeRepository`), typed `CapabilityEffectUnknown` fail-closed, and C7 dispatch linearization (`guard_unchanged`) — for the chat/approval path.

## Options Considered

1. **Union by duplication**: keep both `invoke` paths and route by caller. Rejected: two execution paths for one spine — a bypass risk.
2. **Wave spine wins**: `WorkspaceSandbox.invoke` becomes the only dispatch path. Rejected: violates main's Agent Core / Developer domain-pack boundary (Core must stay workspace-free).
3. **Main shape wins, wave spine grafted in (RECOMMENDED, KEPT)**: `CapabilityPort.execute` + `CapabilityBroker.invoke(action, permit, attempt, *, execution_claim=...)` is the ONLY dispatch path; the durable spine runs inside the broker; workspace implementations stay in the Developer domain pack.

## Decision

**Option 3** with the founder's REVISE_TO_SPEC corrections:

### Execution claim (P1: unify lease/claim)

- `CapabilityBroker.invoke(action, permit, attempt=1, *, execution_claim=...)` **requires an execution claim on every production dispatch**. There is NO `None` default for production callers; the broker refuses dispatch without one (fail-closed).
- The claim carries `{run_id, owner, fence, expires_at}` (the wave `ExecutionLease` shape) and is atomically validated by the outcome store: the lease-fenced reservation insert fails unless the exact claim is the current active lease.
- **RunCoordinator converts its existing run-lease owner/fence/expiry into the claim** at dispatch time instead of passing `None`; `lease_fence_fn` is replaced by claim construction from the run lease. The approval continuation path also passes an explicit claim.
- Broker invariant: `claim.fence == permit.lease_fence` and `claim.run_id == action.run_id`, checked before reservation.

### Agent Core / Developer domain-pack boundary (P1)

- Core (`packages/os_core/src/agent_os_core/capability.py`) keeps ONLY the generic authority spine: `CapabilityBroker` (checks + reservation + guarded dispatch + seal), `DurableActionOutcomeRepository`, `CapabilityPort` protocol (`specs`/`execute`/`replay`/`outcomes`/`preflight`/lease claim primitives), `CapabilityResult`, `CapabilityEffect`, errors. **Core must not contain WorkspaceSandbox or workspace-specific preflight/execute/reconcile** — main's structure tests are honored.
- `WorkspaceSandbox` machinery (allowlist/path preflight, workspace dispatch, cached-effect reconcile) moves into `domain_packs/developer_agent/` and merges with `DeveloperWorkspaceAdapter` as the single workspace connector.

### UNKNOWN exception contract (P1)

- The dispatch chain is strictly: **preflight (deterministic deny, before reserve) → broker reserve → guarded connector execute → broker seal**.
- After reservation begins, ANY exception from the connector propagates to the broker and is converted to typed `CapabilityEffectUnknown` (never `FAILED`), with the reservation kept unsealed and never auto-resent.
- The connector's legacy authoritative idempotency is removed: `DeveloperWorkspaceAdapter.execute` no longer maintains its own replay/write ledger and no longer catches-all to `FAILED`; replay/reservation/outcome authority belongs to the broker's outcome repository. (Legacy records in the `"capability"` scope remain readable as `LEGACY_OUTCOME_WITHOUT_RECEIPT → UNKNOWN`, fail-closed.)

### RunCoordinator UNKNOWN state machine (P1)

- `execution.py` is NOT a broker call-shape change only. On `CapabilityEffectUnknown` from the broker:
  - the Run is marked unresolved/paused (no `RUN_FAILED` auto-finalization);
  - the run execution claim/lease is released;
  - automatic resend and automatic compensation are **forbidden** for that action and prior actions in the chain;
  - the task waits for external reconciliation (typed `HelpRequest`-style surface / operator review).
- Deterministic `CapabilityDenied`/permit/correction errors keep the existing failure + compensation behavior.

### Recorded behavioral reconciliations

- **R1 legacy outcome scope**: legacy `"capability"`-scope records → `LEGACY_OUTCOME_WITHOUT_RECEIPT → UNKNOWN`, fail-closed.
- **R2 run-path C7**: reentrant correction during dispatch aborts → UNKNOWN (intentional strengthening, recorded).
- **R3 receipt identity**: sealed receipt reuses the reservation's `receipt_id`.
- **R4 test reconciliation**: terminal_chat_loop.py and long_horizon_compensation.py need a bidirectional assertion checklist before the merge commit (explicit gate).
- **R5 claim everywhere**: all production dispatch call sites (RunCoordinator, ActionPipeline, approval continuation) pass an explicit execution claim; no production `None`.

## Amended merge file list

- `packages/os_core/src/agent_os_core/persistence.py` — lease-fenced idempotency primitives (auto-merge carries them)
- `packages/os_core/src/agent_os_core/postgres.py` — Postgres equivalents
- `packages/os_core/src/agent_os_core/_action_outcome.py` — `DurableActionOutcomeRepository`, `ExecutionLease`, `ExecutionLeaseConflict`
- `packages/os_core/src/agent_os_core/governance.py` — `guard_unchanged` + `CorrectionGuardConflict`
- `packages/os_core/src/agent_os_core/capability.py` — generic broker + protocol ONLY (workspace-free)
- `domain_packs/developer_agent/workspace_capability.py` — `WorkspaceSandbox` merged into the workspace connector (preflight/execute/reconcile)
- `packages/os_core/src/agent_os_core/execution.py` — RunCoordinator claim construction + UNKNOWN branch
- `packages/os_core/src/agent_os_core/action_pipeline.py`, `task_service.py`, `agent_loop.py`, `apps/api_server/app.py`, `apps/cli/__main__.py` — single dispatch path
- test reconciliation (terminal_chat_loop, long_horizon_compensation, surface suites)

## Consequences

- Core `capability.py` stays generic (~150-200 lines); the workspace connector grows in the domain pack.
- RunCoordinator behavior changes are bounded to the UNKNOWN branch (no auto-compensation on unknown effects); existing deterministic failure behavior unchanged.
- The merged test surface must pass: Python ~1800 (both lineages), Rust 21, Vitest 25, plus the Wave 1 E2E restart gate.
- This ADR does not authorize push, release, or any claim change; C7/evidence boundaries are preserved.

## Execution order (merge-design task)

1. capability.py generic broker + protocol; domain-pack connector merge (WorkspaceSandbox → domain_packs); both with unit tests, independently reviewed.
2. execution.py (claim construction + UNKNOWN branch), then action_pipeline.py, task_service.py, agent_loop.py, app.py, cli — one file per gate, full regression, independent review.
3. Test reconciliation (bidirectional assertion checklist).
4. Full suites + Wave 1 E2E + independent exact-head review of merged main; then the merge commit (no push without separate authorization).
