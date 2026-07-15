# ADM-P4 Goal Card — Immutable Task Configuration Snapshot

> Date: 2026-07-15
> Track: Product / Translational
> Status: **DESIGN_READY / AWAITING_KIMI_SPEC_REVIEW / NO_RUNTIME_AUTHORITY**
> Branch: `codex/adm-p4-task-configuration-snapshot-20260715`
> Exact base: `7e76461aec8e96b4d1016f7fec3ddfc9b13d7ce2`
> Authority: ADR-0057; reviewed ADM-P1/ADM-P2/ADM-P3 local evidence
> Claim ceiling before implementation review: `SPECIFIED_ADM_P4_ONLY`

## Goal

Build the smallest Product-owned immutable `TaskConfigurationSnapshot` seam for one
new consumer Task and its reserved Run. The snapshot must bind the exact committed
workflow, policy contract, provider profile, active execution grants, expected outcome
and evidence requirements, C7 correction epoch vector and, optionally, one inert
ADM-P3 `DomainPriorArtifact` resolved from Product-owned immutable stores.

The first version is a read-only configuration binding. It must not apply the prior,
alter the workflow, widen authority, change tools or model choice, or change execution
semantics.

## Why this is the next slice

ADM-P1 seals inert candidates, ADM-P2 records external evaluation receipts, and ADM-P3
records Product-owned decisions and can atomically publish an inert optional prior.
None of those artifacts can be consumed by a Task or Run. ADR-0057 requires a separate
immutable configuration snapshot and a later new Task/Run before any use can be
considered.

Production policy V1 still returns only `DEFER`, so the production composition root has
no prior to bind and must never synthesize one. A closed test-only policy and fixture may
create one valid promoted prior solely to prove the binding and fail-closed paths.

## Allowed caller input

The caller may provide only:

1. the consumer Task route;
2. optionally, a `DomainPriorSelector` containing the source candidate Task ID,
   candidate digest and prior artifact ID;
3. at Run start, the exact sealed snapshot ID.

The caller may not provide snapshot content, snapshot digest, workflow or workflow
digest, policy or policy digest, provider profile, grants, expected outcome, evidence
requirements, C7 epochs, prior bytes, prior digest, promotion data, receipt subset,
provenance, reserved Run ID, activation flag or execution override.

## Product-owned derivation

The snapshot sealer derives all authoritative fields from existing Product state:

- the committed `WorkflowGraph`, version and canonical digest;
- the registered `PolicyKernel` version and Product-owned policy-contract digest;
- the exact current `ProviderProfile` and canonical digest;
- the exact active, unexpired, same-principal/same-scope grants required by workflow
  capabilities and their canonical set digest;
- the committed `ExpectedOutcome`, canonical digest and embedded evidence requirements;
- a Product-reserved consumer Run ID;
- the C7 vector for `task.configuration.snapshot@1`;
- when selected, the exact candidate, complete evaluation chain, promotion decision and
  inert prior from the same tenant/workspace ADM-P1/P2/P3 stores.

## Authority and separation conditions

The authenticated sealer must:

- have role `PRINCIPAL` or `TENANT_ADMIN`;
- create the consumer Goal and accept its Commitment;
- hold an active, unexpired, exact-scope grant with
  `capability_id="task.configuration.snapshot"` and `capability_version="1"`;
- have the raw authority scope `task.configuration.snapshot` in the Commitment;
- operate in the consumer Task tenant/workspace;
- pass Task state, identity, grant and C7 checks under the same local correction guard
  held through the Task-event append.

When a prior is selected, the consumer Task and reserved Run must differ from the
candidate/materialization Task/Run, every evaluation Task/Run and the promotion
Task/Run. The source artifacts remain inert and immutable. No source Task/Run may bind
its own candidate or prior.

## Done conditions

Implementation may be called locally implemented only when all conditions hold:

1. Frozen contracts reject every caller-injected authoritative or activation field.
2. Snapshot identity and digest are canonical, content-sensitive and self-validating.
3. One consumer Task can seal at most one snapshot; exact replay returns the same
   object and a different selector conflicts.
4. Sealing is allowed only for a committed Task with no Run and no prior snapshot.
5. Workflow, policy, provider, grants, expected outcome/evidence and C7 bindings are
   Product-derived and exact.
6. Optional prior resolution reads the same-scope immutable ADM stores and revalidates
   candidate, receipt-chain, promotion and prior lineage; missing or mismatched data
   fails closed.
7. Candidate/evaluation/promotion Task/Run identities are disjoint from the consumer
   Task/reserved Run.
8. Snapshot append is a first-class Task event protected by Task-stream CAS and the
   same-instance C7 guard.
9. Run start requires the exact snapshot ID when a snapshot exists, uses its reserved
   Run ID, records its ID/digest in `AgentRun`, and fails closed on any live binding
   drift before appending `RUN_STARTED`.
10. Snapshot-bound runs cannot replan in ADM-P4 because that would invalidate the
    frozen workflow binding.
11. No snapshot or prior field is consulted to change WorkflowGraph, Capability,
    PolicyKernel, provider/model, tool set or execution semantics.
12. Production policy V1 creates no prior; only a closed test fixture proves prior
    binding.
13. Seal/get/list/start surfaces bypass generic HTTP idempotency for writes and rely on
    Product-owned replay/conflict semantics.
14. Targeted tests, full Product tests, ruff, pyright, compileall, diff-check and Kimi
    exact-implementation technical review pass.

## Explicit non-goals

- candidate application, representation-patch application or knowledge mutation;
- activation, canary, rollback, performance claims or adaptive competence;
- workflow compilation, grant creation, grant widening or policy/provider selection;
- provider/tool calls during seal/get/list/start binding;
- evaluator execution, evidence custody proof or independence proof;
- materializer acquisition, ADM-P5, Research imports or model training;
- cross-process C7/Task-store atomicity or distributed transaction claims;
- global migration of all legacy Tasks to snapshots;
- L4 active-runtime self-modification, L5 authority-root edit or self-approval;
- Product Alpha, production readiness, migration, push, merge or release.

## Stop and downgrade conditions

Stop implementation and return `REVISE_TO_SPEC` if any design requires caller-owned
authoritative fields, a mutable snapshot, prior application, grant widening, live config
hot reload, source/current-run reuse, weakened C7/CAS, or a second authority spine.

If the existing Task event stream cannot safely record an exact snapshot binding and
make `RUN_STARTED` validate it, implement only a closed immutable snapshot ledger plus
an explicit `NOT_BOUND` Run-start failure. Do not claim integration and do not create a
best-effort or two-phase pseudo-binding.

## Review and execution gate

This Goal Card, Architecture Brief and TDD plan authorize no runtime change. Runtime
implementation begins only after Kimi reviews the exact plan checkpoint and returns the
literal verdict `SPEC_APPROVE`. Push, merge, migration, activation and release remain
separate founder gates.
