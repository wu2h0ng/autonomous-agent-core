# ADM-P1 Candidate Sealing Implementation Evidence

> Date: 2026-07-15
> Track: Product / Translational contract slice
> Status: **IMPLEMENTED_LOCAL_CANDIDATE_SEALING_ONLY**
> Branch: `codex/adaptive-domain-adr-20260715`
> Base: `e3cdacbc`
> Implementation head: `fb8593b10091953b61b6bea982953e3682215243`

## Decision

ADM-P1 implements one bounded local Product capability: an authenticated caller can seal
and list immutable, provenance-bound `DomainCandidate` records for an already-running
Task/Run. The slice is real and locally verified, but it does not discover a domain,
evaluate or promote a candidate, create a prior, activate a candidate, change a workflow,
train a model or establish transfer performance.

## Real entry points and contracts

- `POST /v1/tasks/{task_id}/domain-candidates:seal`
- `GET /v1/tasks/{task_id}/domain-candidates`
- `AgentOSApplication.seal_domain_candidate(...)`
- `AgentOSApplication.list_domain_candidates(...)`
- `DomainCandidateSealer.seal(...)`
- `DomainCandidateSealer.list_for_task(...)`

The closed contract represents B/R/T/P write channels. In ADM-P1, only R may carry a
representation `CANDIDATE`; R may also return `ASK`, `UNKNOWN` or `NOT_SUPPORTED`.
B/T/P are representable only as inert `NOT_SUPPORTED` records. K/S and unknown channels
fail validation.

The sealed record binds the final transaction-assigned candidate version, payload,
requested channel, source snapshot and provenance, mechanism, parent digest, sealer,
timestamp and observed C7 correction epoch vector. Its digest excludes only the digest
field itself.

## Authority, persistence and failure behavior

- Principal, tenant, workspace, Task and Run identities must match exactly.
- Task and Run must both be `RUNNING`.
- C7 halt is checked before work; its epoch vector is captured and halt/epochs are checked
  again under a process-local `CorrectionAuthority` re-entrant guard held through append.
  This linearizes same-authority, same-process `correct`/`resume` against candidate append;
  it does not establish cross-process or distributed atomicity.
- SQLite append uses `BEGIN IMMEDIATE`, derived-key idempotency, same-key/different-payload
  conflict, parent compare-and-swap and transaction-assigned versioning.
- Reopening the store preserves records and digest stability.
- Seal/list does not append a Task event, mutate WorkflowGraph or workspace files, grant a
  capability or create activation authority.
- Scope/authority failures map to 403, stale parent/idempotency conflicts to 409, invalid
  contracts/provenance to 400 and missing Task to 404.
- The seal endpoint bypasses the older generic HTTP idempotency cache so the candidate
  store, not a path/header response cache, owns conflict semantics.

## Verification evidence

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest \
  tests/product/test_materialization_contracts.py \
  tests/product/test_materialization_service.py \
  tests/product/test_materialization_api.py -q
47 passed

PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest tests/product -q
240 passed, 1 skipped in 30.24s

../../.venv/bin/python -m ruff check \
  apps packages/os_core/src packages/contracts/src tests/product
All checks passed!

../../.venv/bin/python -m pyright \
  apps packages/os_core/src packages/contracts/src
0 errors, 0 warnings, 0 informations
```

Bypass-detection mutations and a red-before-green concurrency check were applied only
temporarily and then removed or satisfied by the final implementation:

1. Replacing the pre-append C7 epoch/halt check with an unconditional return caused
   `test_epoch_change_before_append_fails_closed` to fail because no denial was raised.
2. Re-enabling the generic HTTP idempotency cache for seal caused
   `test_seal_endpoint_bypasses_generic_http_idempotency_cache` to fail: a conflicting
   payload incorrectly returned cached 200 instead of 409.
3. Before the process-local C7 guard was introduced,
   `test_correction_cannot_interleave_after_recheck_before_append` failed because a
   concurrent correction completed while the candidate store append was blocked. The
   final implementation holds the authority guard through append and the test passes.

The Product suite is green. This record does not claim the repository-wide suite is green.
A separate diagnostic run of `tests/product_eval -q --maxfail=2` stopped at
`656 passed, 2 failed in 252.79s`; both failures are pre-existing artifact-state/basename
expectations outside the three ADM-P1 commits:

- `test_d1e_source_has_no_early_material_old_identity_or_digest_constants`
  observes the already-present `product_evals/lh_recovery_1a/fixed_baseline.py`.
- `test_scratch_fixture_is_disjoint_from_absent_formal_output_ledgers` observes the
  already-present formal SPINE-E2E-4 ledgers under the parent `.agent_runs` directory.

Those failures remain governed by their own exact artifacts and verdicts; ADM-P1 neither
fixes nor reinterprets them.

## Independent technical review

Kimi reviewed the exact implementation range `ee8c4c3..fb8593b` after the C7
linearization fix and returned `TECHNICAL_APPROVE` with no blockers. Non-blocking notes
cover the wall-clock timeout in the concurrency test, broad exception capture in its
thread helper, serialization of correction against append, the process-local lock scope
and the scripted authority's intentionally non-concurrent semantics.

The review-approved ceiling is:

```text
IMPLEMENTED_LOCAL_CANDIDATE_SEALING_ONLY: same-process C7 changes are linearized with
candidate append via CorrectionAuthority RLock; cross-process or distributed atomicity
is not claimed.
```

## Claim boundary

Authorized statement:

```text
ADM-P1 is IMPLEMENTED_LOCAL_CANDIDATE_SEALING_ONLY on the isolated feature branch.
```

Not established: materializer acquisition, domain understanding, evaluator independence,
candidate quality, promotion, later-run activation, `DomainPriorArtifact`,
`TaskConfigurationSnapshot`, adaptive competence, self-improvement, Product Alpha,
production readiness, autonomy, migration, push, merge or release.

## Deferred successors

- ADM-P2: independent evaluation receipt and evaluator isolation.
- ADM-P3: Product-owned promotion decisions and immutable optional priors.
- ADM-P4: immutable Task configuration snapshot and new-Task activation.
- ADM-P5: bounded materializer acquisition engine and one-way Research observation seam.
- Research falsifier: held-out cross-environment comparison against direct-model,
  retrieval and strong thin-prior baselines.
