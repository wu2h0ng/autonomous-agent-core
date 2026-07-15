# ADM-P2 External Evaluation Receipts Implementation Evidence

> Date: 2026-07-15
> Track: Product / Translational contract slice
> Status: **IMPLEMENTED_LOCAL_EXTERNAL_EVALUATION_RECEIPTS_ONLY**
> Branch: `codex/adm-p2-evaluation-receipts-20260715`
> Frozen plan head: `be5a3034f1a0fbf3d46d34b6bc11695827b6ebd7`
> Implementation head: `4a523bd2c8ff9a97ce6d0d25f91969839756577a`

## Decision

ADM-P2 implements one bounded local Product capability: a separately authenticated
recorder may append and list an externally produced evaluation receipt for an inert
ADM-P1 `DomainCandidate`. The receipt is immutable, contract-bound, scope-bound,
append-only and C7-guarded. This slice records an evaluator's output; it does not invoke
an evaluator, call a provider, decide candidate quality, promote or activate a candidate,
create a domain prior, mutate Task/Run state or write workspace files.

## Real entry points and contracts

- `POST /v1/tasks/{candidate_task_id}/domain-candidates/{candidate_digest}/evaluations:record`
- `GET /v1/tasks/{candidate_task_id}/domain-candidates/{candidate_digest}/evaluations`
- `AgentOSApplication.record_domain_candidate_evaluation(...)`
- `AgentOSApplication.list_domain_candidate_evaluations(...)`
- `DomainCandidateEvaluationRecorder.record(...)`
- `DomainCandidateEvaluationRecorder.list_for_candidate(...)`

`CandidateEvaluationDraft` is a closed contract. It binds candidate/task/run/scope,
evaluator identity, evidence bundle and references, disposition, score or unresolved /
invalid reasons, confidence, parent receipt and submitted time. Disposition shape is
fail-closed. A model evaluator must bind provider, model, checkpoint and prompt digests;
fallback is literally `FORBIDDEN`.

`CandidateEvaluationReceipt` adds transaction-assigned version, deterministic identity,
derived idempotency and payload digests, recorder identity/time, observed correction
epochs and a Product-owned evaluation-contract digest. Its final digest covers every
field except itself and is mutation-sensitive.

## Authority and four-way separation

- Candidate builder, candidate sealer, external evaluator and receipt recorder must be
  distinct identities.
- The evaluator implementation digest cannot equal the candidate mechanism digest.
- Candidate generation and evaluation require distinct Task and Run identities.
- The recorder must own and accept the active evaluation Task commitment and cannot have
  `MODEL` or `PLUGIN` role.
- An exact active `domain.candidate.evaluate@1` `CapabilityGrant` must match principal,
  tenant and workspace and must not be expired or revoked.
- The evaluator type/version must match the frozen `ExpectedOutcome` and the evaluator
  reference must exist in the evaluation Task's `WorkflowGraph`.
- The caller cannot supply or override the evaluation-contract digest; Product code
  derives it from `ExpectedOutcome`, workflow evaluator refs and commitment authority
  scopes.

## Persistence, idempotency and C7

- `SQLiteCandidateEvaluationStore` is an isolated append-only receipt ledger using
  `BEGIN IMMEDIATE`, transaction-assigned versions, parent compare-and-swap and stable
  restart decoding.
- Derived-key idempotency runs before latest-parent CAS, so an exact old replay returns
  its original receipt even after the head advances. The same derived key with changed
  output is a conflict rather than a cached success.
- The six-segment record endpoint bypasses the generic HTTP response cache; the receipt
  ledger owns idempotency and conflict semantics.
- C7 halt is checked, an epoch vector is captured, and the same `CorrectionAuthority`
  guard rechecks and remains held through receipt append. The minimal `CorrectionGuard`
  Protocol changes typing only; production wiring still uses the lock-holding authority.
- This is same-authority, same-process linearization only. Cross-process or distributed
  correction/append atomicity is not claimed.

## No-mutation boundary

Recording or listing a receipt does not:

- append a Task event or change Task/Run/Workflow/Commitment state;
- update, replace or activate a `DomainCandidate`;
- write `WorkspaceSandbox` files;
- invoke a provider or execute evaluator code;
- create promotion, prior, configuration-snapshot or later-run authority.

Two separately authenticated `AgentOSApplication` instances sharing one SQLite file are
covered: one seals the candidate and the other records the receipt. Restart preserves the
receipt while Task events, candidate bytes and workspace bytes remain unchanged.

## Verification evidence

```text
.venv/bin/python -m pytest \
  tests/product/test_materialization_evaluation_contracts.py \
  tests/product/test_materialization_evaluation_persistence.py \
  tests/product/test_materialization_evaluation_service.py \
  tests/product/test_materialization_evaluation_api.py -q
30 passed

.venv/bin/python -m pytest tests/product -q
270 passed, 1 skipped in 26.79s

.venv/bin/ruff check apps packages/contracts/src packages/os_core/src tests/product
All checks passed!

.venv/bin/pyright apps packages/contracts/src packages/os_core/src tests/product
0 errors, 0 warnings, 0 informations

.venv/bin/python -m compileall -q apps packages/contracts/src packages/os_core/src
passed

git diff --check
passed
```

The final recorder/evaluator separation check was test-first: at `43ac9a9`,
`test_record_rejects_recorder_as_evaluator` failed because no denial was raised; after
the explicit identity check at `4a523bd`, it passes. Other bypass tests cover changed
payload under the same derived key, replay after a later head, stale parent CAS, route
scope override, grant status/scope/version/expiry, evaluator contract mismatch, mechanism
reuse, C7 halt/epoch drift, correction interleaving and generic-cache bypass.

A separate diagnostic `tests/product_eval -q` run produced `765 passed, 2 failed in
346.27s`. Both failures are the same pre-existing external-artifact expectations already
recorded for ADM-P1: tracked `fixed_baseline.py` and the parent SPINE-E2E-4 formal ledger
exist. ADM-P2 did not delete or reinterpret either historical artifact to make that suite
green.

## Independent technical review

Kimi Code reviewed the exact implementation repeatedly and remained read-only:

1. `be5a303..16f5dd0`, session
   `session_74de7cf2-d233-4f87-97b9-7fae7a4cde01`: `TECHNICAL_REVISE` for two
   test-typing P1s.
2. `be5a303..43ac9a9`, session
   `session_c7206cc9-45e2-4b6c-a8db-c554e186ed03`: those P1s were closed; one new P1
   identified missing recorder/evaluator identity separation.
3. `be5a303..4a523bd`, session
   `session_bfe0c5f5-4365-445b-a4a3-040c543f44e7`: `TECHNICAL_APPROVE`,
   `BLOCKERS: NONE`, `REQUIRED_FIXES: NONE`.

The review-approved ceiling is:

```text
ADM-P2 is IMPLEMENTED_LOCAL_EXTERNAL_EVALUATION_RECEIPTS_ONLY.
```

## Claim boundary

Authorized statement:

```text
ADM-P2 is IMPLEMENTED_LOCAL_EXTERNAL_EVALUATION_RECEIPTS_ONLY on the isolated feature
branch.
```

Not established: evaluator correctness or independence performance, model execution,
candidate quality, promotion, activation, `DomainPriorArtifact`, immutable Task
configuration, materializer acquisition, cross-domain transfer, adaptive competence,
self-improvement, Product Alpha, production readiness, autonomy, migration, push, merge
or release.

## Deferred successors

- ADM-P3: Product-owned promotion decision and immutable optional prior artifact.
- ADM-P4: immutable Task configuration snapshot and new-Task-only activation.
- ADM-P5: bounded materializer acquisition engine and one-way Research observation seam.
- Research falsifier: held-out cross-environment comparison against direct-model,
  retrieval and strong thin-prior baselines.
