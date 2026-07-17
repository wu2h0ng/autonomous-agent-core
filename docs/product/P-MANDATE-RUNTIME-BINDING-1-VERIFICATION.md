# P-MANDATE-RUNTIME-BINDING-1 verification

Status: `IMPLEMENTED_AND_LOCALLY_VERIFIED / PENDING_INDEPENDENT_REVIEW / NOT_RELEASED`

## Requirement boundary

- `U`: an authenticated operator can turn one durable high-level Mandate into a real, restart-safe observation loop without manually constructing Runtime authority objects.
- `P`: `POST /v1/mandates/{mandate_id}/environment-bindings:authorize` and `GET /v1/mandates/{mandate_id}/observation-authorizations` project a durable `RATIFIED` workspace record into the existing situated Runtime authority store.
- `A`: the Mandate owner and authorizing `TENANT_ADMIN` are distinct; source policy, assessor, context, scope, budgets and correction epoch are exact-bound; Task activation, capability grant and external effects are literal `false`.
- `E`: tests cover missing/expired/drifted records, cross-scope and non-admin callers, class/capability/budget/assessor/context drift, exact replay/conflict, second-admin rebind, receipt/index tamper, pause/correction invalidation, HTTP entry points and a real Data Agent adapter restart replay.
- `R`: none. This package creates no autonomy, learning-effectiveness or Founder Cognitive Load result.

## RED evidence

Commit `59bf89e` contains the initial tests before implementation. The first focused run failed during collection because `MandateObservationAuthorizationCommand` did not exist. Later red runs separately demonstrated the missing HTTP route, source-policy drift bypass and time-dependent idempotency defect before their fixes.

## Verification commands and results

```text
uv run --extra product-test pytest tests/product/test_mandate_observation_authorization.py -q
17 passed in 1.18s

uv run --extra product-test pytest tests/product -q
1419 passed, 1 skipped in 54.78s

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

The Product suite was rerun after the final implementation changes. Integration still requires an exact-head independent review.

## Deliberate non-capabilities

- A `RATIFIED` Mandate Workspace record alone does not create situated authority.
- Observation authorization does not create or activate a Task, grant a capability, call a tool, or authorize an external effect.
- This package does not add a second Runtime, provider implementation, TaskActivation path, UI, generalized domain adaptation, training, release or production identity system.
- Pause/revoke/correction remain owned by the existing situated authority and invalidate old observation authority through its existing correction epoch checks.
