# P-MANDATE-RUNTIME-BINDING-1 verification

Status: `IMPLEMENTED_AND_LOCALLY_VERIFIED / PENDING_INDEPENDENT_REVIEW / NOT_RELEASED`

## Requirement boundary

- `U`: an authenticated operator can turn one durable high-level Mandate into a real, restart-safe observation loop without manually constructing Runtime authority objects.
- `P`: request-authenticated `POST /v1/mandates/{mandate_id}/environment-bindings:authorize` and `GET /v1/mandates/{mandate_id}/observation-authorizations` project a durable `RATIFIED` workspace record into the existing situated Runtime authority store.
- `A`: the Mandate owner and authorizing `TENANT_ADMIN` are distinct; the Runtime revalidates the scoped situated row, authorization row, workspace record, source descriptor, assessor and context together; Task activation, capability grant and external effects are literal `false`.
- `E`: tests cover missing/expired/drifted records, cross-scope and non-admin callers, class/capability/budget/assessor/context drift, exact replay/conflict, second-admin rebind, command/receipt/index/workspace tamper, deleted authorization, legacy naked refs, forged receipt prefixes, cross-tenant same-ID isolation, pause/correction invalidation, request-level HTTP authentication and a real Data Agent adapter restart replay.
- `R`: none. This package creates no autonomy, learning-effectiveness or Founder Cognitive Load result.

## RED evidence

Commit `59bf89e` contains the initial tests before implementation. Commit `abf1026` adds the independent-review attack tests before the corrective implementation. RED runs demonstrated missing contracts and HTTP routing, source-policy drift bypass, time-dependent idempotency, unchecked command digest, global Mandate-ID collision and the unauthenticated HTTP-admin path.

## Verification commands and results

```text
uv run --extra product-test pytest tests/product/test_mandate_observation_authorization.py -q
19 passed

uv run --extra product-test pytest tests/product -q
1423 passed, 1 skipped (three deterministic file chunks: 458/1, 435, 530)

uv run --extra product-test ruff check apps packages/contracts/src packages/os_core/src tests/product
All checks passed

uv run --extra product-test pyright apps packages/contracts/src packages/os_core/src tests/product
0 errors, 0 warnings, 0 informations

uv build --wheel --out-dir /tmp/agent-os-contract-wheel-binding-20260718 packages/contracts
PASS

uv build --wheel --out-dir /tmp/agent-os-core-wheel-binding-20260718 packages/os_core
PASS

git diff --check
PASS
```

The Product suite was rerun after the final implementation changes. Integration still requires a new exact-head independent review.

## Deliberate non-capabilities

- A `RATIFIED` Mandate Workspace record alone does not create situated authority.
- Observation authorization does not create or activate a Task, grant a capability, call a tool, or authorize an external effect.
- This package does not add a second Runtime, provider implementation, TaskActivation path, UI, generalized domain adaptation, training, release or production identity system.
- Pause/revoke/correction remain owned by the existing situated authority and invalidate old observation authority through its existing correction epoch checks.
- Legacy `SQLiteSituatedAssessmentStore(..., mandates=...)` construction remains available to lower-level component tests, but the Product composition path rejects every projection without exact Workspace and observation-authorization provenance.
