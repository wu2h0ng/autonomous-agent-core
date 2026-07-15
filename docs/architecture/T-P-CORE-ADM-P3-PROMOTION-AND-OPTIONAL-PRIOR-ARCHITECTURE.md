# T-P-CORE-ADM-P3 Architecture Brief — Promotion Decision and Optional Prior

> Date: 2026-07-15
> Status: **ARCHITECTURE_PROPOSED / REVIEW_REQUIRED / NO_RUNTIME_AUTHORIZATION**
> Track: Product / Translational
> Base: `9673c4bd9b5ca101c8bee51e806c20d0cb74a746`
> Goal Card: `docs/product/GC-ADM-P3-PROMOTION-AND-OPTIONAL-PRIOR-2026-07-15.md`
> Governing ADR: `docs/adr/ADR-0057-adaptive-domain-materialization-and-optional-priors.md`

## 1. Decision

Use one deterministic Product-owned reducer over one immutable candidate and the
complete immutable evaluation-receipt chain. Persist the reducer result in an isolated
append-only promotion ledger. When, and only when, a registered Product policy returns
`PROMOTE`, construct an inert `DomainPriorArtifact` from the candidate bytes and bind it
to the decision in the same SQLite transaction.

The HTTP caller supplies compare-and-swap coordinates, never decision semantics.

```text
ADM-P1 DomainCandidate
        +
ADM-P2 complete receipt chain at exact latest head
        |
authenticated fifth-party promoter
        |
promotion Task/Run + exact typed grant + C7 guard
        |
closed Product policy registry -> deterministic reducer
        |
        +---- REJECT -> append decision only
        |
        +---- DEFER  -> append decision only
        |
        +---- PROMOTE -> append decision + inert prior atomically
                                      |
                                      +-- no consumer in ADM-P3
```

## 2. Rejected designs

1. **Caller-authored verdict or threshold** — rejected because it converts a typed
   Product decision into self-approval or policy injection.
2. **Caller-selected receipt subset** — rejected because it permits cherry-picking and
   makes the decision non-reproducible.
3. **Separate decision and publication transactions** — rejected because a crash can
   leave `PROMOTE` without its required prior or a prior without a valid decision.
4. **Count reviewer/model names as independence** — rejected because identity labels do
   not prove evaluator independence.
5. **Treat evidence reference strings as custody proof** — rejected because ADM-P2 does
   not verify or retain the referenced bytes.
6. **Apply the prior immediately** — rejected because ADM-P3 has no configuration
   snapshot or activation authority and same-run activation is forbidden by ADR-0057.

## 3. Closed command and result contracts

`CandidatePromotionCommand` contains only:

```python
class CandidatePromotionCommand(ContractModel):
    candidate_digest: Sha256Digest
    candidate_task_id: NonEmptyStr
    promotion_task_id: NonEmptyStr
    promotion_run_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    expected_evaluation_head_digest: Sha256Digest | None = None
    expected_parent_promotion_digest: Sha256Digest | None = None
```

`ContractModel(extra="forbid")` makes `disposition`, `threshold`, `score`,
`evaluation_receipt_digests`, `reason_codes`, `policy`, `prior`, `activate` and unknown
fields invalid input.

`CandidatePromotionDecision` binds:

- transaction-assigned per-candidate version and exact parent decision digest;
- candidate, candidate Task, promotion Task/Run and tenant/workspace;
- the complete receipt-chain digest, ordered receipt digests and exact latest head;
- `REJECT`, `DEFER` or `PROMOTE` plus deterministic reason codes;
- Product policy version and digest;
- derived payload/idempotency digests;
- authenticated promoter, decision time and C7 epoch vector;
- a deterministic prior artifact ID only for `PROMOTE`.

`DomainPriorArtifact` binds:

- transaction-assigned prior version and prior parent digest;
- candidate/payload digest, promotion decision digest and receipt-chain digest;
- the candidate's exact R-channel `RepresentationPatch` and provenance;
- tenant/workspace, Product policy digest, publisher/time and C7 epochs;
- literal `state="INERT"`, `activation_authority="NONE"` and
  `uncertainty_behavior="PRESERVE"`.

The closed schema has no capability grant, credential, policy override, evaluator,
Task/Run configuration, active workflow or execution field. Its content is a generic R
representation prior only; domain-specific semantics remain outside Agent Core.

`CandidatePromotionResult` requires a prior for `PROMOTE` and forbids one for
`REJECT`/`DEFER`.

## 4. Product policy V1

The production composition root registers exactly `ADM-P3-POLICY-V1`. Its canonical
policy specification is hashed and the digest is stored in every decision. The store
looks up the exact registered `(version, digest)` and recomputes the reduction over the
transactionally reloaded full receipt chain.

The fixed V1 precedence is:

```text
DEFER(
    zero or more observations that carry no Product verdict authority:
      "NO_EVALUATION_RECEIPTS"
      "RECORDED_EVALUATOR_FAIL_UNADJUDICATED"
      "EVALUATION_INVALID"
      "EVALUATION_UNRESOLVED"
    and always:
      "EVIDENCE_BYTES_CUSTODY_UNPROVEN"
      "EVALUATOR_INDEPENDENCE_UNPROVEN"
      "PROMOTION_PROOFS_UNAVAILABLE_IN_ADM_P2"
)
```

Therefore `ADM-P3-POLICY-V1` has no reachable `REJECT` or `PROMOTE` branch. Multiple
pass/fail receipts, distinct names, distinct implementation digests or opaque evidence
refs do not change that result. A future production policy may make `REJECT` or
`PROMOTE` reachable only through a separately reviewed typed proof contract and
registered policy version; modifying V1 in place is forbidden.

The store still implements and tests the `PROMOTE` atomicity invariant with a closed,
deterministic policy defined only in the persistence test module and explicitly
registered in that test store. `AgentOSApplication` exposes no policy injection surface
and registers production V1 only.

## 5. Complete-chain and concurrency model

The promotion service never accepts receipt digests from the caller. It loads all
receipts for the exact candidate in version order and validates:

- versions are contiguous from 1;
- each parent digest equals the preceding receipt digest;
- every receipt binds the same candidate, candidate Task, tenant and workspace;
- the command head is `None` iff the chain is empty, otherwise it equals the final
  receipt digest;
- no receipt Task/Run equals the candidate or promotion Task/Run.

`SQLiteCandidateEvaluationStore` and `SQLiteCandidatePromotionStore` share a small
`SQLiteAdaptationLedger` connection/lock object in one process. The promotion store uses
one `BEGIN IMMEDIATE` transaction to reload the complete receipt chain, recheck its
head, validate parent-decision CAS, recompute the registered policy result, append the
decision and, for `PROMOTE`, append the prior before commit.

Derived idempotency is checked before latest-parent CAS so an exact retry can return its
original decision after the chain advances. Same key/different payload fails. A new
decision requires a new receipt head and the exact latest parent decision. Prior
version/parent are transaction-assigned and never caller-selected.

The digest schemas are fixed:

- `ADM-P3-RECEIPT-CHAIN-V1` covers candidate digest plus every canonical receipt in
  version order;
- `ADM-P3-BOUND-PAYLOAD-V1` covers the closed command, canonical candidate,
  full-chain digest, exact registered policy version/digest, recomputed reduction and
  authenticated promoter;
- `ADM-P3-IDEMPOTENCY-V1` covers tenant/workspace, candidate, promotion Task/Run,
  expected receipt head, expected parent decision, policy version/digest, promoter and
  command schema version;
- prior payload/digest covers the exact decision, candidate R patch/provenance and
  transaction-assigned prior lineage. Callers supply none of these digests.

The shared ledger also makes the existing default `:memory:` application composition
see the same evaluation and promotion tables. File-backed independent processes remain
serialized by SQLite `BEGIN IMMEDIATE`; distributed databases and general
cross-process C7 atomicity are not claimed.

## 6. Identity, authority and C7

`DomainCandidatePromotionService` requires:

1. candidate outcome `CANDIDATE`, R channel, exact route and scope;
2. promotion Task and Run both `RUNNING`;
3. promotion Task/Run distinct from candidate and every evaluation Task/Run;
4. authenticated promoter role `PRINCIPAL` or `TENANT_ADMIN`;
5. Goal creator and Commitment acceptor equal the promoter;
6. Commitment authority scope `domain.candidate.promote`;
7. active, unexpired exact principal/tenant/workspace grant for
   `domain.candidate.promote@1`;
8. promoter differs from candidate submitter, fixed Product sealer, every evaluator and
   every receipt recorder;
9. C7 halt check, epoch snapshot and same-authority `guard_unchanged` held through the
   store transaction.

This is same-instance, same-process correction/append linearization. It does not grant
the prior C7, capability or activation authority.

## 7. Entry points and non-mutation

Real entry points:

```text
POST /v1/tasks/{candidate_task_id}/domain-candidates/{candidate_digest}/promotions:decide
GET  /v1/tasks/{candidate_task_id}/domain-candidates/{candidate_digest}/promotions
GET  /v1/tasks/{candidate_task_id}/domain-candidates/{candidate_digest}/domain-priors
```

The POST endpoint bypasses the generic HTTP response cache; the promotion ledger owns
idempotency and conflicts. Successful `REJECT`/`DEFER` returns the immutable decision
with `prior=null`. A future registered production policy could return a decision and
prior together; ADM-P3 V1 cannot.

Decision and list operations do not append Task events, mutate Task/Run/Workflow,
change candidate or evaluation bytes, write workspace artifacts, invoke an evaluator,
call a provider/tool, create a configuration snapshot or activate a prior.

## 8. Failure semantics

- 400: invalid/open command or contract shape;
- 403: role, identity, task state, grant, scope authority, non-candidate or C7 denial;
- 404: candidate or route-scoped record absent;
- 409: stale evaluation head, stale parent decision, chain drift, idempotency conflict
  or concurrent append;
- 201: immutable `REJECT`, `DEFER` or registered-policy `PROMOTE` result, including an
  exact idempotent POST replay of the original ledger result;
- 200: read-only list result.

`REJECT` and `DEFER` are Product decisions, not transport failures.

## 9. Verification boundary

Bypass-detecting tests must prove caller verdict/subset rejection, full-chain loading,
policy digest recomputation, V1 all-DEFER behavior, fifth-party separation, exact grant,
C7 interleaving resistance, derived idempotency, latest-head and parent CAS, atomic
decision/prior rollback and complete non-mutation/no-provider behavior.

Even after implementation, the maximum claim is a local Product structural slice. It
does not establish evaluator correctness, evidence custody, candidate quality, domain
adaptation, prior effectiveness, activation, transfer, autonomy, production readiness,
migration, push, merge or release.
