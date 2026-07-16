# P-SRL Event Admission 1 Design

> Status: `FOUNDER_DIRECTION_CONTINUED / DESIGN_FROZEN_FOR_LOCAL_IMPLEMENTATION`
> Primary requirement: `A/P`
> Product claim ceiling: `IMPLEMENTED_LOCAL / LOCAL_CONTROLLED`
> Base: `codex/p-srl-event-admission-1-20260717@8d5820c75a397a299bec898e783ee8113fd3d542`

## 1. Goal

Close the smallest real gap between an external observation adapter and the existing situated product spine: prove that an event came from a registered source under an exact credential, binding, scope, payload-safety policy and correction epoch before the existing `OperationalProposalService` may assess or persist it.

This is an admission and convergence slice, not a third event architecture and not a new Runtime.

## 2. Existing product spine to reuse

The implementation must reuse, not duplicate:

- `EnvironmentEvent`, `OperationalProjectionRef`, `RatifiedMandateRef`, `EnvironmentBindingAuthorization`;
- `SituationalTrustResolver`, `OperationalProposalService`, `ProviderRelevanceAssessor`;
- `SituatedAssessmentRecord`, `TaskDraftProposal`, `HelpRequest`;
- `SQLiteSituatedAssessmentStore` replay, pause, revoke and epoch behavior;
- `CredentialRef` and the existing credential broker boundary;
- the Data Agent report adapter as the first concrete source adapter.

`SrlEnvironmentEvent` remains an internal transport/invariant DTO. It does not become a second product event authority and it is not sufficient for admission by itself.

## 3. Selected design

### 3.1 Contracts

Create `agent_os_contracts.srl_event_admission` with these objects:

```python
class EventSourceRef(ContractModel):
    source_id: NonEmptyStr
    source_contract_digest: Sha256Digest
    credential_ref_digest: Sha256Digest
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    mandate_id: NonEmptyStr
    environment_binding_id: NonEmptyStr
    environment_binding_version: int
    environment_binding_digest: Sha256Digest
    schema_digest: Sha256Digest
    payload_safety_policy_digest: Sha256Digest
    read_capability_id: NonEmptyStr


class CredentialLeaseRef(ContractModel):
    lease_id: NonEmptyStr
    credential_ref_digest: Sha256Digest
    source_id: NonEmptyStr
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    mandate_id: NonEmptyStr
    environment_binding_id: NonEmptyStr
    correction_epoch: int
    valid_from: UtcDateTime
    expires_at: UtcDateTime
    issued_by: NonEmptyStr
    lease_digest: Sha256Digest


class PayloadSafetyAttestation(ContractModel):
    attestation_id: NonEmptyStr
    source_id: NonEmptyStr
    observation_artifact_id: NonEmptyStr
    observation_digest: Sha256Digest
    policy_digest: Sha256Digest
    schema_digest: Sha256Digest
    issued_by: NonEmptyStr
    assessed_at: UtcDateTime
    safe_for_model: Literal[True]
    contains_credentials: Literal[False]
    attestation_digest: Sha256Digest


class EnvironmentEventAdmissionReceipt(ContractModel):
    receipt_id: NonEmptyStr
    source: EventSourceRef
    credential_lease: CredentialLeaseRef
    payload_safety: PayloadSafetyAttestation
    environment_event_id: NonEmptyStr
    event_digest: Sha256Digest
    observation_digest: Sha256Digest
    correction_epoch: int
    admitted_at: UtcDateTime
    receipt_digest: Sha256Digest
    grants_authority: Literal[False] = False
    authorizes_effects: Literal[False] = False


class SituatedEvaluationTrace(ContractModel):
    trace_id: NonEmptyStr
    admission_receipt_digest: Sha256Digest
    event_id: NonEmptyStr
    projection_id: NonEmptyStr
    mandate_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    result_kind: Literal["TASK_DRAFT", "HELP_REQUEST", "NO_PROPOSAL", "DENIED"]
    reason_code: NonEmptyStr
    provider_call_count: int
    input_tokens: int | None
    output_tokens: int | None
    duration_ms: int
    measurement_scope: Literal["LOCAL_CONTROLLED"] = "LOCAL_CONTROLLED"
    recorded_at: UtcDateTime
```

All digest fields are raw lowercase SHA-256. Receipts are content addressed: their id is derived from their digest, and construction verifies the digest over every field except the digest/id pair.

### 3.2 Trusted registries and ports

Create narrow ports rather than a parallel security framework:

```python
class EventSourceRegistryPort(Protocol):
    def source(self, source_id: str) -> EventSourceRef | None: ...

class CredentialLeaseVerifierPort(Protocol):
    def verify(self, lease: CredentialLeaseRef, *, at: datetime) -> bool: ...

class PayloadSafetyRegistryPort(Protocol):
    def attestation(self, attestation_id: str) -> PayloadSafetyAttestation | None: ...

class EventAdmissionStorePort(Protocol):
    def put(self, receipt: EnvironmentEventAdmissionReceipt) -> EnvironmentEventAdmissionReceipt: ...
    def by_event_id(self, event_id: str) -> EnvironmentEventAdmissionReceipt | None: ...

class SituatedTraceStorePort(Protocol):
    def append(self, trace: SituatedEvaluationTrace) -> None: ...
```

V0 provides deterministic in-memory implementations. They are real product code for a local controlled slice, but not a production identity/KMS plane.

### 3.3 Event admission service

`EnvironmentEventAdmissionService.admit(...)` consumes only an existing trusted `EnvironmentEvent`, an exact source id, lease ref and safety attestation id. It resolves trusted objects from injected registries and enforces:

1. source equality with the registered source;
2. exact principal/tenant/workspace/mandate/binding id/version/digest scope;
3. binding exists in the active ratified mandate;
4. current mandate status and correction epoch;
5. lease is exact, current and source/binding/scope/epoch bound;
6. event observation digest equals the safety attestation digest;
7. safety policy/schema digests equal the source contract;
8. trusted event and artifact bytes resolve through the existing `SituationalTrustResolver` and match exact SHA-256;
9. duplicate event id with identical receipt returns the original receipt;
10. duplicate event id with changed source, payload or scope raises a typed conflict.

No provider is called and no assessment is written during admission.

### 3.4 MandateSteward convergence facade

`MandateSteward.observe_event(event_id, projection_id, admission_receipt_id)` is a thin facade over one existing `OperationalProposalService`.

It:

1. resolves the admission receipt;
2. rechecks active mandate/binding/epoch before assessment;
3. delegates exactly once to `OperationalProposalService.propose(...)`;
4. emits one safe `SituatedEvaluationTrace`;
5. returns the existing `TaskDraftProposal | HelpRequest | None`.

It never constructs a second assessor, event ledger, assessment store or proposal compiler. `TaskDraftProposal.activation_authorized` and `external_effects_authorized` remain false. It cannot call `TaskService`, `CapabilityBroker`, a connector or an effect path.

Trace persistence is part of the atomic acceptance boundary. If the required trace cannot be appended for a new result, the facade must fail closed and must not claim a completed M1-plus result. Exact replay may return the existing persisted result and trace without a second provider call.

## 4. Security boundary

This slice guarantees:

- no raw observation bytes, prompt, provider response, exception text, resolver key, credential or secret enters `SituatedEvaluationTrace`;
- no credential secret is serialized by any new contract;
- caller-created source/lease/safety objects have no authority unless they exactly equal trusted registry entries;
- source, principal, tenant, workspace, mandate, binding and correction epoch are checked before provider invocation;
- model narration cannot mint source identity, payload safety, evidence, activation or capability authority;
- provider output remains subject to existing strict parsing, authority-shaped-output rejection and trusted evidence binding.

This slice requires trusted upstream payload-safety attestation. It does not claim a general PII/DLP classifier. Production KMS/Vault, mTLS/webhook signing, tenant-specific encryption and distributed credential fencing remain controlled-pilot/release gates.

## 5. Failure behavior

| Failure | Result |
|---|---|
| unknown/forged source, lease or safety attestation | typed denial; provider 0; assessment writes 0 |
| cross-scope or binding drift | typed denial; provider 0; assessment writes 0 |
| expired/revoked/epoch-changed mandate or lease | typed denial; provider 0 |
| event/artifact/payload digest mismatch | typed denial; provider 0 |
| same event id with different receipt identity | typed conflict |
| provider malformed/failure | existing safe ABSTAIN/HELP behavior; no raw exception text |
| trace append failure | fail closed; no success claim |
| exact replay | same persisted result and trace; provider not called again |

## 6. Testing and falsification

Every new behavior starts RED. Required delta tests:

- exact source/lease/safety/binding admission;
- forged or caller-minted registry objects rejected;
- cross-tenant/principal/workspace/binding/epoch rejection before provider;
- non-SHA payload/digest and invalid chronology contract rejection;
- same event id/different payload conflict;
- exact receipt replay idempotency;
- `MandateSteward` uses one existing provider assessor and one existing assessment store;
- non-executing draft and zero Task/connector/capability effects;
- revoke/epoch change dominates between admission and assessment emission;
- safe trace allowlist and forbidden-content checks;
- jailbreak/model narration cannot satisfy admission or activation fields.

Existing situated, provider relevance, Data Agent ingress, replay/revoke and M0 invariant suites remain regression gates.

## 7. Parallel research gate

`P-SRL-E2E-FALSIFIER-1` is specified and frozen in parallel, not executed in this slice. It blocks product-value, Founder-cognitive-load, pilot and Dispatch claims; it does not block implementing admission/facade/trace infrastructure.

## 8. Non-goals and claims

- no canonical merge, push, release or production activation;
- no positive `TaskActivationGate` implementation;
- no automatic external effect;
- no new Runtime or replacement of `OperationalProposalService`;
- no general autonomy, domain adaptation, learning, training or multimodal claim;
- no production p99, distributed throughput or enterprise tenant-isolation claim;
- no claim that the system reduces Founder cognitive load until the E2E falsifier runs.

## 9. Acceptance

The slice is locally complete only when the public admission and steward facade have real code paths, all bypass tests and full Product/static gates pass, an independent reviewer approves the exact diff, and live state records `IMPLEMENTED_LOCAL_NOT_INTEGRATED`. Green tests do not authorize canonical integration.
