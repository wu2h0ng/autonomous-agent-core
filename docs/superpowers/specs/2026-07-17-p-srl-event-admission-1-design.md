# P-SRL Event Admission 1 Design

> Status: `REVISION_2 / DESIGN_FROZEN_FOR_LOCAL_IMPLEMENTATION`
> Primary requirement: `A/P`
> Product claim ceiling: `IMPLEMENTED_LOCAL / LOCAL_CONTROLLED`
> Base: `codex/p-srl-event-admission-1-20260717@8d5820c75a397a299bec898e783ee8113fd3d542`
> Supersedes: design revision 1 at `f904aa10a3bbc100a8982f7769aaa9ae73ef117f`

## 1. Goal and correction

Close the smallest real gap between an external observation adapter and the existing situated product spine: prove that an event has an adapter-owned origin registration, a current canonical credential lease, a policy-bound payload-admission attestation and a live Mandate/binding epoch before the existing `OperationalProposalService` may assess or persist it.

Revision 2 closes four independent-review defects:

1. the existing public proposal entry cannot bypass admission;
2. caller-supplied source, lease and attestation objects are never authority inputs;
3. the steward rechecks current Mandate/binding/epoch from the authority store;
4. trace is a durable `PENDING -> COMPLETED | DENIED` outbox, not a false cross-store atomic claim.

This is an admission and convergence slice. It is not a third event architecture and not a new Runtime.

## 2. Existing product spine to reuse

The implementation must reuse:

- `EnvironmentEvent`, `OperationalProjectionRef`, `RatifiedMandateRef`, `EnvironmentBindingAuthorization`;
- `SituationalTrustResolver`, `OperationalProposalService`, `ProviderRelevanceAssessor`;
- `SituatedAssessmentStore`, `SituatedAssessmentRecord`, `TaskDraftProposal`, `HelpRequest`;
- SQLite assessment replay, pause, revoke and correction-epoch CAS;
- `CredentialRef` and the credential-broker boundary;
- the Data Agent report adapter as the first concrete ingress adapter.

`SrlEnvironmentEvent` remains an internal transport/invariant DTO. It is not a product event authority and cannot be admitted directly.

## 3. Contracts

Create `agent_os_contracts.srl_event_admission`.

### 3.1 Adapter-owned event origin

```python
class EventOriginRegistration(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    registration_id: NonEmptyStr
    environment_event_id: NonEmptyStr
    source_id: NonEmptyStr
    source_config_digest: Sha256Digest
    credential_ref_id: NonEmptyStr
    credential_ref_digest: Sha256Digest
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    mandate_id: NonEmptyStr
    environment_binding_id: NonEmptyStr
    event_digest: Sha256Digest
    observation_digest: Sha256Digest
    event_schema_digest: Sha256Digest
    payload_policy_digest: Sha256Digest
    registered_at: UtcDateTime
    registration_digest: Sha256Digest
```

The caller never chooses a source id. `EventOriginRegistryPort.resolve_event(event_id)` returns the exact adapter-owned registration. The registration is derived from the immutable adapter/source configuration plus the exact admitted event and `CredentialRef`; it cannot independently alter principal, scope, mandate or binding.

`registration_id == f"event-origin:{registration_digest}"`. The digest covers every field except `registration_id` and `registration_digest`.

### 3.2 Canonical credential lease

```python
class CredentialLeaseRef(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    lease_id: NonEmptyStr
    credential_ref_id: NonEmptyStr
    credential_ref_digest: Sha256Digest
    source_id: NonEmptyStr
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    mandate_id: NonEmptyStr
    environment_binding_id: NonEmptyStr
    correction_epoch: int
    issued_at: UtcDateTime
    valid_from: UtcDateTime
    expires_at: UtcDateTime
    issuer_id: NonEmptyStr
    lease_digest: Sha256Digest
```

`CredentialLeaseRegistryPort.resolve(lease_id)` returns a canonical lease. `CredentialRefReader.resolve(credential_ref_id)` returns the current `CredentialRef`. Admission verifies exact digest, `ACTIVE`, principal/tenant/workspace, required read/source scopes, time, and `lease.expires_at <= credential.expires_at`. A boolean verifier over a caller-supplied lease is forbidden.

`lease_id == f"credential-lease:{lease_digest}"`; the digest covers every other field.

### 3.3 Policy-bound payload admission

```python
class PayloadAdmissionAttestation(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    attestation_id: NonEmptyStr
    environment_event_id: NonEmptyStr
    source_id: NonEmptyStr
    observation_artifact_id: NonEmptyStr
    observation_digest: Sha256Digest
    policy_digest: Sha256Digest
    schema_digest: Sha256Digest
    issuer_id: NonEmptyStr
    assessed_at: UtcDateTime
    disposition: Literal["ADMITTED_UNDER_POLICY"]
    credential_reflected: Literal[False] = False
    attestation_digest: Sha256Digest
```

`PayloadAdmissionRegistryPort.resolve_event(event_id)` returns the canonical attestation. The caller cannot provide an attestation object or select an issuer. This attests only that the frozen adapter policy admitted the exact bytes; it is not a general PII/DLP or universal “safe for model” claim.

`attestation_id == f"payload-admission:{attestation_digest}"`; the digest covers every other field.

### 3.4 Admission receipt and durable outbox trace

```python
class EnvironmentEventAdmissionReceipt(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    receipt_id: NonEmptyStr
    environment_event_id: NonEmptyStr
    event_digest: Sha256Digest
    event_origin_digest: Sha256Digest
    credential_lease_digest: Sha256Digest
    payload_attestation_digest: Sha256Digest
    mandate_id: NonEmptyStr
    environment_binding_id: NonEmptyStr
    environment_binding_version: int
    environment_binding_digest: Sha256Digest
    correction_epoch: int
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    admitted_at: UtcDateTime
    issued_by: Literal["event-admission-service/v1"]
    receipt_digest: Sha256Digest
    grants_authority: Literal[False] = False
    authorizes_effects: Literal[False] = False


class SituatedTraceStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"


class SituatedTraceReason(str, Enum):
    ASSESSMENT_PENDING = "ASSESSMENT_PENDING"
    TASK_DRAFT = "TASK_DRAFT"
    HELP_REQUEST = "HELP_REQUEST"
    NO_PROPOSAL = "NO_PROPOSAL"
    ADMISSION_DENIED = "ADMISSION_DENIED"
    AUTHORITY_CHANGED = "AUTHORITY_CHANGED"
    PROVIDER_FAILED = "PROVIDER_FAILED"


class SituatedEvaluationTrace(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    trace_id: NonEmptyStr
    admission_receipt_digest: Sha256Digest
    event_id: NonEmptyStr
    projection_id: NonEmptyStr
    mandate_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    status: SituatedTraceStatus
    reason: SituatedTraceReason
    result_binding_digest: Sha256Digest | None
    delegation_attempt_count: int = Field(ge=0)
    committed_provider_call_attempted: bool | None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    duration_ms: int = Field(ge=0)
    measurement_scope: Literal["LOCAL_CONTROLLED"] = "LOCAL_CONTROLLED"
    recorded_at: UtcDateTime
```

`receipt_id == f"event-admission:{receipt_digest}"`. `trace_id` is deterministic from the admission receipt and projection. Reason fields are closed enums; no provider, caller or exception text can enter the trace.

## 4. Authority and storage ports

```python
class EventOriginRegistryPort(Protocol):
    def resolve_event(self, event_id: str) -> EventOriginRegistration | None: ...

class CredentialLeaseRegistryPort(Protocol):
    def resolve(self, lease_id: str) -> CredentialLeaseRef | None: ...

class CredentialRefReader(Protocol):
    def resolve(self, credential_ref_id: str) -> CredentialRef | None: ...

class PayloadAdmissionRegistryPort(Protocol):
    def resolve_event(self, event_id: str) -> PayloadAdmissionAttestation | None: ...

class EventAdmissionStorePort(Protocol):
    def by_receipt_id(self, receipt_id: str) -> EnvironmentEventAdmissionReceipt | None: ...
    def by_event_id(self, event_id: str) -> EnvironmentEventAdmissionReceipt | None: ...

class SituatedTraceOutboxPort(Protocol):
    def begin(self, trace: SituatedEvaluationTrace) -> SituatedEvaluationTrace: ...
    def complete(self, trace: SituatedEvaluationTrace) -> SituatedEvaluationTrace: ...
    def by_trace_id(self, trace_id: str) -> SituatedEvaluationTrace | None: ...
```

Only `EnvironmentEventAdmissionService` owns the admission-store write capability. Store construction creates an identity-checked, non-serializable object capability and returns separate reader and writer views. The writer closure requires `token is bound_token`; a caller-created object, same-field object, copied value or deserialized value cannot satisfy it. Only the service receives the writer closure and token. The application exposes neither store writer/token nor mutable origin/lease/attestation registries.

V0 supplies deterministic composition-owned registries plus SQLite-backed admission and trace outbox stores. In-memory stores may exist for unit tests but cannot close restart/persistence gates.

## 5. Event admission service

Public entry:

```python
EnvironmentEventAdmissionService.admit(
    event_id: str,
    lease_id: str,
    *,
    admitted_at: datetime,
) -> EnvironmentEventAdmissionReceipt
```

The service resolves every authority input itself and enforces:

1. canonical event, adapter-derived origin, lease, current credential ref and adapter-derived payload attestation exist;
2. origin event id/event digest/observation digest equal the trusted event;
3. origin source config, credential ref and binding data match the adapter registration;
4. lease equals the registry object and current credential digest, status, scopes and expiry;
5. origin, lease, attestation, event and active mandate share principal/tenant/workspace/mandate/binding;
6. current `EnvironmentBindingAuthorization` version/digest are copied only into the newly constructed receipt and match active authority; origin carries only the adapter's binding id and cannot duplicate or override authority version/digest;
7. current correction epoch equals the lease and receipt epoch;
8. attestation event/source/artifact/digest/schema/policy match the origin and event;
9. trusted artifact bytes resolve through `SituationalTrustResolver`, have `situated:read`, and match exact SHA-256;
10. exact replay returns the durable original receipt;
11. same event id with changed origin, payload, lease, scope or epoch raises typed conflict.

Admission calls no provider and writes no assessment.

## 6. MandateSteward convergence facade

```python
MandateSteward.observe_event(
    event_id: str,
    projection_id: str,
    admission_receipt_id: str,
) -> TaskDraftProposal | HelpRequest | None
```

The steward receives the same `SituatedAssessmentStore` authority reader used by `OperationalProposalService`. Before provider invocation it resolves current Mandate/binding and requires exact receipt mandate, binding id/version/digest, principal scope and correction epoch.

It then:

1. creates or reuses a durable `PENDING` trace outbox entry and increments `delegation_attempt_count` before each delegation attempt;
2. delegates to the one existing `OperationalProposalService.propose(...)`;
3. derives `COMPLETED` trace state from the persisted result;
4. returns only after the trace is durable.

If completion fails after assessment persistence, no result is returned. A retry uses the existing persisted assessment replay, performs no second provider call, and reconciles the trace to `COMPLETED`.

The exact guarantee is limited to sequential and restart replay of an already committed assessment. V0 adds a process-local single-flight lock per receipt/projection to prevent concurrent duplicate provider calls in one process. It does not claim provider exactly-once across a crash before assessment commit or across multiple processes; those require provider idempotency/durable invocation claims.

`delegation_attempt_count` is an exact durable count of facade-to-service attempts, not provider calls. `committed_provider_call_attempted` is copied only from the committed assessment receipt and may be null while PENDING. The trace does not claim an exact total provider-call count across a crash window; a crash after provider invocation but before assessment commit can make provider activity externally unobservable in V0.

`AgentOSApplication.propose_situated_work` becomes admission-required and routes only through `MandateSteward`. Calling the legacy public entry without a receipt fails closed before provider and persistence. The raw `OperationalProposalService` remains an internal dependency, not a public bypass.

The facade never constructs another provider assessor, assessment store, event ledger or proposal compiler. It cannot import or call `TaskService`, `CapabilityBroker`, connectors or effect APIs. Existing `TaskDraftProposal` fixed-false authority fields remain unchanged.

## 7. Data Agent composition

The Data Agent adapter remains the existing exact-byte, credential-bound ingress and directly implements the read-only `EventOriginRegistryPort` and `PayloadAdmissionRegistryPort` from its existing durable observation state plus frozen configuration. Application composition injects these readers; it never receives or registers origin/attestation objects.

The implementation adds only derived immutable read methods/material:

- origin registration for an already ingested event, with `registered_at == event.recorded_at`;
- payload-admission attestation for the exact external-redacted observation, with `assessed_at` derived from the durable ingest record;
- source configuration digest and current credential-ref identity.

Application composition registers only a canonical lease through the composition-owned lease registry, admits the event through the adapter readers, then calls the admission-required steward entry. It does not copy origin/attestation objects or rewrite report fetching, strict JSON, HTTPS/origin checks, redaction checks, cursor/restart state or provider relevance. Repeated resolution after restart must return byte-equal origin and attestation contracts.

## 8. Security and failure semantics

- Unknown or forged origin/lease/attestation/receipt: provider 0, assessment 0.
- Cross-scope, stale binding, revoked credential, expired lease or epoch change: provider 0.
- Raw observation, prompt, response, exception, resolver key and credential secret never enter the new receipt/outbox trace.
- Caller/model text cannot satisfy origin, attestation, lease, evidence, activation or capability fields.
- Provider malformed/failure uses existing fail-closed relevance behavior.
- PENDING outbox recovery is deterministic; a completed result is never returned without a durable COMPLETED trace.
- Outbox transitions are closed: `PENDING -> COMPLETED | DENIED`; terminal records are immutable; exact terminal replay is idempotent; a different result binding or attempt history conflicts.
- Positive Task activation remains out of scope.

The slice does not implement general PII/DLP, production KMS, mTLS/source signing, distributed fencing or cross-process provider exactly-once.

## 9. Required RED matrix

Contract/digest:

- content-addressed ids and mutation sensitivity for every field;
- raw lowercase SHA only; chronology and numeric bounds;
- fixed-false authority/effect fields and closed trace reason enum.

Authority/admission:

- caller-minted source/lease/attestation/receipt rejected;
- direct receipt writes with a caller object, fake private proof, same-field token or serialized/deserialized token rejected;
- boolean “verified” lease without registry object rejected;
- event origin source cannot be selected by caller;
- current `CredentialRef` revoked/expired/scope drift after lease issue rejects;
- lease expiry beyond credential expiry rejects;
- binding version/digest or correction epoch drift rejects;
- same event id/different payload/source conflict; exact durable replay returns same receipt.

Steward/bypass:

- legacy public entry without receipt yields provider 0/assessment 0;
- stale receipt after epoch change rejects before provider;
- TaskDraft/Help/None/ABSTAIN result matrix equals the existing persisted record;
- constant `None`, constant digest and bypass persistence implementations fail tests;
- Task, Task event, connector and capability spies remain zero;
- forbidden-import AST gate;
- concurrent same-receipt requests delegate at most once in one process;
- committed assessment plus failed trace completion reconciles after restart without another provider call.
- crash after a recorded delegation attempt but before assessment commit increments the attempt count and makes no exact provider-total claim.

Data Agent:

- adapter readers derive origin/attestation exactly from source config, durable event state, credential, event and payload;
- caller/Application-supplied same-content origin or attestation is ignored/rejected, and restart derivation is byte-identical;
- foreign namespace, credential drift and raw secret reflection reject before provider;
- existing ingestion/restart/relevance suites remain green.

## 10. Parallel falsifier and non-claims

`P-SRL-E2E-FALSIFIER-1` is specified/frozen in parallel and blocks value, Founder-load, pilot and Dispatch claims, but not this infrastructure implementation.

No canonical merge, push, release, production activation, positive Task activation, autonomy, learning, training, multimodal, distributed-runtime or generic-domain claim follows. Local latency and token fields are `LOCAL_CONTROLLED` only.

## 11. Acceptance

Local completion requires real public admission and steward paths, SQLite restart evidence, RED/GREEN bypass proof, full Product/static gates and independent exact-diff approval. State may advance only to `IMPLEMENTED_LOCAL_NOT_INTEGRATED`; canonical integration remains a separate authorization.
