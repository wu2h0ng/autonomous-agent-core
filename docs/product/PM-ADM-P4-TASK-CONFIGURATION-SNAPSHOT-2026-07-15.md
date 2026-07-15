# ADM-P4 Immutable Task Configuration Snapshot Evidence

> Date: 2026-07-15
> Track: Product / Translational contract slice
> Status: **IMPLEMENTED_LOCAL_PENDING_EXACT_HEAD_REREVIEW / REFERENCE_ONLY / NO_ACTIVATION**
> Branch: `codex/adm-p4-task-configuration-snapshot-20260715`
> Exact ADM-P3 base: `7e76461aec8e96b4d1016f7fec3ddfc9b13d7ce2`
> Approved exact-plan checkpoint: `b0aeab5c40fdb784ea1efc7a5b5cc6b412f03e49`
> Initial implementation commit: `625e0a64b283581dab0dc76baa853ad2abff012a`
> Review-remediation commit: the atomic fix commit containing the updated evidence;
> its exact hash is reported in the delegated handoff

## Decision

ADM-P4 implements one bounded local Product capability: a committed, unstarted Task
may seal one immutable Product-derived `TaskConfigurationSnapshot`, and its later Run
must bind the exact snapshot ID/digest and use the Run ID reserved at seal time.

The snapshot records the exact committed workflow, Product policy descriptor,
provider profile, active workflow execution grants, ExpectedOutcome/evidence contract
and C7 epoch vector. It may also record one same-scope ADM-P3 inert prior as an exact
lineage reference. The prior is not applied, interpreted or passed to execution.

Production `PromotionPolicyV1` remains all-`DEFER`; therefore the production
composition root cannot create a prior and never synthesizes one. A closed deterministic
policy defined only in tests creates a valid inert fixture to falsify optional-prior
binding and failure paths.

## Closed caller surface and derived authority

The seal command accepts only an optional `DomainPriorSelector` containing source
candidate Task ID, candidate digest and prior artifact ID. The consumer Task ID comes
from the route. The caller cannot supply snapshot content/digest, Run ID, workflow,
policy, provider, grants, outcome/evidence, epochs, prior bytes/lineage or activation
fields.

`TaskConfigurationSnapshotService` derives and rechecks:

- Task state, Goal creator, Commitment acceptor, tenant/workspace and raw authority;
- exact active `task.configuration.snapshot@1` authority grant;
- committed `WorkflowGraph` plus canonical digest;
- Product-owned `policy-1` descriptor plus canonical digest;
- point-in-time `ProviderProfile` plus canonical digest;
- exactly one active, unexpired, same-principal/same-scope grant for each workflow tool
  capability, whose version matches the Product capability registry, plus canonical
  grant-set digest;
- committed `ExpectedOutcome`, including its evidence requirements, plus digest;
- Product-reserved Run ID and C7 Task/Run/capability epoch vector.

Snapshot contracts are frozen, extra-field-forbidden and self-digesting. They reject
inactive or duplicate capability grants, scope drift, contract/digest drift, non-inert
prior state and consumer Task/Run reuse of any prior source.

## Optional-prior lineage and source separation

The selector is only a locator. The resolver reloads the exact same-scope candidate,
version-contiguous evaluation receipts, `PROMOTE` decision and inert prior from the
existing ADM-P1/P2/P3 stores. It recomputes candidate, receipt, chain, promotion, prior,
representation-patch and provenance bindings before constructing `DomainPriorBinding`.

The binding records exact candidate/materialization, evaluation and promotion Task/Run
coordinates; receipt chain; policy; patch digest; full provenance and provenance
digest. A later append-only receipt does not rewrite or invalidate an older selected
prior: the resolver binds the exact receipt prefix named by that immutable prior while
still validating the complete current store chain for gaps or corruption.

The consumer Task ID and reserved Run ID must differ from the candidate/materialization,
every selected evaluation and promotion Task/Run. This rule is enforced both by the
Product resolver and the persisted snapshot contract, so event rehydration cannot
silently accept self-consumption.

## Task event and exact Run binding

`TASK_CONFIGURATION_SNAPSHOT_SEALED` is a first-class event in the existing Task
stream. Existing expected-sequence CAS supplies one-snapshot-per-Task ordering and
SQLite restart rehydration. Exact replay returns the persisted `snapshot_id`,
`sealed_at` and digest; a changed selector conflicts rather than rebuilding.

`AgentRun` has paired `configuration_snapshot_id` and
`configuration_snapshot_digest` fields. For a snapshotted Task, `TaskService`,
`TaskAggregate`, application auto-start and HTTP start all require the exact snapshot
ID, use its reserved Run ID and reject a missing/mismatched digest or provider binding.
Legacy Tasks without a snapshot retain their existing start path. Snapshot-bound Runs
cannot replan in ADM-P4.

Before `RUN_STARTED` and before coordinator construction, the Product service compares
the live workflow, policy, provider, grants, outcome, optional-prior lineage and C7
epochs against the sealed snapshot. Any change fails closed. Snapshot/prior fields are
reserved from runtime inputs and are not added to `ProviderRequest`, policy input,
candidate envelopes, action contracts, capability-broker input or tool arguments.

## Concurrency and failure boundary

The composition root owns one re-entrant configuration lock shared by seal, bound
start/preflight, `attach_workspace` and the provider-config commit. Seal and start hold
that lock and the same `CorrectionAuthority.guard_unchanged` through their Task-event
append. They reload the Task and rederive Product bindings immediately before append.
The service obtains a fresh clock value after entering the C7 guard, revalidates
Commitment/grant expiry at that linearization point and constructs the persisted
snapshot from that guarded derivation. An expiry that crosses the guard boundary cannot
append `TASK_CONFIGURATION_SNAPSHOT_SEALED` or `RUN_STARTED`.
The coordinator receives the selected provider/sandbox objects and a copied grant map
under the same lock.

This establishes same-instance non-interleaving plus Task-stream CAS only. Provider
profiles and grants are point-in-time Product objects, not a durable configuration
ledger; after restart or reconfiguration, get/list still rehydrate exact snapshot bytes
but bound start/run may correctly fail on live drift. Cross-process C7/configuration
atomicity is not claimed.

Deterministic HTTP mappings are 403 for authority/scope denial, 404 for route-scoped
absence and 409 for replay, binding, drift or CAS conflict. Seal/start/run bypass the
generic HTTP response cache; Product event replay and exact binding remain authoritative.

## Real entry points

- `POST /v1/tasks/{task_id}/configuration-snapshots:seal`
- `GET /v1/tasks/{task_id}/configuration-snapshots`
- `GET /v1/tasks/{task_id}/configuration-snapshots/{snapshot_id}`
- `POST /v1/tasks/{task_id}/start` with exact `configuration_snapshot_id`
- `POST /v1/tasks/{task_id}/run` with exact `configuration_snapshot_id`
- matching `AgentOSApplication`, `TaskConfigurationSnapshotService`, `TaskService` and
  Task aggregate paths

Seal/get/list/start perform no provider or workspace-tool call. The prior remains
reference-only and cannot change workflow, policy, provider/model, grants, tools or
execution semantics.

## TDD and verification evidence

Explicit RED checkpoints covered missing contracts, missing aggregate seal/start
binding, missing Product derivation service, unimplemented optional-prior resolution,
missing exact bound start, absent application/HTTP surfaces, later-receipt invalidation,
source/current Task/Run reuse, duplicate grants and runtime-input leakage. Review
remediation added four independently red tests: seal/start expiry crossing at C7 guard
entry, a valid workflow capability version other than the sealer version and a grant/spec
version mismatch. It also strengthened digest sensitivity, authoritative-field rejection,
receipt-lineage tamper and every reserved prior/runtime-input key.

Final local verification on the implementation working tree:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:. python -m pytest -q \
  tests/product/test_task_configuration_contracts.py \
  tests/product/test_task_configuration_task_binding.py \
  tests/product/test_task_configuration_service.py \
  tests/product/test_task_configuration_application.py \
  tests/product/test_task_configuration_api.py \
  tests/product/test_task_aggregate.py \
  tests/product/test_task_service.py \
  tests/product/test_materialization_promotion_contracts.py \
  tests/product/test_materialization_promotion_service.py \
  tests/product/test_materialization_promotion_api.py
130 passed

PYTHONPATH=packages/contracts/src:packages/os_core/src:. python -m pytest -q \
  tests/product
473 passed, 1 skipped, 2 failed

The two failures are pre-existing time/environment drift in
`tests/product/test_materialization_evaluation_api.py`: its fixed `NOW` makes the
evaluation grant expired relative to the live HTTP application clock, producing 403 in
`test_http_records_lists_and_restarts_without_mutating_product_state` and
`test_record_endpoint_bypasses_generic_http_idempotency_cache`. Kimi independently
observed the same two failures on the unremediated exact implementation head. They are
outside ADM-P4 and were not modified in this fix commit.

python -m ruff check packages/contracts/src packages/os_core/src apps tests/product
All checks passed!

PYTHONPATH=packages/contracts/src:packages/os_core/src:. pyright \
  packages/contracts/src packages/os_core/src apps tests/product
0 errors, 0 warnings, 0 informations

python -m compileall -q packages/contracts/src packages/os_core/src apps tests/product
passed

git diff --check
passed
```

The 130-test bypass set includes exact event rehydration, legacy compatibility, C7 and
configuration drift, full optional-prior lineage, later receipt append, source
separation, guard-entry expiry races, capability-spec version binding, restart reads,
shared-lock exclusion, HTTP cache bypass, caller-field and runtime-input rejection. All
ADM-P4 and adjacent ADM-P1/P2/P3 checks pass; the full Product suite is not represented
as green because of the two named pre-existing fixed-time failures.

## Independent review gate

Kimi Code exact-plan review session
`session_0b624b48-fc74-49db-9476-feb2e09827a9` first returned `SPEC_REVISE` for six
concrete gaps: full in-guard rederivation, exact replay, mutable profile/grant drift,
legacy start/run bypass, HTTP/idempotency ordering and execution-input leakage. The
revised exact plan at `b0aeab5` addressed them and the same session returned
`SPEC_APPROVE` with no open blockers.

The same Kimi session began a read-only exact-head review of `625e0a64`; it completed
four technical slices but was stopped at the 15-minute hard timeout before emitting a
verdict. It had already confirmed one blocker: seal/start reused a pre-guard timestamp
for guarded expiry checks. It also required real workflow capability-version binding
instead of using the sealer's fixed version and requested stronger mutation coverage.
This remediation closes those exact findings. The branch remains `HOLD` until the same
reviewer identity reviews the new exact head and returns literal `TECHNICAL_APPROVE`.

## Claim boundary

Authorized before independent implementation review:

```text
ADM-P4 is IMPLEMENTED_LOCAL_PENDING_EXACT_HEAD_REREVIEW as an immutable Product Task
configuration and exact later-Run reference binding only; it has NO_ACTIVATION authority.
```

Not established: production-created prior, prior usefulness, adaptation, learning,
transfer, candidate application, representation mutation, new capability acquisition,
evaluator correctness/custody/independence, cross-process atomicity, Product Alpha,
production readiness, autonomy, general intelligence, migration, push, merge or release.
