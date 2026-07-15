# T-P-CORE ADM-P4 — Immutable Task Configuration Snapshot Architecture

> Date: 2026-07-15
> Track: Product / Translational
> Status: **DESIGN_READY / AWAITING_KIMI_SPEC_REVIEW**
> Exact base: `7e76461aec8e96b4d1016f7fec3ddfc9b13d7ce2`
> Runtime authority: none until exact-plan `SPEC_APPROVE`

## 1. Decision

ADM-P4 adds a Product-owned immutable `TaskConfigurationSnapshot` as a first-class
event in the existing Task event stream. One committed consumer Task may seal one
snapshot before Run start. A later `RUN_STARTED` event must bind the exact snapshot ID
and digest and must use the Run ID reserved by that snapshot.

An optional ADM-P3 prior is represented only as a read-only lineage binding. It is not
an instruction, configuration patch, capability, policy, tool or model choice.

## 2. Alternatives considered

### A. Task-stream snapshot event — selected

`TASK_CONFIGURATION_SNAPSHOT_SEALED` is appended to the consumer Task stream with the
existing expected-sequence CAS. `TaskAggregate` rehydrates and validates it. The same
aggregate validates the later `RUN_STARTED` snapshot binding.

Why selected:

- one authoritative state machine instead of a second Task authority spine;
- crash-safe append and immutable history already exist in both in-memory and SQLite
  adapters;
- same-instance C7 guard can cover all checks through the append linearization point;
- Run start can compare exact snapshot bytes/digest in the same aggregate;
- restart behavior follows existing event rehydration semantics.

### B. Separate snapshot table plus two-phase Run binding — rejected

A second SQLite table/connection would require a distributed transaction with the Task
event store to claim atomic binding. A write to one side followed by failure on the
other creates ambiguous truth. ADM-P4 must not introduce that failure mode.

### C. Embed snapshot only inside `RUN_STARTED` — rejected

This would provide no independently sealable, inspectable or listable configuration
contract before execution. It also collapses configuration approval and Run start into
one opaque operation and cannot meet seal/get/list requirements.

### Mandatory downgrade

If implementation evidence disproves option A, the only allowed downgrade is a closed
immutable snapshot ledger whose Run-start API returns explicit `NOT_BOUND`. It may not
claim Task/Run integration.

## 3. New contracts

All contracts extend frozen `ContractModel(extra="forbid")`.

### 3.1 `DomainPriorSelector`

The only caller-controlled prior coordinate:

```text
candidate_task_id
candidate_digest
prior_artifact_id
```

It carries no prior content, digest override, receipt subset, promotion decision or
activation field.

### 3.2 `PriorEvaluationSource`

One exact source receipt coordinate derived from ADM-P2:

```text
evaluation_task_id
evaluation_run_id
evaluation_digest
evaluator_id
recorded_by
```

### 3.3 `DomainPriorBinding`

Derived only by the Product sealer:

```text
prior_artifact_id / prior_version / prior_digest
candidate_id / candidate_task_id / materialization_run_id
candidate_digest / candidate_payload_digest
promotion_id / promotion_task_id / promotion_run_id / promotion_digest
evaluation_head_digest / evaluation_receipt_digests / receipt_chain_digest
evaluation_sources[]
representation_patch_digest
provenance[] / provenance_digest
policy_digest
source_state = INERT
source_activation_authority = NONE
consumption_mode = REFERENCE_ONLY
```

The binding includes exact provenance values and their digest. It does not embed an
executable workflow mutation. The prior digest continues to bind the full immutable
source artifact, including its representation patch.

### 3.4 `TaskConfigurationSnapshotCommand`

```text
prior_selector: DomainPriorSelector | null
```

The consumer Task ID comes from the route. Principal/scope and every authoritative
configuration field come from Product state.

### 3.5 `TaskConfigurationSnapshot`

```text
snapshot_id / snapshot_version = 1 / snapshot_digest
seal_request_digest
consumer_task_id / reserved_run_id / commitment_id
tenant_id / workspace_id / principal_id
workflow / workflow_digest
policy_version / policy_digest
provider_profile / provider_profile_digest
execution_grants[] / execution_grants_digest
expected_outcome / expected_outcome_digest
observed_correction_epochs
optional_prior: DomainPriorBinding | null
sealed_by / sealed_at
state = SEALED
prior_consumption_mode = REFERENCE_ONLY
```

`snapshot_digest` is the canonical SHA-256 digest of every field except itself. Grant
ordering is canonical by `(capability_id, capability_version, grant_id)`. Contract
validation rejects duplicate capability-version bindings, digest mismatch, scope drift,
workflow/expected-outcome mismatch, inactive grants and any non-inert prior binding.

`snapshot_id` is a Product-generated UUID-like identifier created once for the winning
append. `seal_request_digest` is derived only from the consumer Task route and the
optional `DomainPriorSelector`. Because `snapshot_digest` includes `snapshot_id`,
`sealed_at` and every binding, replay must return the already persisted event; it must
never reconstruct a nominally equivalent snapshot.

## 4. Product policy digest

`PolicyKernel` currently exposes only `policy_version`. ADM-P4 adds a Product-owned
canonical descriptor and digest for the admitted `policy-1` contract. The digest is a
digest of the declared policy contract, not a source-code or binary attestation. An
unsupported policy version fails closed; the caller cannot register or select a policy.

## 5. Seal service

`TaskConfigurationSnapshotService` receives the composition root's one re-entrant
configuration lock and configuration-reader callback. Its `seal(...)` enters that lock
itself; `configure_provider`, `attach_workspace`, bound start and bound-run preflight
use the same lock. A direct service call therefore cannot omit the lock. It executes:

1. Load the Task aggregate and require `COMMITTED`, no Run and no existing snapshot.
2. Require Goal, Commitment, Workflow and ExpectedOutcome.
3. Require exact principal tenant/workspace, role, Goal creator and Commitment acceptor.
4. Require raw Commitment scope `task.configuration.snapshot`.
5. Validate the exact active/unexpired `task.configuration.snapshot@1` grant.
6. Reserve a Product-generated Run ID.
7. Under the configuration lock, derive point-in-time workflow, policy, provider,
   execution-grant and expected-outcome bindings.
8. If a selector exists, resolve and revalidate the prior lineage from the injected
   ADM-P1/P2/P3 read ports in the same tenant/workspace.
9. Require consumer Task/reserved Run to differ from every source Task/Run.
10. Read C7 epochs for consumer Task/reserved Run/snapshot capability and reject halt.
11. Construct the self-validating immutable snapshot.
12. Enter `CorrectionAuthority.guard_unchanged(...)` without releasing the
    configuration lock. Reload the Task and rederive **all** Product-owned bindings:
    Task state/sequence, identity, authority scope, seal grant, workflow, policy
    descriptor, provider profile, execution grants and expected outcome. Compare them
    with the candidate snapshot and fail closed on any difference, then append the
    snapshot event with expected Task sequence while both guards remain held.

The service owns deterministic replay. Once a snapshot exists, it rehydrates the exact
event and compares `seal_request_digest`; a match returns the persisted object and a
difference raises an idempotency conflict. If concurrent sealers race, the CAS loser
rehydrates the winner and applies the same comparison. It never regenerates
`snapshot_id`, `sealed_at` or `snapshot_digest`. Generic HTTP idempotency does not cache
this route.

## 6. Prior resolution and lineage revalidation

The selector is only a locator. The resolver must load:

- the exact candidate from `CandidateStore`;
- the complete version-contiguous evaluation chain from `CandidateEvaluationStore`;
- the exact `PROMOTE` decision and prior from `CandidatePromotionStore`.

It then revalidates all of the following:

- tenant/workspace and candidate route;
- prior ID/digest and candidate/promotion bindings;
- promotion disposition is `PROMOTE` and names that prior;
- receipt IDs/digests, exact head and receipt-chain digest;
- candidate payload and representation-patch digests;
- full provenance and provenance digest;
- `state="INERT"`, `activation_authority="NONE"` and uncertainty preservation;
- source Task/Run disjointness from the consumer Task/reserved Run.

The service never accepts a prior-like body from the caller. Production policy V1
cannot create a prior; the production app therefore returns not found for a fabricated
selector and never invents one.

## 7. Task aggregate and event semantics

Add `TASK_CONFIGURATION_SNAPSHOT_SEALED` before `RUN_STARTED`.

`TaskAggregate` gains `configuration_snapshot` and validates:

- event occurs only in `COMMITTED` state before any Run;
- there is no prior snapshot in the stream;
- Task/Commitment/Workflow/ExpectedOutcome/scope bindings are exact;
- snapshot digest is valid;
- applying the event does not change Task status.

Malformed, duplicate, post-start or drifted events make rehydration fail closed.

## 8. Run binding

`AgentRun` gains optional paired fields:

```text
configuration_snapshot_id
configuration_snapshot_digest
```

Both must be present or absent. `TaskService.start_run` receives a full resolved
snapshot from the Product service, never caller-provided bytes. For a snapshot-bound
Task it must:

- require the caller's selector to match the sealed snapshot ID;
- use `reserved_run_id`;
- copy exact snapshot ID/digest into `AgentRun`;
- preserve existing commitment/workflow/expected-outcome/provider/policy checks;
- append only after Product preflight revalidates C7, identity, grants and live config.

The aggregate rejects `RUN_STARTED` when the snapshot is absent, mismatched, stale or
bound to another Run. If a Task already has a snapshot, legacy start without its ID
fails closed. Tasks with no snapshot remain legacy-compatible in this bounded slice.
This rejection is enforced inside `TaskService.start_run` and `TaskAggregate`, not only
at HTTP/application edges; direct service calls and `run_task` auto-start cannot bypass
the binding.

Before any provider/tool call, `AgentOSApplication.run_task` repeats the immutable
binding preflight. It compares exact workflow, policy descriptor, provider profile,
execution grants, expected outcome and C7 epochs. The prior is not consumed by
`RunCoordinator` and is not passed to the provider or capability broker.

For a snapshot-bound Task, the preflight and construction of `RunCoordinator` occur
under the same composition-root configuration lock. The coordinator receives the
already selected provider/sandbox objects and a copied grant mapping, so a later
composition-root update cannot silently change that run's objects. The following are
strictly forbidden from `ProviderRequest`, `CandidateGenerationEnvelope`, `PolicyInput`,
`ActionContract`, capability-broker input and tool arguments:

```text
configuration_snapshot_id
configuration_snapshot_digest
optional_prior
any prior content or lineage field
```

Snapshot-bound runs cannot use the existing in-run replan path in ADM-P4. A changed
workflow requires a future new Task/Run and new snapshot contract.

## 9. HTTP surface

```text
POST /v1/tasks/{task_id}/configuration-snapshots:seal
GET  /v1/tasks/{task_id}/configuration-snapshots
GET  /v1/tasks/{task_id}/configuration-snapshots/{snapshot_id}
POST /v1/tasks/{task_id}/start  {"configuration_snapshot_id": "..."}
POST /v1/tasks/{task_id}/run    {"configuration_snapshot_id": "...", ...existing inputs...}
```

The seal body accepts only the optional selector. Get/list are read-only. Start/run
accept only the snapshot ID, never snapshot content or digests. Error mapping separates
403 authority/scope failures, 404 missing Task/prior/snapshot and 409 replay/state/CAS
conflicts.

The router must match `configuration-snapshots*` and bound start/run routes before the
existing split-based fallback. Seal and bound start are explicitly added to the generic
HTTP-idempotency exclusion list; Product event replay/CAS remains authoritative.

## 10. C7 and concurrency boundary

Seal and bound start both use the composition root's existing `CorrectionAuthority`,
Task store and shared configuration lock. Each holds the configuration lock and
`guard_unchanged` through its Task-event append. Configuration-mutating application
paths use the same lock. This proves same-process/same-authority non-interleaving only.
It does not prove cross-process atomicity. SQLite Task-stream CAS independently
prevents competing Task appends.

`ProviderProfile` and the grant mapping are not durable ledgers in the current Product;
the snapshot therefore stores explicit point-in-time copies. A later
`configure_provider` or `attach_workspace` is allowed to update the composition root,
but cannot update the snapshot and causes bound start/run drift checks to fail closed.

## 11. Failure semantics

Fail closed on:

- uncommitted, expired, running or already snapshotted Task;
- missing/mismatched identity, scope, authority or grant;
- missing workflow capability grant or inactive/expired grant;
- unsupported policy version or any digest drift;
- missing/malformed/mismatched prior lineage;
- source/current Task or Run reuse;
- C7 halt/epoch change;
- concurrent Task append;
- missing/wrong snapshot ID at start;
- snapshot/live-config drift before start or execution;
- any attempt to replan a snapshot-bound Run.

No failure path falls back to an unbound Run or silently drops the selected prior.

## 12. Claim boundary

Passing ADM-P4 proves only a local Product-owned immutable configuration snapshot and
exact later Task/Run reference binding. It does not prove prior usefulness, adaptation,
learning, transfer, autonomy, intelligence, production readiness, distributed safety,
activation, migration or release.
