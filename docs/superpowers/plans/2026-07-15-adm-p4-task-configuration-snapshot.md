# ADM-P4 Immutable Task Configuration Snapshot Implementation Plan

> **For Codex:** execute only after exact-plan Kimi verdict `SPEC_APPROVE`. Use strict
> RED-GREEN-REFACTOR. Do not implement a best-effort Run binding.

**Goal:** Add one immutable Product-owned configuration snapshot for a committed new
Task, optionally bind one same-scope inert ADM-P3 prior, and require a later Run to bind
the exact snapshot without changing runtime behavior.

**Architecture:** Store the snapshot as `TASK_CONFIGURATION_SNAPSHOT_SEALED` in the
existing Task event stream. Resolve all authoritative content from Product state. Bind
the reserved Run with snapshot ID/digest in `RUN_STARTED`. Hold the existing local C7
guard through both appends. The prior remains reference-only and is never passed to
provider, policy or capabilities.

**Stack:** Python 3.12, Pydantic v2 frozen contracts, existing Task event stores,
existing ADM-P1/P2/P3 read stores, pytest, ruff, pyright.

**Exact base:** `7e76461aec8e96b4d1016f7fec3ddfc9b13d7ce2`

**Baseline:** `419 passed, 1 skipped` in Product suite.

## Frozen boundaries

- Production `PromotionPolicyV1` remains all-`DEFER`; production code never fabricates
  a prior.
- Caller input is only optional prior locator and later snapshot ID.
- Snapshot fields are Product-derived and immutable.
- No prior application, WorkflowGraph mutation, tool/model change, grant widening,
  provider/tool call, Research import, L4/L5, push, merge or release.
- Same Task/Run source consumption is forbidden.
- If exact Task-event/Run binding fails, stop and implement only `NOT_BOUND` downgrade.

## Task 1: Freeze contract tests (RED)

**Files:**

- Create: `tests/product/test_task_configuration_contracts.py`
- Create: `packages/contracts/src/agent_os_contracts/task_configuration.py`
- Modify: `packages/contracts/src/agent_os_contracts/runtime.py`
- Modify: `packages/contracts/src/agent_os_contracts/__init__.py`

**Step 1: Write failing tests**

Cover:

1. `DomainPriorSelector` rejects every extra authoritative/activation field.
2. `DomainPriorBinding` rejects non-inert state, altered receipt head/chain,
   provenance digest drift and duplicate source receipts.
3. `TaskConfigurationSnapshot` rejects wrong snapshot/workflow/policy/provider/grant/
   expected-outcome digests, scope mismatch, duplicate capability grants, inactive
   grants and a non-reference prior.
4. Mutating any nested field fails because all contracts are frozen.
5. `AgentRun` requires snapshot ID and digest as a pair.

Run:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  .venv/bin/python -m pytest -q tests/product/test_task_configuration_contracts.py
```

Expected: fail on missing contracts/fields.

**Step 2: Implement minimum contracts**

Define:

- `DomainPriorSelector`
- `PriorEvaluationSource`
- `DomainPriorBinding`
- `TaskConfigurationSnapshotCommand`
- `TaskConfigurationSnapshot`
- `domain_prior_binding_digest(...)`
- `task_configuration_snapshot_digest(...)`

Use `content_digest` and model validators. Add the paired snapshot fields to
`AgentRun`. Export public contracts.

**Step 3: Run tests GREEN and refactor**

Keep canonical ordering inside validators and digest helpers. Do not add mutable
builders or caller-facing factory arguments for authoritative fields.

## Task 2: Freeze Task aggregate and service binding (RED)

**Files:**

- Modify: `tests/product/test_task_aggregate.py`
- Modify: `tests/product/test_task_service.py`
- Modify: `packages/contracts/src/agent_os_contracts/runtime.py`
- Modify: `packages/os_core/src/agent_os_core/task_aggregate.py`
- Modify: `packages/os_core/src/agent_os_core/task_service.py`

**Step 1: Write failing aggregate tests**

Cover:

- snapshot event only after `TASK_COMMITTED` and before `RUN_STARTED`;
- one snapshot maximum;
- malformed digest and committed-contract drift fail during rehydration;
- applying the event preserves `COMMITTED` status;
- `RUN_STARTED` requires exact snapshot ID/digest/reserved Run ID when snapshot exists;
- legacy Task without a snapshot still starts;
- snapshot-bound Task cannot replan.

**Step 2: Write failing service tests**

Cover `TaskService.seal_configuration_snapshot(...)` append/CAS and
`start_run(..., configuration_snapshot=...)` exact binding. Confirm wrong or absent
snapshot fails before an event append.

**Step 3: Implement minimum event/state-machine change**

- Add `TASK_CONFIGURATION_SNAPSHOT_SEALED`.
- Add `configuration_snapshot` to `TaskAggregate`.
- Add aggregate draft builder and event application/validation.
- Extend `TaskService.start_run` to accept a trusted resolved snapshot and use its
  reserved Run ID.
- Reject replan for snapshot-bound runs.

Run:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  .venv/bin/python -m pytest -q \
  tests/product/test_task_aggregate.py \
  tests/product/test_task_service.py
```

## Task 3: Freeze Product-owned policy/config derivation (RED)

**Files:**

- Create: `tests/product/test_task_configuration_service.py`
- Create: `packages/os_core/src/agent_os_core/task_configuration.py`
- Modify: `packages/os_core/src/agent_os_core/governance.py`
- Modify: `packages/os_core/src/agent_os_core/errors.py`
- Modify: `packages/os_core/src/agent_os_core/__init__.py`

**Step 1: Add closed error taxonomy**

Add `TaskConfigurationError`, `TaskConfigurationNotFound`,
`TaskConfigurationDenied`, `TaskConfigurationScopeMismatch`,
`TaskConfigurationConflict`, `TaskConfigurationNotBound` and
`TaskConfigurationDrift`.

**Step 2: Write failing no-prior service tests**

Cover:

- Task must be committed, unstarted, unexpired and unsnapshotted;
- principal role/scope/Goal creator/Commitment acceptor checks;
- raw authority scope and exact `task.configuration.snapshot@1` grant checks;
- required workflow grants are derived, active, unexpired and exact scope;
- workflow, policy descriptor, provider profile, grants and expected outcome are
  captured from Product state rather than command;
- unsupported policy version fails closed;
- exact replay returns same snapshot; changed selector conflicts;
- C7 halt and a correction interleaving immediately before append are detected;
- concurrent Task append is detected by CAS;
- seal invokes no provider/tool and appends exactly one snapshot Task event.

**Step 3: Implement Product-owned derivation**

Add constants:

```text
TASK_CONFIGURATION_CAPABILITY = task.configuration.snapshot
TASK_CONFIGURATION_CAPABILITY_VERSION = 1
POLICY_KERNEL_V1_SPEC
POLICY_KERNEL_V1_DIGEST
```

The policy digest is explicitly a contract descriptor digest, not code attestation.
Implement `TaskConfigurationSnapshotService` with read ports for candidate,
evaluation and promotion stores, but keep prior resolution separate until Task 4.

Run:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  .venv/bin/python -m pytest -q \
  tests/product/test_task_configuration_service.py -k 'not prior'
```

## Task 4: Freeze optional-prior resolution and separation (RED)

**Files:**

- Modify: `tests/product/test_task_configuration_service.py`
- Modify: `packages/os_core/src/agent_os_core/task_configuration.py`
- If a narrow read method is required, modify:
  `packages/os_core/src/agent_os_core/materialization_promotion_persistence.py`

**Step 1: Build a closed test-only promoted prior fixture**

Reuse the existing ADM-P3 test policy pattern to create a valid candidate, complete
evaluation chain, `PROMOTE` decision and inert prior in local test stores. Do not add
the policy to the production registry or application constructor.

**Step 2: Write failing tests**

Cover:

- valid prior binds exact id/digest/candidate/promotion/receipt-chain/provenance;
- selector resolves from the injected same-scope stores, never request content;
- missing prior/candidate/decision/receipt fails closed;
- incomplete, gapped, reordered or changed receipt chain fails closed;
- non-`PROMOTE`, wrong prior ID, altered policy/patch/provenance or non-inert prior
  fails closed;
- cross-tenant/workspace prior is hidden/rejected;
- consumer Task/reserved Run differs from materialization, every evaluation and
  promotion Task/Run;
- a source Task/Run cannot consume its own prior;
- production `PromotionPolicyV1` yields no prior and the app does not synthesize one.

**Step 3: Implement minimum resolver**

Load immutable artifacts using store read ports. Recompute every lineage digest and
construct `DomainPriorBinding`. Do not expose source-store rows or accept artifact
objects in the command.

Run:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  .venv/bin/python -m pytest -q \
  tests/product/test_task_configuration_service.py
```

## Task 5: Freeze application and execution preflight (RED)

**Files:**

- Create: `tests/product/test_task_configuration_application.py`
- Modify: `apps/api_server/app.py`
- Modify: `packages/os_core/src/agent_os_core/task_configuration.py`
- Modify only if required: `packages/os_core/src/agent_os_core/execution.py`

**Step 1: Write failing integration tests**

Cover:

- composition root wires the existing Task store, correction authority and ADM stores;
- app adds exact snapshot capability grant without widening workflow grants;
- seal/get/list work across a SQLite restart;
- start requires exact snapshot ID and uses reserved Run ID;
- wrong/missing ID, changed workflow/policy/provider/grant/expected-outcome or changed
  C7 epochs fails before `RUN_STARTED` or before any provider/tool call;
- prior binding is absent from provider requests, allowed capabilities, policy inputs
  and tool arguments;
- snapshot-bound Task cannot be auto-started by `run_task` without snapshot ID;
- legacy no-snapshot path remains compatible.

**Step 2: Implement application wiring**

Add `seal_task_configuration`, `get_task_configuration`,
`list_task_configurations`, and snapshot-aware `start_run`/`run_task`. The Product
service performs preflight. Do not teach `RunCoordinator` to interpret a prior.

Run:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  .venv/bin/python -m pytest -q \
  tests/product/test_task_configuration_application.py
```

## Task 6: Freeze HTTP closed surface (RED)

**Files:**

- Create: `tests/product/test_task_configuration_api.py`
- Modify: `apps/api_server/server.py`

**Step 1: Write failing API tests**

Cover:

- seal/get/list routes and exact JSON contracts;
- seal rejects body Task/scope/config/digest/grant/policy/provider/prior-content and
  activation fields;
- start/run accepts snapshot ID only and rejects snapshot body/digest;
- generic HTTP idempotency cache is bypassed for seal and bound start;
- 403/404/409 mapping is deterministic;
- replay and restart return exact snapshot bytes/digest.

**Step 2: Implement minimum routing**

Parse path Task ID as authority. Pass only validated command and snapshot ID to the
application. Never default missing snapshot ID for a snapshotted Task.

Run:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  .venv/bin/python -m pytest -q \
  tests/product/test_task_configuration_api.py
```

## Task 7: Bypass suite and compatibility regression

**Files:**

- Modify only tests needed to preserve existing public behavior.

Run targeted bypass set:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  .venv/bin/python -m pytest -q \
  tests/product/test_task_configuration_contracts.py \
  tests/product/test_task_configuration_service.py \
  tests/product/test_task_configuration_application.py \
  tests/product/test_task_configuration_api.py \
  tests/product/test_task_aggregate.py \
  tests/product/test_task_service.py \
  tests/product/test_materialization_promotion_contracts.py \
  tests/product/test_materialization_promotion_service.py \
  tests/product/test_materialization_promotion_api.py
```

Explicit mutation checks must demonstrate that tests fail when:

- snapshot validation returns a constant;
- the sealer accepts caller digests or artifacts;
- prior lineage validation is skipped;
- source/current Task separation is removed;
- C7 recheck is moved outside the append guard;
- start ignores snapshot ID/digest/reserved Run;
- preflight silently accepts config drift;
- prior bytes are added to provider/tool inputs.

## Task 8: Full verification and documentation truth

**Files:**

- Create after implementation: `docs/product/PM-ADM-P4-TASK-CONFIGURATION-SNAPSHOT-2026-07-15.md`
- Modify: `docs/CURRENT_STATE.yaml`
- Modify only if routing requires: relevant product index/plan.

Run:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  .venv/bin/python -m pytest -q tests/product
.venv/bin/python -m ruff check \
  packages/contracts/src packages/os_core/src apps tests/product
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  .venv/bin/python -m pyright \
  packages/contracts/src packages/os_core/src apps tests/product
.venv/bin/python -m compileall -q \
  packages/contracts/src packages/os_core/src apps tests/product
git diff --check
git status --short
```

Record exact counts and limitations. Do not upgrade claims based on green tests alone.

## Task 9: Exact implementation review and atomic finalization

1. Commit runtime/tests/docs as one atomic implementation commit after the reviewed
   plan checkpoint.
2. Confirm clean exact implementation head.
3. Ask Kimi for read-only exact-head technical review with no file mutation and no
   background tests.
4. Require literal `TECHNICAL_APPROVE`; otherwise keep branch `HOLD` and repair through
   a new reviewed diff.
5. Report plan head, Kimi plan session/verdict, implementation head, exact test/lint/
   type/compile evidence and claim ceiling.
6. Do not push, merge, migrate, activate or release.
