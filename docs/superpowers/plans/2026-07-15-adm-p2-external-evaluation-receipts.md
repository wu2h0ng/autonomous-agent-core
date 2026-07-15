# ADM-P2 External Candidate Evaluation Receipt Plan

> Status: **IMPLEMENTATION PLAN / SECOND TECHNICAL REVISE APPLIED / EXACT-BYTES RE-REVIEW REQUIRED / NO IMPLEMENTATION YET**
> Date: 2026-07-15
> Branch: `codex/adm-p2-evaluation-receipts-20260715`
> Base: `caf5bdf7090f6f9b83a922cc7d22a991d1dab4eb`
> Authority: ADR-0057 and the founder accelerated multi-lane decision
> Claim ceiling: `SPECIFIED_EXTERNAL_EVALUATION_RECEIPTS_ONLY`

## Goal

Add one real Product entry point that records and lists immutable evaluation receipts
for an existing inert `DomainCandidate`. The receipt must be written from a distinct
evaluation Task/Run, bind a closed evaluator identity and exact evidence/contract
digests, and pass the existing identity, scope and C7 spine.

ADM-P2 does **not** run an evaluator, decide that an evaluator is cognitively
independent, promote a candidate, create a prior, alter a graph, activate behavior or
authorize a later Run.

## Architecture

```text
sealed DomainCandidate (ADM-P1)
        |
distinct evaluation Task/Run + frozen ExpectedOutcome
        |
external evaluator output + evidence bundle
        |
authenticated non-builder recorder
        |
C7 snapshot/guard over evaluation Task/Run
        |
append-only CandidateEvaluationReceipt ledger
        |
inert receipt only -- no promotion/activation consumer in ADM-P2
```

The evaluator may be programmatic, human or model-based, but a model/plugin cannot
directly hold receipt-write authority. The authenticated recorder is a Product
principal, tenant admin or scoped worker. Model identity is bound as evidence; it is
not treated as authority or presumed independent.

## Non-negotiable boundaries

- Candidate task and evaluation task must be different.
- Candidate materialization Run and evaluation Run must be different.
- Receipt recorder principal and bound evaluator identity must differ from the
  candidate submitter and sealer; exact reuse of the candidate mechanism as the
  evaluator implementation is rejected.
- Evaluation Task/Run, candidate and recorder must share exact tenant/workspace scope.
- Evaluation Task and Run must be `RUNNING`; its Goal creator and Commitment acceptor
  must match the authenticated recorder, its Commitment must explicitly contain
  authority scope `domain.candidate.evaluate`, and its frozen `ExpectedOutcome`
  evaluator type/version must match the receipt evaluator identity. Its frozen
  `WorkflowGraph.evaluator_refs` must also contain the exact literal
  `evaluator:{evaluator_type}:{evaluator_version}`.
- The recorder must hold an unexpired active `CapabilityGrant` for
  `capability_id="domain.candidate.evaluate"` and `capability_version="1"` with
  exact principal/tenant/workspace scope. The ID and version are separate grant
  fields; `domain.candidate.evaluate:1` is never used as a capability ID.
- Evaluator fallback is literally `FORBIDDEN`; exact implementation,
  configuration, and model identity digests are bound.
- Product enforces identity binding and role separation only. It does not infer
  cognitive independence from provider/model/prompt names.
- Only a candidate with outcome `CANDIDATE` may receive an ADM-P2 receipt.
- The evaluation receipt store is separate from `TaskEventStore`; record/list must not
  append Task events or mutate Task, Run, WorkflowGraph, workspace, capability,
  policy, approval, audit, correction, candidate or evidence artifacts.
- Same evaluation idempotency key with different payload fails; parent receipt digest
  is compare-and-swap protected. The key is derived by the Product service under the
  literal schema `ADM-P2-IDEMPOTENCY-V1`; callers cannot supply or choose it.
- C7 halt and epoch drift are checked for capability
  `domain.candidate.evaluate` on the evaluation Task/Run, with the local guard held
  through append. This only linearizes changes made through the same
  `CorrectionAuthority` instance; cross-instance, cross-process and distributed
  atomicity remain unclaimed and must be closed before activation/promotion can use
  these receipts.
- No Research Track imports, provider calls, evaluator execution, promotion service,
  `DomainPriorArtifact`, `TaskConfigurationSnapshot`, migration, push, merge or release.

## Closed contracts

Add to `agent_os_contracts.materialization`:

```python
class CandidateEvaluationDisposition(str, Enum):
    EVALUATOR_PASS = "EVALUATOR_PASS"
    EVALUATOR_FAIL = "EVALUATOR_FAIL"
    UNRESOLVED = "UNRESOLVED"
    INVALID = "INVALID"


class CandidateEvaluatorKind(str, Enum):
    PROGRAMMATIC = "PROGRAMMATIC"
    HUMAN = "HUMAN"
    MODEL = "MODEL"


class CandidateEvaluatorIdentity(ContractModel):
    evaluator_id: NonEmptyStr
    evaluator_kind: CandidateEvaluatorKind
    evaluator_type: NonEmptyStr
    evaluator_version: NonEmptyStr
    implementation_digest: Sha256Digest
    configuration_digest: Sha256Digest
    provider_id: NonEmptyStr | None = None
    model_id: NonEmptyStr | None = None
    checkpoint_digest: Sha256Digest | None = None
    prompt_digest: Sha256Digest | None = None
    fallback_policy: Literal["FORBIDDEN"] = "FORBIDDEN"


class CandidateEvaluationDraft(ContractModel):
    candidate_digest: Sha256Digest
    candidate_task_id: NonEmptyStr
    evaluation_task_id: NonEmptyStr
    evaluation_run_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    evaluator: CandidateEvaluatorIdentity
    evidence_bundle_digest: Sha256Digest
    evidence_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    disposition: CandidateEvaluationDisposition
    score: float | None = None
    confidence: float
    unresolved_gaps: tuple[NonEmptyStr, ...] = ()
    invalidity_reasons: tuple[NonEmptyStr, ...] = ()
    parent_evaluation_digest: Sha256Digest | None = None
    submitted_at: UtcDateTime


class CandidateEvaluationReceipt(ContractModel):
    evaluation_id: NonEmptyStr
    evaluation_version: int
    evaluation_digest: Sha256Digest
    payload_digest: Sha256Digest
    idempotency_key: Sha256Digest
    recorded_by: NonEmptyStr
    recorded_at: UtcDateTime
    observed_correction_epochs: CorrectionEpochVector
    evaluation_contract_digest: Sha256Digest
    draft: CandidateEvaluationDraft
```

Contract validation:

- normalize and deduplicate evidence/gap/reason tuples;
- reject non-finite score/confidence; confidence is `[0, 1]`;
- `EVALUATOR_PASS` and `EVALUATOR_FAIL` require score and evidence; these values
  report the named evaluator's output and never mean Product verification;
- `UNRESOLVED` requires unresolved gaps and no verified claim;
- `INVALID` requires invalidity reasons;
- `MODEL` requires provider, model, checkpoint and prompt identity;
- `PROGRAMMATIC` and `HUMAN` forbid model/provider fields;
- candidate and evaluation task IDs must differ;
- receipt digest covers every final field except itself; the exported
  `candidate_evaluation_receipt_digest(payload)` helper is the only digest
  implementation, and `CandidateEvaluationReceipt` validates its
  `evaluation_digest` against that helper.

## Store and service

Add `CandidateStore.get_by_digest(...)` and a logically separate
`CandidateEvaluationStore` / `SQLiteCandidateEvaluationStore` in
`materialization_evaluation_persistence.py`.

The evaluation table stores `parent_evaluation_digest` and assigns the final
per-candidate version transactionally. Its unique keys are evaluation digest and
`(tenant, workspace, idempotency_key)`; its primary order is
`(tenant, workspace, candidate_digest, evaluation_version)`.

`CandidateEvaluationStore.append(..., expected_parent_digest)` uses one SQLite
`BEGIN IMMEDIATE` transaction and the following fixed order:

1. resolve an existing row by idempotency key; return it only when its
   `payload_digest` matches, otherwise raise `CandidateIdempotencyConflict`;
2. read the latest receipt for the exact tenant/workspace/candidate;
3. require `expected_parent_digest is None` iff no receipt exists; otherwise require
   it to equal the latest receipt's `evaluation_digest`;
4. on mismatch raise `CandidateConcurrentWrite` without inserting;
5. assign version `1` or `latest.evaluation_version + 1`, persist the exact parent,
   construct/validate the final digest-bound receipt, then commit.

This ordering preserves a genuine retry of an older successful request even after a
later version exists, while every new append is latest-parent CAS protected.

The POST draft cannot contain or override `evaluation_contract_digest`. After loading
the evaluation Task, the Product service computes it under the literal schema
`ADM-P2-EVALUATION-CONTRACT-V1` over the canonical frozen `ExpectedOutcome`, the
canonical frozen `WorkflowGraph.evaluator_refs`, and the Commitment authority scopes.
The service then computes `payload_digest` under
`ADM-P2-BOUND-PAYLOAD-V1` over the canonical draft, this service-computed contract
digest and the authenticated `recorded_by` principal. It derives the idempotency key
from schema literal, tenant/workspace, candidate digest, evaluation Task/Run, evaluator
identity digest, the service-computed evaluation contract digest, evidence bundle
digest, parent evaluation digest, authenticated `recorded_by` and contract schema
version. Thus two principals never receive a receipt that names the other principal as
recorder. The store constructs the final versioned receipt and uses
`candidate_evaluation_receipt_digest(...)` to compute `evaluation_digest` over every
final field except `evaluation_digest` itself. Caller-provided contract, payload,
idempotency, version or receipt digests are invalid input, not hints.

Add `DomainCandidateEvaluationRecorder` in `materialization_evaluation.py`:

1. load candidate by exact digest and scope, then require
   `candidate.draft.task_id == candidate_task_id` from the route; a mismatch is
   indistinguishable from absence and returns 404;
2. reject non-`CANDIDATE` outcomes;
3. load evaluation Task and exact Run;
4. explicitly require both
   `candidate.draft.task_id != evaluation_task_id` and
   `candidate.draft.materialization_run_id != evaluation_run_id`;
5. require exact tenant/workspace and reject recorder roles `MODEL` and `PLUGIN`;
6. require evaluation Goal creator and Commitment acceptor to equal the recorder;
7. require Commitment authority scope `domain.candidate.evaluate`;
8. use the existing `AgentOSApplication.grants` registry to validate the recorder's active,
   unexpired `CapabilityGrant(capability_id="domain.candidate.evaluate",
   capability_version="1")` against principal, tenant and workspace;
9. reject recorder/evaluator identities equal to candidate submitter or sealer and
   reject evaluator implementation digest equal to the candidate mechanism digest;
10. match evaluation Task `ExpectedOutcome.evaluator_type/version` to evaluator
    identity and require its WorkflowGraph evaluator refs to contain the exact
    `evaluator:{type}:{version}` binding;
11. compute the evaluation contract digest from the loaded frozen Product contracts,
    then bind it with evaluator identity, external evidence digest/refs, disposition
    and parent digest; no request field can override the computed digest;
12. check C7, capture epochs and hold `guard_unchanged` while calling store append
    with `draft.parent_evaluation_digest` as `expected_parent_digest`;
13. return an inert immutable receipt.

The evidence bundle remains externally stored in ADM-P2. Product records its exact
digest and references but does not claim to possess or independently verify those
bytes. Missing durable evidence custody therefore prevents any later promotion and is
an explicit successor requirement, not silently backfilled by the receipt.

Listing requires candidate existence and exact principal tenant/workspace scope. It
does not imply acceptance or expose a promotion endpoint.

## HTTP and composition root

Allow `AgentOSApplication(..., principal: PrincipalIdentity | None = None,
evaluation_grant: CapabilityGrant | None = None)` so tests and future authentication
adapters can compose a distinct evaluator recorder and grant while the default local
principal remains unchanged. The local default grant is narrow, internal-transactional,
created by a dedicated `_build_evaluation_grant`, inserted into the existing
`AgentOSApplication.grants` mapping, scoped only to
`capability_id="domain.candidate.evaluate"` / `capability_version="1"`, and is
independently revocable/expiring. It is deliberately not added to
`WorkspaceSandbox.specs()` because recording an internal Product ledger fact is not a
workspace connector capability. `evaluation_grant` is composition-root/local-test
injection, not an alternate production authorization path; injected grants are subject
to the same validation. Any grant-registry rebuild, including workspace attachment,
must preserve or deliberately rebuild this separate evaluation grant.

Add:

```text
POST /v1/tasks/{candidate_task_id}/domain-candidates/{candidate_digest}/evaluations:record
GET  /v1/tasks/{candidate_task_id}/domain-candidates/{candidate_digest}/evaluations
```

The POST body may not override path candidate task/digest. Both endpoints use the
application's authenticated principal. Modify
`apps/api_server/server.py::_uses_generic_http_idempotency(path)` so both
`/domain-candidates:seal` and `/evaluations:record` return `False`; the evaluation
ledger, not the generic HTTP response cache, owns record retry/conflict semantics.

Error mapping:

- scope/role/C7/task-state/independence denial -> 403;
- stale parent or same-key/different-payload -> 409;
- invalid contract/disposition/evaluator identity -> 400;
- missing Task or candidate -> 404.

## Test-first tasks

### Task 1: contracts

Files:

- modify `packages/contracts/src/agent_os_contracts/materialization.py`
- modify `packages/contracts/src/agent_os_contracts/__init__.py`
- add `tests/product/test_materialization_evaluation_contracts.py`

RED tests must kill open schemas, unbound model identity, allowed fallback, invalid
disposition shapes, same Task identity, non-finite values, caller-supplied contract
digests and receipt digest omission/mismatch. The receipt digest validator and helper
must be mutation-sensitive to every final field other than `evaluation_digest`.

### Task 2: persistence

Files:

- modify `packages/os_core/src/agent_os_core/materialization_persistence.py`
- add `packages/os_core/src/agent_os_core/materialization_evaluation_persistence.py`
- add `tests/product/test_materialization_evaluation_persistence.py`

RED tests must kill payload mismatch, same-key/different-payload, stale-parent append,
wrong candidate scope, missing-parent-with-existing-head, parent-on-first-write,
transaction/version non-determinism, idempotent replay after a later version and restart
instability.

### Task 3: Product service and C7

Files:

- add `packages/os_core/src/agent_os_core/materialization_evaluation.py`
- modify `packages/os_core/src/agent_os_core/__init__.py`
- add `tests/product/test_materialization_evaluation_service.py`

RED tests must kill same-task/same-run evaluation, same recorder/builder/evaluator
identity, exact mechanism/evaluator implementation reuse, MODEL/PLUGIN direct writer,
missing authority scope, missing/revoked/expired/mismatched capability grant, Goal or
Commitment author mismatch, missing or mismatched WorkflowGraph evaluator ref, scope
mismatch, evaluator mismatch, route candidate-task mismatch, candidate materialization
Run reuse, caller contract-digest override, cross-recorder idempotency aliasing,
candidate non-CANDIDATE, Task/Run
non-running, C7 halt/epoch drift and correction interleaving during append.
The interleaving test must fail before the C7 guard is held through append.

### Task 4: real application and HTTP entry points

Files:

- modify `apps/api_server/app.py`
- modify `apps/api_server/server.py`
- add `tests/product/test_materialization_evaluation_api.py`

Tests use two `AgentOSApplication` instances with the same SQLite database but distinct
authenticated principals. Candidate creation completes before the evaluator app records
the receipt; C7 interleaving tests use the evaluator app's single authority instance and
must not imply cross-instance atomicity. Tests must prove record/list/restart behavior, path binding,
typed errors, generic-cache bypass, no Task event, no candidate mutation and no
workspace mutation. No provider call is allowed.

All verification commands below run from the Agent OS worktree root, not from
`apps/api_server/`.

### Task 5: verification and truth update

Run:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest \
  tests/product/test_materialization_evaluation_contracts.py \
  tests/product/test_materialization_evaluation_persistence.py \
  tests/product/test_materialization_evaluation_service.py \
  tests/product/test_materialization_evaluation_api.py -q

PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest tests/product -q

../../.venv/bin/python -m ruff check \
  apps packages/os_core/src packages/contracts/src tests/product

../../.venv/bin/python -m pyright \
  apps packages/os_core/src packages/contracts/src

git diff --check
```

Update `docs/CURRENT_STATE.yaml`, `codebase_index.md` and a dated ADM-P2 evidence
record only after tests pass and independent exact-diff review closes P0/P1 findings.

## Completion ceiling

The only authorized completion statement is:

```text
ADM-P2 is IMPLEMENTED_LOCAL_EXTERNAL_EVALUATION_RECEIPTS_ONLY.
```

It means Agent OS can immutably record and list a scoped external evaluation fact. It
does not mean the evaluator is correct or cognitively independent, the candidate is
accepted, domain adaptation works, promotion/activation is authorized, or any Product,
research, autonomy, training, migration or release claim has advanced.
