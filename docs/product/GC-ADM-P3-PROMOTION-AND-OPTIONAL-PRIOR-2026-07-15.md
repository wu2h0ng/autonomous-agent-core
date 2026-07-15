# ADM-P3 Goal Card — Product Promotion Decision and Optional Domain Prior

> Date: 2026-07-15
> Track: Product / Translational
> Status: **GOAL_CARD_PROPOSED / PLAN_REVIEW_REQUIRED / NO_IMPLEMENTATION_AUTHORITY**
> Branch: `codex/adm-p3-optional-domain-prior-20260715`
> Exact base: `9673c4bd9b5ca101c8bee51e806c20d0cb74a746`
> Authority: ADR-0057; ADM-P1 and ADM-P2 implementation evidence
> Claim ceiling before implementation review: `SPECIFIED_ADM_P3_ONLY`

## Goal

Build the next bounded Product-owned seam after ADM-P1 and ADM-P2: a deterministic,
versioned and digest-bound promotion reducer that consumes one immutable ADM-P1
`DomainCandidate` and its complete ADM-P2 evaluation-receipt chain, records an
append-only `REJECT`, `DEFER` or `PROMOTE` decision, and atomically creates one inert
immutable `DomainPriorArtifact` only when a registered Product policy returns
`PROMOTE`.

ADM-P3 must make it impossible for an API caller, model, plugin, candidate builder,
candidate sealer, evaluator or receipt recorder to choose the verdict, threshold,
receipt subset or prior payload.

## Why this is the next slice

ADM-P1 can seal inert candidate data. ADM-P2 can record inert external evaluation
facts. Neither creates a Product decision, publication artifact or activation
authority. ADR-0057 requires the Product-owned promotion seam before any immutable
configuration snapshot or later-run use can exist.

The current ADM-P2 contract does **not** mechanically prove evidence-byte custody or
evaluator independence. Therefore ADM-P3 Product policy V1 must fail closed:

- every current ADM-P2 chain, including one containing `EVALUATOR_FAIL`, produces
  `DEFER` with explicit reason codes because the evidence and evaluator behind that
  disposition are not mechanically admissible for a Product decision;
- Product policy V1 can produce neither `REJECT` nor `PROMOTE`;
- evaluator names, provider names, implementation digests, receipt count and opaque
  evidence-reference strings are not substitutes for custody or independence proof.

This limitation is a deliberate correctness property, not an incomplete placeholder.

## Inputs and outputs

### Allowed semantic inputs

1. one exact immutable `DomainCandidate` from ADM-P1;
2. the complete, version-contiguous ADM-P2 `CandidateEvaluationReceipt` chain for that
   candidate at an exact latest-head digest.

The request may carry only route/scope identifiers and compare-and-swap coordinates:
candidate Task/digest, promotion Task/Run, expected evaluation head and expected parent
promotion decision. It may not carry a verdict, threshold, score override, reason,
receipt subset, policy, prior payload, activation instruction or provider/tool request.

### Outputs

- exactly one immutable `CandidatePromotionDecision` appended to a per-candidate chain;
- zero `DomainPriorArtifact` records for `REJECT` or `DEFER`;
- exactly one immutable inert `DomainPriorArtifact` in the same SQLite transaction for
  `PROMOTE`;
- read-only list surfaces for decisions and prior artifacts.

## Authority and identity condition

The authenticated promoter is a fifth identity and must differ from every candidate
builder, candidate sealer, bound evaluator and receipt recorder in the complete receipt
chain. The promoter must:

- have role `PRINCIPAL` or `TENANT_ADMIN`;
- own the promotion Task Goal and accept its Commitment;
- hold an active, unexpired, exact-scope
  `domain.candidate.promote@1` `CapabilityGrant`;
- use a promotion Task/Run distinct from the candidate Task/Run and every evaluation
  Task/Run;
- operate in the exact candidate tenant/workspace;
- pass C7 halt/epoch checks under the same `CorrectionAuthority` guard held through the
  decision/prior transaction.

No identity may self-approve by changing the reducer or supplying its output. Product
policy is registered in code, closed, versioned, deterministic and digest-bound.

## Done conditions

The implementation may be called locally implemented only after all of the following
are true:

1. Closed contracts reject caller verdicts, thresholds, receipt subsets and active
   prior fields.
2. The service loads the complete receipt chain and the store rechecks its latest head
   transactionally; missing, gapped, reordered, cross-scope or stale chains fail closed.
3. Parent-decision CAS, derived idempotency and same-key/different-payload conflict
   behavior are covered by bypass-detecting tests.
4. Product policy V1 is deterministic, version/digest-bound and exhaustively proven to
   return `DEFER` for every current ADM-P2 disposition combination.
5. A registered closed test policy proves `PROMOTE` and prior creation are one atomic
   transaction; an injected SQLite abort leaves neither record.
6. `REJECT` and `DEFER` never create a prior artifact.
7. The promoter is mechanically separated from builder, sealer, every evaluator and
   every recorder, with exact typed capability and Task/Run scope checks.
8. C7 correction cannot interleave after recheck and before append when the same
   authority instance is used.
9. Decision/list operations do not append Task events, change Task/Run/Workflow,
   mutate the candidate or receipts, write workspace bytes, invoke an evaluator,
   provider or tool, or create activation/configuration authority.
10. Targeted and full Product tests, ruff, pyright, compileall and independent exact-diff
    technical review pass.

## Explicit non-goals

- evaluator execution, evaluator-performance validation or independence inference;
- evidence-byte acquisition, evidence-custody attestation or proof generation;
- active candidate application, verified patch application or current-run consumption;
- `TaskConfigurationSnapshot`, ADM-P4 later-run activation, canary or rollback;
- materializer acquisition, ADM-P5, Research imports or model training;
- provider/tool calls, workspace writes, Task events or WorkflowGraph mutation;
- policy/evaluator/promotion-root self-edit, self-approval, L4 or L5;
- Product Alpha, production, cross-process atomicity, migration, push, merge or release.

## Stop conditions

Stop and return `REVISE_TO_SPEC` if implementation requires any of the following:

- caller-selected verdict, threshold, policy or receipt subset;
- treating opaque evidence references or reviewer/model names as mechanical proof;
- a second authority spine or promotion runtime;
- a `PROMOTE` decision without an atomic prior, or a prior without `PROMOTE`;
- current Task/Run/configuration mutation;
- model, plugin, evaluator or candidate author holding promotion authority;
- weakening C7, CAS, append-only history or identity separation;
- extending ADM-P2 receipts or adding proof registries without a separately reviewed
  contract change.

## Review and execution gate

This Goal Card and its Architecture Brief/implementation plan authorize no code change.
Runtime work starts only after delegated CTO and independent technical review accept the
exact plan bytes. Push, merge, activation and release remain separate founder gates.
