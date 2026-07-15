# ADM-P3 Promotion Decision and Optional Prior Infrastructure Evidence

> Date: 2026-07-15
> Track: Product / Translational contract slice
> Status: **IMPLEMENTED_LOCAL_ADM_P3_INFRASTRUCTURE_ONLY / PRODUCTION_POLICY_V1_ALL_DEFER / NO_ACTIVATION**
> Branch: `codex/adm-p3-optional-domain-prior-20260715`
> Exact ADM-P2 ancestry: `9673c4bd9b5ca101c8bee51e806c20d0cb74a746`
> Approved plan checkpoint: `5b30696d5967fca343a8ac1a3d329fdb11abb9dc`
> Implementation commit: the single atomic commit containing this evidence file; its exact hash is recorded in the delegated handoff and Git history

## Decision

ADM-P3 implements one bounded local Product capability: a separately authenticated
fifth-party promoter may request a Product-owned deterministic decision over one inert
ADM-P1 `DomainCandidate` and its complete immutable ADM-P2 evaluation-receipt chain.
The caller supplies route and compare-and-swap coordinates only. It cannot submit a
verdict, threshold, score override, receipt subset, reason, policy, prior bytes or
activation instruction.

The production composition root registers only `ADM-P3-POLICY-V1`. That policy returns
`DEFER` for every receipt combination currently expressible by ADM-P2 because opaque
evidence references and identity labels do not prove evidence-byte custody or evaluator
independence. Therefore production ADM-P3 creates no `DomainPriorArtifact`. Closed,
deterministic policies defined only in tests exercise and falsify the atomic
`PROMOTE`-plus-inert-prior persistence boundary.

## Closed contracts and Product policy

The public contract family adds:

- `CandidatePromotionCommand`: route, scope, promotion Task/Run and exact evaluation /
  parent-decision heads only;
- `CandidatePromotionDecision`: transaction-assigned version and lineage, complete
  receipt-chain binding, deterministic disposition/reasons, policy version/digest,
  authenticated actor/time and C7 epochs;
- `DomainPriorArtifact`: candidate/promotion/receipt/policy lineage plus the exact R
  representation patch and provenance, with literal `state="INERT"`,
  `activation_authority="NONE"` and `uncertainty_behavior="PRESERVE"`;
- `CandidatePromotionResult`: requires a prior for `PROMOTE` and forbids one for
  `REJECT` or `DEFER`.

Contracts and persistence independently reject `PROMOTE` for an empty receipt chain.
Decision and prior digests are canonical and mutation-sensitive. Receipt digests are
ordered and unique, and the recorded head must equal the final receipt.

`PromotionPolicyV1` is pure and deterministic: it has no clock, store, provider, model,
tool, randomness or mutable configuration input. It records observed fail/invalid/
unresolved states as non-authoritative reasons and always adds the missing custody and
independence proofs before returning `DEFER`. The registry resolves only an exact
version/digest pair; the application exposes no policy injection surface.

## Shared ledger, atomicity and idempotency

`SQLiteAdaptationLedger` owns one SQLite connection and in-process transaction lock.
The evaluation and promotion stores borrow the same ledger in the production
composition root, allowing the promotion transaction to reload and validate the exact
receipt chain before writing. A store that creates a ledger owns and closes it; a store
given a shared ledger is a borrower and cannot close the owner's connection.

Inside one `BEGIN IMMEDIATE` transaction, the promotion store:

1. resolves an exact derived-idempotency replay before latest-parent CAS;
2. reloads and validates every receipt byte, contiguous version, parent digest and
   scope binding;
3. rechecks the evaluation head and latest promotion parent;
4. resolves the exact registered policy and recomputes its reduction;
5. appends an immutable decision;
6. only for a registered-policy `PROMOTE`, appends the inert prior before commit.

Same key with changed payload conflicts. A new decision requires a new receipt head and
the exact latest promotion parent. Any prior-construction or insert failure rolls back
the decision. This is local SQLite atomicity and same-authority, same-process C7
linearization; distributed transaction or general cross-process C7 atomicity is not
claimed.

## Fifth-party authority and C7

`DomainCandidatePromotionService` requires:

- an R-channel `CANDIDATE` sealed by the fixed Product sealer;
- a running promotion Task and Run distinct from candidate generation and every
  evaluation Task/Run;
- authenticated role `PRINCIPAL` or `TENANT_ADMIN`, with Goal creator and Commitment
  acceptor equal to the promoter;
- raw Commitment authority scope `domain.candidate.promote`;
- an active unexpired grant with `capability_id="domain.candidate.promote"` and separate
  `capability_version="1"`, exact principal/tenant/workspace and zero provider/tool
  budget;
- promoter identity distinct from candidate builder, Product sealer, every evaluator
  and every receipt recorder;
- C7 halt check, epoch snapshot and `guard_unchanged` held through the store
  transaction.

The promotion capability is not registered in `WorkspaceSandbox`; it is an internal
typed authority seam, not a tool or model capability.

## Real entry points and no-effect boundary

- `POST /v1/tasks/{candidate_task_id}/domain-candidates/{candidate_digest}/promotions:decide`
- `GET /v1/tasks/{candidate_task_id}/domain-candidates/{candidate_digest}/promotions`
- `GET /v1/tasks/{candidate_task_id}/domain-candidates/{candidate_digest}/domain-priors`
- matching `AgentOSApplication` methods and `DomainCandidatePromotionService`

The POST route bypasses the generic HTTP response cache; the promotion ledger owns
idempotency and conflict semantics. Stale evaluation heads, stale decision parents and
concurrent writes map to 409. Invalid caller-owned semantics map to 400; identity,
scope, grant and C7 denial map to 403; route-scoped absence maps to 404.

Deciding or listing does not append a Task event, mutate Task/Run/Workflow/Commitment,
change candidate or receipt bytes, write a workspace file, call a provider/tool,
execute an evaluator, create a configuration snapshot or activate a prior.

## TDD and verification evidence

The implementation was driven through explicit RED checkpoints:

- contract tests first failed at import because the promotion contracts were absent;
- policy tests first failed because the Product policy module was absent;
- persistence tests first failed because the shared ledger/store did not exist;
- service tests first failed because promotion errors/service did not exist;
- API tests first failed because application composition and routes were absent.

The final verification commands and results are:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:. python -m pytest \
  tests/product/test_materialization_contracts.py \
  tests/product/test_materialization_service.py \
  tests/product/test_materialization_api.py \
  tests/product/test_materialization_evaluation_contracts.py \
  tests/product/test_materialization_evaluation_persistence.py \
  tests/product/test_materialization_evaluation_service.py \
  tests/product/test_materialization_evaluation_api.py \
  tests/product/test_materialization_promotion_contracts.py \
  tests/product/test_materialization_promotion_policy.py \
  tests/product/test_materialization_promotion_persistence.py \
  tests/product/test_materialization_promotion_service.py \
  tests/product/test_materialization_promotion_api.py -q
226 passed

PYTHONPATH=packages/contracts/src:packages/os_core/src:. python -m pytest tests/product -q
419 passed, 1 skipped

python -m ruff check apps packages/contracts/src packages/os_core/src tests/product
All checks passed!

pyright apps packages/contracts/src packages/os_core/src tests/product
0 errors, 0 warnings, 0 informations

python -m compileall -q apps packages/contracts/src packages/os_core/src
passed

git diff --check
passed
```

Bypass-detecting tests cover forbidden caller fields, all current receipt-disposition
combinations, policy digest mismatch, malformed/reordered/cross-scope chains, exact old
store replay after the receipt head advances, changed payload under the same key, stale
head/parent, borrower close semantics, atomic rollback, fifth-party collisions, Task /
Run/grant/scope failures, C7 halt/epoch drift/interleaving, HTTP cache bypass, restart
decoding and absence of provider, workspace, candidate, receipt or Task effects.

## Independent technical review

Kimi Code approved the exact Goal Card, Architecture Brief and plan as `SPEC_APPROVE`
in session `session_4908b8a8-a26a-49bc-bb96-7ecf55ae2fd6`. The implementation review
was read-only against checkpoint `5b30696d` plus the complete working tree. Session
`session_a4e419b9-175c-4e85-a817-4c12638b0a09` returned
`TECHNICAL_APPROVE`, `BLOCKERS: NONE` and `REQUIRED_FIXES: NONE` after independently
rerunning 226 targeted tests, the 419-pass/1-skip Product suite, Ruff, Pyright,
compileall and `git diff --check`.

Its non-blocking risks are preserved: a future multi-process composition must re-prove
the process-local C7 boundary; `SQLiteAdaptationLedger` could harden its WAL-mode return
check; and future gateways must preserve the six-segment `:decide` route plus its HTTP
generic-cache exclusion. None changes the approved ADM-P3 local claim ceiling.

The reviewer also started `pytest tests -q --ignore=tests/product` as a diagnostic, but
that background task was killed when the Kimi session closed and produced no result.
It is not counted as verification evidence and this record makes no repository-wide
test claim.

## Claim boundary

Authorized statement:

```text
ADM-P3 is IMPLEMENTED_LOCAL_ADM_P3_INFRASTRUCTURE_ONLY on the isolated feature branch;
the production policy V1 is ALL_DEFER and ADM-P3 has NO_ACTIVATION authority.
```

Not established: evaluator correctness, evaluator performance or independence,
evidence-byte custody, candidate quality, production promotion, a production-created
optional prior, prior effectiveness, immutable Task configuration, later-run
activation, materializer acquisition, cross-domain transfer, adaptive competence,
self-improvement, Product Alpha, production readiness, autonomy, migration, push, merge
or release.

## Deferred successors

- ADM-P4: separately reviewed immutable Task configuration snapshot and new-Task-only
  activation; same-run activation remains forbidden.
- ADM-P5: bounded materializer acquisition and one-way Research observation seam.
- Research falsifier: held-out cross-environment comparisons against direct-model,
  retrieval and strong thin-prior baselines before any effectiveness claim.
