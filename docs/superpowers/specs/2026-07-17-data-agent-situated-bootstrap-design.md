# Data Agent Situated Bootstrap Design

> Status: `APPROVED_FOR_IMPLEMENTATION`
> Track: `Product / Architecture / Engineering`
> Base: `46405a31fd71d95d9cd19440fda59a810f13d32d`

## 1. User result and claim boundary

`U`: a durable Data Agent observation can enter the Agent OS situated loop without the operator constructing an origin, attestation, credential lease or admission receipt. A valid observation produces a durable receipt and then exactly one replayable `TaskDraftProposal | HelpRequest | None`; forged, stale, revoked or foreign-scope material reaches neither assessor, provider, Task nor external effect.

This slice establishes a real local Product entry and production composition. It does not establish customer value, Task activation, external effects, production IAM/KMS, HTTP deployment, autonomy, training or an E2E falsifier result.

## 2. Chosen architecture

Use an independent production-owned `DataAgentSituatedBootstrap`; do not add security-sensitive constructor arguments to `AgentOSApplication`.

```text
DataAgentReportSourceConfig + durable adapter state
  -> DataAgentReportAdapter.pull/poll
  -> derived read-only origin + payload attestation
  -> composition-owned credential authorization + deterministic lease
  -> EnvironmentEventAdmissionService.admit
  -> scoped durable admission receipt
  -> MandateSteward.observe_event
  -> TaskDraftProposal | HelpRequest | None
```

The bootstrap builds one `DataAgentSituatedRuntime` containing the adapter, admission facade and scope-bound steward. `AgentOSApplication` receives that runtime only through a private composition classmethod. Its public constructor remains free of admission writers, raw assessment stores, credentials, leases, origins and attestations.

## 3. Components

### 3.1 `DataAgentAdmissionMaterialReader`

Lives beside `DataAgentReportAdapter` and implements the existing origin and attestation reader ports. It receives a canonical snapshot of `DataAgentReportSourceConfig`, the adapter and the frozen payload-policy/schema digests.

For an event already present in durable adapter state it deterministically derives:

- `EventOriginRegistration` from safe source metadata, the exact current credential digest, event digest, observation digest and frozen schema/policy digests;
- `PayloadAdmissionAttestation` from the exact observation artifact and the same frozen schema/policy digests.

No resolver key, report body, provider response or exception text enters either contract. Identical durable input bytes produce identical material after restart.

### 3.2 `DataAgentAdmissionFacade`

Owns the composition-only credential authorization reader, lease derivation and `EnvironmentEventAdmissionService`.

`admit_event(event_id: str) -> EnvironmentEventAdmissionReceipt`:

1. resolve the durable event;
2. resolve the current mandate and binding at the composition clock;
3. derive a deterministic `CredentialLeaseRef` from the canonical credential snapshot, source id, current correction epoch and credential validity window;
4. expose that exact lease only to the internal admission service;
5. call `EnvironmentEventAdmissionService.admit` and return its durable receipt.

The caller cannot provide a lease id or any authority object. A changed correction epoch produces different lease material and invalidates stale admission.

### 3.3 `DataAgentSituatedBootstrap`

Builds the adapter, scoped admission store, assessment reader, proposal service, steward and application from production composition inputs:

- database/workspace;
- authenticated `PrincipalIdentity`;
- frozen `DataAgentReportSourceConfig`;
- durable `DataAgentReportStateStore`;
- already-ratified situated control and assessor ports;
- transport/credential resolver supplied only at the composition boundary;
- clock.

It returns an `AgentOSApplication` bound to one `DataAgentSituatedRuntime`. It does not ratify mandates, grant capabilities or create Tasks.

## 4. Public entry points

```python
bundle = app.observe_data_agent_report(trace_id)
receipt = app.admit_data_agent_event(bundle.event.environment_event_id)
result = app.propose_situated_work(
    bundle.event.environment_event_id,
    bundle.projection.projection_id,
    receipt.receipt_id,
)
```

`admit_data_agent_event` is unavailable on an uncomposed application. `propose_situated_work` retains its mandatory receipt id and only calls `MandateSteward.observe_event`.

## 5. Invariants and failures

- The adapter or its tightly owned reader derives origin/attestation; Application never constructs them.
- Credential resolver material is accepted only by the adapter transport boundary and is discarded from admission metadata.
- The lease is composition-owned and cannot be supplied by an API caller.
- Origin, attestation and lease canonical ids/digests are recomputed and mutation-sensitive.
- Principal, tenant, workspace, mandate, binding and correction epoch must match across every object.
- Credential inactive, expired, revoked, scope-drifted or content-drifted material fails before receipt, assessment, provider, trace, Task or effect.
- Foreign-scope and caller-minted same-content objects are indistinguishable from unavailable material at the public boundary.
- Dependency exceptions become fixed safe product errors with `from None`; raw text is absent from logs and durable state.
- Legacy two-argument proposal calls and direct receipt construction remain forbidden; no compatibility shim restores them.
- Existing local Task 3 database schemas remain disposable and fail closed; no production migration is claimed.

## 6. Verification

RED must demonstrate the current test helper is not product composition, then cover:

- deterministic origin/attestation/lease derivation and restart equality;
- real adapter pull -> admission -> steward proposal and durable replay;
- credential status, expiry, content and scope drift;
- foreign scope and same-content/caller-minted authority attempts;
- dependency-exception and secret sentinels absent from errors, logs and databases;
- no receipt path means zero assessment/provider/trace/Task/effect;
- no direct `.propose` or private writer/store use from `AgentOSApplication`;
- zero Task activation and connector/capability calls.

Focused Product tests run first, followed by all Product tests, Ruff, Pyright and `git diff --check`.

## 7. Deferred work

- TaskActivationGate and external effect execution;
- IC0/IC1 controller integration and result-bearing E2E falsifier;
- production HTTP configuration, IAM/KMS and database migration;
- model training, distributed runtime, multimodal ingestion and domain-generalization claims.

