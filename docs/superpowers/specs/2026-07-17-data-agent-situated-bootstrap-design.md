# Data Agent Situated Bootstrap Design

> Status: `REVISED / APPROVED_FOR_IMPLEMENTATION`
> Track: `Product / Architecture / Engineering`
> Base: `46405a31fd71d95d9cd19440fda59a810f13d32d`
> Supersedes: commit `4205d3c` design text where the adapter derived its own payload attestation

## 1. User result and claim boundary

`U`: a durable Data Agent observation can enter the Agent OS situated loop through a real local entry point without the operator constructing origin, attestation, credential lease or admission receipt. A valid observation produces one durable admission receipt and then one replayable `TaskDraftProposal | HelpRequest | None`; forged, stale, revoked or foreign-scope material reaches neither assessor, provider, Task nor external effect.

This slice establishes a local Product composition candidate and user-reachable proposal-only path. It does not establish customer value, Task activation, external effects, production IAM/KMS, production HTTP deployment, autonomy, training or an E2E falsifier result.

Credential revocation is re-evaluated for events that have not yet received a durable admission receipt. Retrospective invalidation of an already persisted receipt requires a correction-epoch or receipt-contract change and is explicitly outside this slice.

## 2. Chosen architecture

The report adapter is an ingress and exact-byte resolver, not its own admission authority. Payload validation, authority composition and deployment startup remain separate.

```text
DataAgentReportAdapter
  -> exact durable event + artifact bytes
  -> independent executable payload validator
  -> atomic origin + attestation material store
  -> current credential + current Mandate/binding/epoch
  -> deterministic one-event credential lease
  -> existing EnvironmentEventAdmissionService
  -> durable scoped receipt
  -> existing MandateSteward
  -> TaskDraftProposal | HelpRequest | None
```

The bootstrap produces one scope-bound `DataAgentSituatedRuntime`; it does not construct `AgentOSApplication`. Application binding and local startup are separate tasks and cannot expose raw authority injection.

## 3. Components

### 3.1 Independent payload validator and material registrar

`apps/api_server/data_agent_report_admission.py` owns Data-Agent-specific admission validation. `DataAgentPayloadAdmissionValidator` has frozen executable schema and policy descriptors whose digests are computed internally and cannot be supplied by callers.

It independently re-runs, over the exact durable bytes:

- strict UTF-8 JSON parsing with duplicate-key and non-finite-number rejection;
- size, SHA-256, canonical `ArtifactRef`, event type, media type and `situated:read` checks;
- tenant/workspace/time/event/artifact/dedupe identity binding;
- external audience, applied external redaction and single trace binding;
- credential-reflection rejection without persisting the secret;
- the rule that report business actions do not become Agent OS authority.

On first success, `DataAgentAdmissionMaterialRegistrar` uses the trusted validation clock for both `registered_at` and `assessed_at`, then atomically persists canonical `EventOriginRegistration` and `PayloadAdmissionAttestation` through `SQLiteDataAgentAdmissionMaterialStore`. It never backdates validation to `event.recorded_at`. Restart reuses stored bytes; schema/policy version drift, corruption or conflicting event content fails closed rather than silently re-signing.

The adapter continues to own pull/poll, transport credential use, exact durable bytes, event/artifact/projection construction and read-only resolution. It must not import or construct `PayloadAdmissionAttestation`.

### 3.2 Admission facade and scope-bound runtime

`DataAgentAdmissionFacade.admit_event(event_id)`:

1. resolves the exact durable event;
2. calls the independent material registrar;
3. resolves current credential authorization and current Mandate/binding/epoch;
4. purely derives one deterministic `CredentialLeaseRef`;
5. places only that lease in a one-shot immutable `CanonicalCredentialLeaseRegistry`;
6. calls the existing `EnvironmentEventAdmissionService.admit`.

The public facade accepts only `event_id`. It exposes no origin, attestation, lease, credential object, writer, store, registry or authority override.

Lease fields are bound to the exact event/current authority. `issued_at = origin.registered_at`; `valid_from = max(origin.registered_at, credential.created_at, mandate.valid_from)`; `expires_at = min(credential.expires_at, mandate.expires_at)`; invalid chronology denies. The origin registration time is the truthful, persisted first-validation time, so restart remains deterministic without backdating lease issuance to event observation. The issuer is `data-agent-situated-bootstrap/v1`. A fresh one-event immutable registry is used per admission; no mutable `register/put/add/verify` API and no old-lease accumulation are allowed.

`DataAgentSituatedBootstrap.compose(...)` returns a `DataAgentSituatedRuntime` containing only safe `observe_report`, `admit_event` and receipt-required `propose` operations. It reuses existing admission, situated assessment, proposal and steward implementations; it does not ratify mandates, create credentials, activate Tasks or authorize effects.

### 3.3 Application and real local startup

`AgentOSApplication` binds a pre-composed scope-matching runtime only through a private composition method. Its public constructor does not accept the runtime, steward, origins, attestations, credentials, leases, admission writer or raw proposal service.

The local CLI gains `--data-agent-situated-config PATH`. A private deployment builder loads a strict, bounded, non-symlink JSON file containing only opaque locators and digest-bound non-secret configuration. It must resolve an already persisted active Mandate/binding from `SQLiteSituatedAssessmentStore`; configuration cannot mint or ratify authority, import factories, or inject Python objects. Missing, paused, revoked, expired, mismatched or unprovisioned authority fails before `serve`.

The local API exposes one proposal-only operation accepting only `trace_id`:

```text
POST /api/situated/data-agent-reports/{trace_id}/proposal
  -> pull -> validate/register -> admit -> receipt-required propose
```

This is the existing local stdlib server surface, not a production IAM/HTTP claim.

## 4. Invariants and failures

- The adapter cannot attest itself; schema/policy labels without executable validation are invalid.
- First validation time is durable and truthful; restart clock changes cannot alter material bytes.
- Every not-yet-admitted event re-resolves current credential authorization and current Mandate/binding/epoch.
- Caller-minted same-content origin, attestation, lease or receipt is ignored because no public API accepts it.
- Principal, tenant, workspace, mandate, binding, correction epoch and credential digest match across the full chain.
- Credential inactive, expired, revoked, scope/content/owner drift or foreign scope denies before a new receipt.
- Dependency exceptions become fixed safe errors with `from None`; secret, resolver key, headers, raw body and provider response do not enter authority databases, traces, logs or error text.
- Existing durable report storage may contain exact already-redacted external report bytes; no broader raw-data claim is made.
- Legacy two-argument proposal calls and test-only self-minted receipts remain forbidden.
- No path activates a Task or invokes a connector/capability/effect.

## 5. Verification and claim state

RED and verification cover executable policy bypasses, atomic persistence, restart equality, mutation/drift, current credential reads, correction epochs, caller authority injection, secret leakage, concurrent events, CLI composition and the real local endpoint. Every denial asserts zero new receipt/assessment/provider/trace/Task/effect as applicable.

The accepted final state is `IMPLEMENTED_LOCAL_NOT_CANONICALLY_INTEGRATED`. It remains neither released nor Customer-0 evidence.

## 6. Deferred work

- retrospective credential revocation of already admitted receipts;
- TaskActivationGate and external effects;
- IC0/IC1 controller integration and result-bearing E2E falsifier;
- production IAM/KMS, migrations and hardened HTTP deployment;
- training, distributed runtime, multimodal ingestion and domain-generalization claims.
