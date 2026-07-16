from __future__ import annotations

import hashlib
import importlib
import inspect
import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from threading import Barrier
from typing import Any, Mapping, cast

import pytest
from pydantic import BaseModel

from agent_os_contracts import (
    ArtifactLocationClass,
    ArtifactRef,
    CredentialLeaseRef,
    CredentialAuthorizationSnapshot,
    CredentialRef,
    CredentialStatus,
    EnvironmentBindingAuthorization,
    EnvironmentEvent,
    EnvironmentEventAdmissionReceipt,
    EventOriginRegistration,
    EvidenceRef,
    EvidenceSourceKind,
    PayloadAdmissionAttestation,
    RatifiedMandateRef,
    LedgerAccessScope,
    RelevanceAssessorRef,
    content_digest,
    credential_lease_digest,
    event_origin_registration_digest,
    payload_admission_attestation_digest,
)
from agent_os_core import (
    CanonicalCredentialAuthorizationReader,
    CanonicalCredentialLeaseRegistry,
    InMemorySituationalTrustRegistry,
    InMemorySituationalControlPlane,
    SituationalTrustDenied,
)
from agent_os_core.situated_persistence import SQLiteSituatedAssessmentStore
from agent_os_core.srl_event_admission import EnvironmentEventAdmissionService
from agent_os_core.srl_event_store import (
    EventAdmissionPersistenceConflict,
    ScopedEventAdmissionReader,
    _create_event_admission_store,
)


NOW = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
ADMITTED_AT = NOW + timedelta(minutes=5)
RAW_OBSERVATION = b'{"kind":"canonical-environment-event"}'
SOURCE_CONFIG_DIGEST = "a" * 64
EVENT_SCHEMA_DIGEST = "b" * 64
PAYLOAD_POLICY_DIGEST = "c" * 64
BINDING_DIGEST = "d" * 64
MANDATE_DIGEST = "e" * 64


def _admission_policy_digest(scopes: frozenset[str]) -> str:
    return content_digest({"required_credential_scopes": tuple(sorted(scopes))})


class _Lookup:
    def __init__(self, values: Mapping[str, Any]) -> None:
        self._values = dict(values)

    def resolve_event(self, event_id: str) -> Any | None:
        return self._values.get(event_id)


class _CredentialLookup:
    def __init__(self, values: Mapping[str, CredentialRef]) -> None:
        self._values = dict(values)

    def resolve_authorization(
        self, credential_ref_id: str
    ) -> CredentialAuthorizationSnapshot | None:
        credential = self._values.get(credential_ref_id)
        if credential is None:
            return None
        return CredentialAuthorizationSnapshot(
            credential_ref_id=credential.credential_ref_id,
            credential_ref_digest=content_digest(credential),
            owner_principal_id=credential.owner_principal_id,
            tenant_id=credential.tenant_id,
            workspace_id=credential.workspace_id,
            provider_id=credential.provider_id,
            scopes=credential.scopes,
            status=credential.status,
            created_at=credential.created_at,
            expires_at=credential.expires_at,
        )


class _LeaseLookup:
    def __init__(self, values: Mapping[str, CredentialLeaseRef]) -> None:
        self._values = dict(values)

    def resolve(self, lease_id: str) -> CredentialLeaseRef | None:
        return self._values.get(lease_id)


class _WriterSpy:
    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.calls = 0

    def persist_receipt(
        self, receipt: EnvironmentEventAdmissionReceipt
    ) -> EnvironmentEventAdmissionReceipt:
        self.calls += 1
        return cast(EnvironmentEventAdmissionReceipt, self.delegate.persist_receipt(receipt))


class _BarrierWriter(_WriterSpy):
    def __init__(self, delegate: Any, barrier: Barrier) -> None:
        super().__init__(delegate)
        self._barrier = barrier

    def persist_receipt(
        self, receipt: EnvironmentEventAdmissionReceipt
    ) -> EnvironmentEventAdmissionReceipt:
        self._barrier.wait(timeout=5)
        return super().persist_receipt(receipt)


class _ArtifactRefSubclass(ArtifactRef):
    pass


class _EvidenceTupleSubclass(tuple[Any, ...]):
    pass


def _artifact() -> ArtifactRef:
    return ArtifactRef(
        artifact_id="artifact:event-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        content_digest=hashlib.sha256(RAW_OBSERVATION).hexdigest(),
        media_type="application/json",
        location_class=ArtifactLocationClass.OBJECT_STORE,
        location_ref="object://event-1",
        acl_scopes=("situated:read",),
        retention_policy="retain-30-days",
        created_by="environment-adapter:test",
        created_at=NOW - timedelta(minutes=4),
    )


def _event(*, artifact: ArtifactRef | None = None) -> EnvironmentEvent:
    observation = artifact or _artifact()
    evidence = EvidenceRef(
        evidence_id="evidence:event-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        source_kind=EvidenceSourceKind.ARTIFACT,
        source_ref=observation.artifact_id,
        relation="supports",
        artifact_ids=(observation.artifact_id,),
        created_by="environment-adapter:test",
        created_at=NOW - timedelta(minutes=3),
    )
    return EnvironmentEvent(
        environment_event_id="event-1",
        environment_binding_id="binding-1",
        mandate_id="mandate-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        event_type_ref="external.observation.v1",
        dedupe_key="source-1:revision-1",
        observation=observation,
        evidence=(evidence,),
        occurred_at=NOW - timedelta(minutes=4),
        recorded_at=NOW - timedelta(minutes=3),
    )


def _rebuilt_event(event: EnvironmentEvent, **updates: Any) -> EnvironmentEvent:
    payload = event.model_dump(mode="python")
    payload.update(updates)
    return EnvironmentEvent.model_validate(payload)


def _credential() -> CredentialRef:
    return CredentialRef(
        credential_ref_id="credential-1",
        owner_principal_id="principal-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        provider_id="source-adapter-1",
        resolver_key="opaque-key-ref",
        scopes=("events:read", "situated:read"),
        status=CredentialStatus.ACTIVE,
        created_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(hours=2),
    )


def _lease(credential: CredentialRef) -> CredentialLeaseRef:
    payload = {
        "schema_version": "1.0",
        "credential_ref_id": credential.credential_ref_id,
        "credential_ref_digest": content_digest(credential),
        "source_id": "source-1",
        "principal_id": "principal-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "mandate_id": "mandate-1",
        "environment_binding_id": "binding-1",
        "correction_epoch": 3,
        "issued_at": NOW - timedelta(hours=1),
        "valid_from": NOW - timedelta(minutes=30),
        "expires_at": NOW + timedelta(hours=1),
        "issuer_id": "credential-authority/v1",
    }
    digest = credential_lease_digest(payload)
    return CredentialLeaseRef(
        lease_id=f"credential-lease:{digest}", lease_digest=digest, **payload
    )


def _origin(event: EnvironmentEvent, credential: CredentialRef) -> EventOriginRegistration:
    payload = {
        "schema_version": "1.0",
        "environment_event_id": event.environment_event_id,
        "source_id": "source-1",
        "source_config_digest": SOURCE_CONFIG_DIGEST,
        "credential_ref_id": credential.credential_ref_id,
        "credential_ref_digest": content_digest(credential),
        "principal_id": "principal-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "mandate_id": "mandate-1",
        "environment_binding_id": "binding-1",
        "event_digest": content_digest(event),
        "observation_digest": event.observation.content_digest,
        "event_schema_digest": EVENT_SCHEMA_DIGEST,
        "payload_policy_digest": PAYLOAD_POLICY_DIGEST,
        "registered_at": NOW - timedelta(minutes=2),
    }
    digest = event_origin_registration_digest(payload)
    return EventOriginRegistration(
        registration_id=f"event-origin:{digest}",
        registration_digest=digest,
        **payload,
    )


def _attestation(event: EnvironmentEvent) -> PayloadAdmissionAttestation:
    payload = {
        "schema_version": "1.0",
        "environment_event_id": event.environment_event_id,
        "source_id": "source-1",
        "observation_artifact_id": event.observation.artifact_id,
        "observation_digest": event.observation.content_digest,
        "policy_digest": PAYLOAD_POLICY_DIGEST,
        "schema_digest": EVENT_SCHEMA_DIGEST,
        "issuer_id": "payload-admission-policy/v1",
        "assessed_at": NOW - timedelta(minutes=1),
        "disposition": "ADMITTED_UNDER_POLICY",
        "credential_reflected": False,
    }
    digest = payload_admission_attestation_digest(payload)
    return PayloadAdmissionAttestation(
        attestation_id=f"payload-admission:{digest}",
        attestation_digest=digest,
        **payload,
    )


def _mandate() -> RatifiedMandateRef:
    return RatifiedMandateRef(
        mandate_id="mandate-1",
        version=1,
        mandate_digest=MANDATE_DIGEST,
        ratification_receipt_id="ratification-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        owner_principal_id="principal-1",
        ratified_by="founder-1",
        ratified_at=NOW - timedelta(days=1),
        valid_from=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=30),
        correction_epoch=3,
        authority_envelope_digest="f" * 64,
        allowed_environment_bindings=(
            EnvironmentBindingAuthorization(
                environment_binding_id="binding-1",
                version=4,
                binding_digest=BINDING_DIGEST,
            ),
        ),
        relevance_assessor=RelevanceAssessorRef(
            assessor_id="assessor-1", version=1, policy_digest="1" * 64
        ),
    )


def _rebuilt_origin(
    origin: EventOriginRegistration, **updates: Any
) -> EventOriginRegistration:
    payload = origin.model_dump(
        mode="python", exclude={"registration_id", "registration_digest"}
    )
    payload.update(updates)
    digest = event_origin_registration_digest(payload)
    return EventOriginRegistration(
        registration_id=f"event-origin:{digest}",
        registration_digest=digest,
        **payload,
    )


def _rebuilt_lease(lease: CredentialLeaseRef, **updates: Any) -> CredentialLeaseRef:
    payload = lease.model_dump(mode="python", exclude={"lease_id", "lease_digest"})
    payload.update(updates)
    digest = credential_lease_digest(payload)
    return CredentialLeaseRef(
        lease_id=f"credential-lease:{digest}", lease_digest=digest, **payload
    )


def _rebuilt_attestation(
    attestation: PayloadAdmissionAttestation, **updates: Any
) -> PayloadAdmissionAttestation:
    payload = attestation.model_dump(
        mode="python", exclude={"attestation_id", "attestation_digest"}
    )
    payload.update(updates)
    digest = payload_admission_attestation_digest(payload)
    return PayloadAdmissionAttestation(
        attestation_id=f"payload-admission:{digest}",
        attestation_digest=digest,
        **payload,
    )


def _field_mutation(value: Any) -> Any:
    if isinstance(value, bool):
        return not value
    if isinstance(value, datetime):
        return value + timedelta(microseconds=1)
    if isinstance(value, int):
        return value + 1
    if isinstance(value, Enum):
        return next(member for member in type(value) if member is not value)
    if isinstance(value, str):
        return f"{value}-mutated"
    if isinstance(value, BaseModel):
        return value.model_copy(update={"__mutation_probe__": True})
    if isinstance(value, tuple):
        if value and isinstance(value[0], BaseModel):
            first = value[0]
            field_name = next(
                name
                for name in type(first).model_fields
                if isinstance(getattr(first, name), str) and name != "schema_version"
            )
            changed = first.model_copy(
                update={field_name: f"{getattr(first, field_name)}-mutated"}
            )
            return (changed, *value[1:])
        return (*value, "mutation-probe")
    raise AssertionError(f"unsupported admission field mutation: {value!r}")


_ADMISSION_FIELD_CASES = tuple(
    (target, field_name)
    for target, model_type in (
        ("event", EnvironmentEvent),
        ("origin", EventOriginRegistration),
        ("credential", CredentialRef),
        ("lease", CredentialLeaseRef),
        ("attestation", PayloadAdmissionAttestation),
    )
    for field_name in model_type.model_fields
)


def _build_service(
    tmp_path: Path,
    *,
    event: EnvironmentEvent | None = None,
    trusted_artifact: ArtifactRef | None = None,
    raw_observation: bytes = RAW_OBSERVATION,
    credential: CredentialRef | None = None,
    lease: CredentialLeaseRef | None = None,
    origin: EventOriginRegistration | None = None,
    attestation: PayloadAdmissionAttestation | None = None,
    mandate: RatifiedMandateRef | None = None,
    trust_event: bool = True,
    trust_artifact: bool = True,
    origin_available: bool = True,
    lease_available: bool = True,
    credential_available: bool = True,
    attestation_available: bool = True,
    principal_id: str = "principal-1",
    required_scopes: frozenset[str] = frozenset({"events:read"}),
    database_name: str = "admission.sqlite3",
    authority: Any | None = None,
    writer_wrapper: Any | None = None,
) -> tuple[EnvironmentEventAdmissionService, ScopedEventAdmissionReader, Any]:
    canonical_event = event or _event()
    canonical_credential = credential or _credential()
    canonical_lease = lease or _lease(canonical_credential)
    canonical_origin = origin or _origin(canonical_event, canonical_credential)
    canonical_attestation = attestation or _attestation(canonical_event)
    current_authority = authority or SQLiteSituatedAssessmentStore(
        tmp_path / f"authority-{database_name}", mandates=(mandate or _mandate(),)
    )
    scope = LedgerAccessScope(
        principal_id=principal_id,
        tenant_id=canonical_event.tenant_id,
        workspace_id=canonical_event.workspace_id,
    )
    reader, writer = _create_event_admission_store(
        tmp_path / database_name, scope=scope
    )
    injected_writer = writer_wrapper(writer) if writer_wrapper is not None else writer
    service = EnvironmentEventAdmissionService(
        trust=InMemorySituationalTrustRegistry(
            artifacts=(
                (((trusted_artifact or canonical_event.observation), raw_observation),)
                if trust_artifact
                else ()
            ),
            events=((canonical_event,) if trust_event else ()),
        ),
        authority=current_authority.scoped_reader(scope),
        origins=_Lookup(
            {canonical_event.environment_event_id: canonical_origin}
            if origin_available
            else {}
        ),
        leases=_LeaseLookup(
            {canonical_lease.lease_id: canonical_lease} if lease_available else {}
        ),
        credentials=_CredentialLookup(
            {canonical_credential.credential_ref_id: canonical_credential}
            if credential_available
            else {}
        ),
        attestations=_Lookup(
            {canonical_event.environment_event_id: canonical_attestation}
            if attestation_available
            else {}
        ),
        admission_reader=reader,
        admission_writer=injected_writer,
        principal_id=principal_id,
        required_credential_scopes=required_scopes,
    )
    return service, reader, injected_writer


def test_admits_canonical_event_with_current_authority_and_exact_bytes(
    tmp_path: Path,
) -> None:
    module = importlib.import_module("agent_os_core.srl_event_admission")
    event = _event()
    credential = _credential()
    lease = _lease(credential)
    origin = _origin(event, credential)
    attestation = _attestation(event)
    authority = SQLiteSituatedAssessmentStore(
        tmp_path / "authority.sqlite3", mandates=(_mandate(),)
    )
    scope = LedgerAccessScope(
        principal_id="principal-1", tenant_id="tenant-1", workspace_id="workspace-1"
    )
    reader, writer = _create_event_admission_store(
        tmp_path / "admission.sqlite3", scope=scope
    )
    service = module.EnvironmentEventAdmissionService(
        trust=InMemorySituationalTrustRegistry(
            artifacts=((event.observation, RAW_OBSERVATION),), events=(event,)
        ),
        authority=authority.scoped_reader(scope),
        origins=_Lookup({event.environment_event_id: origin}),
        leases=CanonicalCredentialLeaseRegistry((lease,)),
        credentials=CanonicalCredentialAuthorizationReader((credential,)),
        attestations=_Lookup({event.environment_event_id: attestation}),
        admission_reader=reader,
        admission_writer=writer,
        principal_id="principal-1",
        required_credential_scopes=frozenset({"events:read"}),
    )

    receipt = service.admit(
        event.environment_event_id, lease.lease_id, admitted_at=ADMITTED_AT
    )

    assert reader.by_event_id(event.environment_event_id) == receipt
    assert receipt.event_digest == content_digest(event)
    assert receipt.event_origin_digest == origin.registration_digest
    assert receipt.credential_lease_digest == lease.lease_digest
    assert receipt.payload_attestation_digest == attestation.attestation_digest
    assert receipt.admission_policy_digest == _admission_policy_digest(
        frozenset({"events:read"})
    )
    assert receipt.environment_binding_version == 4
    assert receipt.environment_binding_digest == BINDING_DIGEST
    assert receipt.correction_epoch == 3
    assert receipt.admitted_at == ADMITTED_AT
    assert receipt.grants_authority is False
    assert receipt.authorizes_effects is False
    assert "opaque-key-ref" not in receipt.model_dump_json()


@pytest.mark.parametrize(
    "missing",
    ["event", "origin", "lease", "credential", "attestation", "artifact"],
)
def test_each_missing_resolver_input_denies_before_writer_call(
    tmp_path: Path, missing: str
) -> None:
    kwargs = {
        "trust_event": missing != "event",
        "origin_available": missing != "origin",
        "lease_available": missing != "lease",
        "credential_available": missing != "credential",
        "attestation_available": missing != "attestation",
        "trust_artifact": missing != "artifact",
        "writer_wrapper": _WriterSpy,
    }
    service, _, writer = _build_service(tmp_path, **kwargs)

    with pytest.raises(SituationalTrustDenied):
        service.admit("event-1", _lease(_credential()).lease_id, admitted_at=ADMITTED_AT)

    assert writer.calls == 0


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("naive_time", "time"),
        ("wrong_principal", "principal"),
        ("credential_owner", "principal"),
        ("credential_tenant", "scope"),
        ("credential_workspace", "scope"),
        ("credential_created_after", "created"),
        ("missing_scope", "scope"),
        ("revoked_credential", "active"),
        ("expired_credential", "validity"),
        ("lease_beyond_credential", "validity"),
        ("stale_epoch", "epoch"),
        ("origin_source", "source"),
        ("attestation_policy", "attestation"),
        ("attestation_schema", "attestation"),
        ("attestation_artifact", "attestation"),
        ("event_digest", "event digest"),
        ("credential_digest", "credential"),
        ("artifact_ref", "artifact"),
        ("artifact_acl", "scope"),
        ("artifact_bytes", "bytes"),
    ],
)
def test_mutated_or_stale_material_denies_before_writer_call(
    tmp_path: Path, case: str, expected: str
) -> None:
    event = _event()
    credential = _credential()
    lease = _lease(credential)
    origin = _origin(event, credential)
    attestation = _attestation(event)
    admitted_at = ADMITTED_AT
    principal_id = "principal-1"
    required_scopes = frozenset({"events:read"})
    raw = RAW_OBSERVATION
    trusted_artifact = None
    if case == "naive_time":
        admitted_at = ADMITTED_AT.replace(tzinfo=None)
    elif case == "wrong_principal":
        principal_id = "attacker"
    elif case == "credential_owner":
        credential = credential.model_copy(update={"owner_principal_id": "attacker"})
        origin = _rebuilt_origin(origin, credential_ref_digest=content_digest(credential))
        lease = _rebuilt_lease(lease, credential_ref_digest=content_digest(credential))
    elif case == "credential_tenant":
        credential = credential.model_copy(update={"tenant_id": "tenant-other"})
        origin = _rebuilt_origin(origin, credential_ref_digest=content_digest(credential))
        lease = _rebuilt_lease(lease, credential_ref_digest=content_digest(credential))
    elif case == "credential_workspace":
        credential = credential.model_copy(update={"workspace_id": "workspace-other"})
        origin = _rebuilt_origin(origin, credential_ref_digest=content_digest(credential))
        lease = _rebuilt_lease(lease, credential_ref_digest=content_digest(credential))
    elif case == "credential_created_after":
        credential = credential.model_copy(update={"created_at": ADMITTED_AT + timedelta(seconds=1)})
        origin = _rebuilt_origin(origin, credential_ref_digest=content_digest(credential))
        lease = _rebuilt_lease(lease, credential_ref_digest=content_digest(credential))
    elif case == "missing_scope":
        required_scopes = frozenset({"events:admin"})
    elif case == "revoked_credential":
        credential = credential.model_copy(update={"status": CredentialStatus.REVOKED})
        origin = _rebuilt_origin(origin, credential_ref_digest=content_digest(credential))
        lease = _rebuilt_lease(lease, credential_ref_digest=content_digest(credential))
    elif case == "expired_credential":
        credential = credential.model_copy(update={"expires_at": NOW + timedelta(minutes=1)})
        origin = _rebuilt_origin(origin, credential_ref_digest=content_digest(credential))
        lease = _rebuilt_lease(lease, credential_ref_digest=content_digest(credential))
    elif case == "lease_beyond_credential":
        credential = credential.model_copy(update={"expires_at": NOW + timedelta(minutes=30)})
        origin = _rebuilt_origin(origin, credential_ref_digest=content_digest(credential))
        lease = _rebuilt_lease(lease, credential_ref_digest=content_digest(credential))
    elif case == "stale_epoch":
        lease = _rebuilt_lease(lease, correction_epoch=2)
    elif case == "origin_source":
        origin = _rebuilt_origin(origin, source_id="other-source")
    elif case == "attestation_policy":
        attestation = _rebuilt_attestation(attestation, policy_digest="2" * 64)
    elif case == "attestation_schema":
        attestation = _rebuilt_attestation(attestation, schema_digest="2" * 64)
    elif case == "attestation_artifact":
        attestation = _rebuilt_attestation(
            attestation, observation_artifact_id="artifact:other"
        )
    elif case == "event_digest":
        origin = _rebuilt_origin(origin, event_digest="2" * 64)
    elif case == "credential_digest":
        origin = _rebuilt_origin(origin, credential_ref_digest="2" * 64)
    elif case == "artifact_ref":
        trusted_artifact = event.observation
        changed = event.observation.model_copy(update={"location_ref": "object://other"})
        event = _event(artifact=changed)
        origin = _origin(event, credential)
        attestation = _attestation(event)
    elif case == "artifact_acl":
        changed = event.observation.model_copy(update={"acl_scopes": ("other:read",)})
        event = _event(artifact=changed)
        origin = _origin(event, credential)
        attestation = _attestation(event)
    elif case == "artifact_bytes":
        raw = b"changed-bytes"
    service, _, writer = _build_service(
        tmp_path,
        event=event,
        trusted_artifact=trusted_artifact,
        raw_observation=raw,
        credential=credential,
        lease=lease,
        origin=origin,
        attestation=attestation,
        principal_id=principal_id,
        required_scopes=required_scopes,
        writer_wrapper=_WriterSpy,
    )

    with pytest.raises(SituationalTrustDenied, match=expected):
        service.admit("event-1", lease.lease_id, admitted_at=admitted_at)

    assert writer.calls == 0


@pytest.mark.parametrize(
    "case",
    [
        "origin_id",
        "origin_digest",
        "lease_id",
        "lease_digest",
        "attestation_id",
        "attestation_digest",
    ],
)
def test_forged_content_addressed_authority_root_denies_before_write(
    tmp_path: Path, case: str
) -> None:
    event = _event()
    credential = _credential()
    lease = _lease(credential)
    origin = _origin(event, credential)
    attestation = _attestation(event)
    if case == "origin_id":
        origin = origin.model_copy(update={"registration_id": "event-origin:forged"})
    elif case == "origin_digest":
        origin = origin.model_copy(update={"registration_digest": "2" * 64})
    elif case == "lease_id":
        lease = lease.model_copy(update={"lease_id": "credential-lease:forged"})
    elif case == "lease_digest":
        lease = lease.model_copy(update={"lease_digest": "2" * 64})
    elif case == "attestation_id":
        attestation = attestation.model_copy(
            update={"attestation_id": "payload-admission:forged"}
        )
    else:
        attestation = attestation.model_copy(update={"attestation_digest": "2" * 64})
    service, _, writer = _build_service(
        tmp_path,
        event=event,
        credential=credential,
        lease=lease,
        origin=origin,
        attestation=attestation,
        writer_wrapper=_WriterSpy,
    )

    with pytest.raises(SituationalTrustDenied, match="canonical"):
        service.admit("event-1", lease.lease_id, admitted_at=ADMITTED_AT)

    assert writer.calls == 0


@pytest.mark.parametrize(("target", "field_name"), _ADMISSION_FIELD_CASES)
def test_every_canonical_admission_field_mutation_denies_before_write(
    tmp_path: Path, target: str, field_name: str
) -> None:
    event = _event()
    credential = _credential()
    lease = _lease(credential)
    origin = _origin(event, credential)
    attestation = _attestation(event)
    values: dict[str, BaseModel] = {
        "event": event,
        "origin": origin,
        "credential": credential,
        "lease": lease,
        "attestation": attestation,
    }
    current = values[target]
    values[target] = current.model_copy(
        update={field_name: _field_mutation(getattr(current, field_name))}
    )
    mutated_event = cast(EnvironmentEvent, values["event"])
    mutated_credential = cast(CredentialRef, values["credential"])
    mutated_lease = cast(CredentialLeaseRef, values["lease"])
    service, reader, writer = _build_service(
        tmp_path,
        event=mutated_event,
        credential=mutated_credential,
        lease=mutated_lease,
        origin=cast(EventOriginRegistration, values["origin"]),
        attestation=cast(PayloadAdmissionAttestation, values["attestation"]),
        writer_wrapper=_WriterSpy,
    )

    with pytest.raises(SituationalTrustDenied):
        service.admit("event-1", mutated_lease.lease_id, admitted_at=ADMITTED_AT)

    assert writer.calls == 0
    assert reader.by_event_id("event-1") is None


def test_every_field_matrix_covers_exact_model_fields() -> None:
    expected = {
        "event": set(EnvironmentEvent.model_fields),
        "origin": set(EventOriginRegistration.model_fields),
        "credential": set(CredentialRef.model_fields),
        "lease": set(CredentialLeaseRef.model_fields),
        "attestation": set(PayloadAdmissionAttestation.model_fields),
    }
    actual = {
        target: {
            field_name
            for case_target, field_name in _ADMISSION_FIELD_CASES
            if case_target == target
        }
        for target in expected
    }
    assert actual == expected


@pytest.mark.parametrize("field_name", tuple(EnvironmentBindingAuthorization.model_fields))
def test_every_current_binding_field_mutation_denies_or_conflicts_before_write(
    tmp_path: Path, field_name: str
) -> None:
    first, _, _ = _build_service(
        tmp_path,
        authority=InMemorySituationalControlPlane((_mandate(),)),
        database_name="shared.sqlite3",
    )
    lease = _lease(_credential())
    first.admit("event-1", lease.lease_id, admitted_at=ADMITTED_AT)
    mandate = _mandate()
    binding = mandate.allowed_environment_bindings[0]
    mutated_binding = binding.model_copy(
        update={field_name: _field_mutation(getattr(binding, field_name))}
    )
    changed_authority = InMemorySituationalControlPlane(
        (mandate.model_copy(update={"allowed_environment_bindings": (mutated_binding,)}),)
    )
    restarted, reader, writer = _build_service(
        tmp_path,
        authority=changed_authority,
        database_name="shared.sqlite3",
        writer_wrapper=_WriterSpy,
    )

    with pytest.raises((SituationalTrustDenied, EventAdmissionPersistenceConflict)):
        restarted.admit(
            "event-1", lease.lease_id, admitted_at=ADMITTED_AT + timedelta(seconds=1)
        )

    assert writer.calls == 0
    assert reader.by_event_id("event-1") is not None


@pytest.mark.parametrize(
    "injected_key",
    [
        "registrationId",
        "registration_id_alias",
        "eventDigest",
        "registration_id\u200b",
        "ｒｅｇｉｓｔｒａｔｉｏｎ＿ｉｄ",
    ],
)
def test_origin_raw_shape_alias_and_unicode_injection_denies_before_write(
    tmp_path: Path, injected_key: str
) -> None:
    event = _event()
    credential = _credential()
    origin = _origin(event, credential).model_copy(
        update={injected_key: "attacker-controlled"}
    )
    service, _, writer = _build_service(
        tmp_path,
        event=event,
        credential=credential,
        origin=origin,
        writer_wrapper=_WriterSpy,
    )

    with pytest.raises(SituationalTrustDenied, match="canonical"):
        service.admit("event-1", _lease(credential).lease_id, admitted_at=ADMITTED_AT)

    assert writer.calls == 0


def test_nested_artifact_raw_shape_injection_denies_before_write(
    tmp_path: Path,
) -> None:
    canonical = _event()
    forged_artifact = canonical.observation.model_copy(
        update={"contentDigest": canonical.observation.content_digest}
    )
    event = canonical.model_copy(update={"observation": forged_artifact})
    credential = _credential()
    service, _, writer = _build_service(
        tmp_path,
        event=event,
        origin=_origin(event, credential),
        attestation=_attestation(event),
        writer_wrapper=_WriterSpy,
    )

    with pytest.raises(SituationalTrustDenied, match="canonical"):
        service.admit("event-1", _lease(credential).lease_id, admitted_at=ADMITTED_AT)

    assert writer.calls == 0


def test_resolved_artifact_unknown_field_denies_without_pydantic_equality(
    tmp_path: Path,
) -> None:
    event = _event()
    forged_resolved_ref = event.observation.model_copy(
        update={"contentDigest": event.observation.content_digest}
    )
    service, _, writer = _build_service(
        tmp_path,
        event=event,
        trusted_artifact=forged_resolved_ref,
        writer_wrapper=_WriterSpy,
    )

    with pytest.raises(SituationalTrustDenied, match="canonical"):
        service.admit("event-1", _lease(_credential()).lease_id, admitted_at=ADMITTED_AT)

    assert writer.calls == 0


@pytest.mark.parametrize(
    "shape_attack",
    ["nested_model_subclass", "origin_private_state", "nested_container_subclass"],
)
def test_raw_to_decoded_tree_shape_attack_denies_before_write(
    tmp_path: Path, shape_attack: str
) -> None:
    event = _event()
    credential = _credential()
    origin = _origin(event, credential)
    if shape_attack == "nested_model_subclass":
        forged_artifact = _ArtifactRefSubclass.model_validate(
            event.observation.model_dump()
        )
        event = event.model_copy(update={"observation": forged_artifact})
    elif shape_attack == "origin_private_state":
        object.__setattr__(
            origin,
            "__pydantic_private__",
            {"_hidden": "attacker-controlled"},
        )
    else:
        event = event.model_copy(
            update={"evidence": _EvidenceTupleSubclass(event.evidence)}
        )
    service, reader, writer = _build_service(
        tmp_path,
        event=event,
        credential=credential,
        origin=origin,
        attestation=_attestation(event),
        writer_wrapper=_WriterSpy,
    )

    with pytest.raises(SituationalTrustDenied, match="canonical"):
        service.admit("event-1", _lease(credential).lease_id, admitted_at=ADMITTED_AT)

    assert writer.calls == 0
    assert reader.by_event_id("event-1") is None


@pytest.mark.parametrize("status", ["paused", "revoked", "expired"])
def test_non_active_current_mandate_denies_before_writer_call(
    tmp_path: Path, status: str
) -> None:
    authority = InMemorySituationalControlPlane((_mandate(),))
    if status == "paused":
        authority.pause("mandate-1", expected_epoch=3)
    elif status == "revoked":
        authority.revoke("mandate-1", expected_epoch=3)
    else:
        expired = _mandate().model_copy(update={"expires_at": NOW + timedelta(minutes=1)})
        authority = InMemorySituationalControlPlane((expired,))
    service, _, writer = _build_service(
        tmp_path, authority=authority, writer_wrapper=_WriterSpy
    )

    with pytest.raises(SituationalTrustDenied):
        service.admit("event-1", _lease(_credential()).lease_id, admitted_at=ADMITTED_AT)

    assert writer.calls == 0


def test_restart_revalidates_current_authority_then_returns_original_bytes(
    tmp_path: Path,
) -> None:
    service, reader, _ = _build_service(tmp_path)
    lease = _lease(_credential())
    original = service.admit("event-1", lease.lease_id, admitted_at=ADMITTED_AT)

    restarted, restarted_reader, _ = _build_service(
        tmp_path, database_name="admission.sqlite3"
    )
    replay = restarted.admit(
        "event-1", lease.lease_id, admitted_at=ADMITTED_AT + timedelta(minutes=1)
    )

    assert replay == original
    assert replay.admitted_at == ADMITTED_AT
    assert replay.receipt_id == original.receipt_id
    assert replay.receipt_digest == original.receipt_digest
    assert restarted_reader.by_event_id("event-1") == original


def test_restart_with_different_constructor_scope_policy_conflicts(
    tmp_path: Path,
) -> None:
    first, _, _ = _build_service(
        tmp_path,
        required_scopes=frozenset({"events:read"}),
        database_name="shared.sqlite3",
    )
    lease = _lease(_credential())
    first.admit("event-1", lease.lease_id, admitted_at=ADMITTED_AT)
    restarted, _, writer = _build_service(
        tmp_path,
        required_scopes=frozenset({"situated:read"}),
        database_name="shared.sqlite3",
        writer_wrapper=_WriterSpy,
    )

    with pytest.raises(EventAdmissionPersistenceConflict):
        restarted.admit(
            "event-1", lease.lease_id, admitted_at=ADMITTED_AT + timedelta(minutes=1)
        )

    assert writer.calls == 0


@pytest.mark.parametrize(
    "changed_root",
    [
        "origin_source_config",
        "origin_registered_at",
        "lease_issuer",
        "attestation_issuer",
        "attestation_assessed_at",
        "event_content",
        "binding_version",
        "binding_digest",
        "correction_epoch",
    ],
)
def test_restart_changed_authority_material_conflicts_without_second_write(
    tmp_path: Path, changed_root: str
) -> None:
    first_authority = InMemorySituationalControlPlane((_mandate(),))
    first, _, _ = _build_service(
        tmp_path, authority=first_authority, database_name="shared.sqlite3"
    )
    credential = _credential()
    lease = _lease(credential)
    first.admit("event-1", lease.lease_id, admitted_at=ADMITTED_AT)
    event = _event()
    origin = _origin(event, credential)
    attestation = _attestation(event)
    mandate = _mandate()
    if changed_root == "origin_source_config":
        origin = _rebuilt_origin(origin, source_config_digest="2" * 64)
    elif changed_root == "origin_registered_at":
        origin = _rebuilt_origin(
            origin, registered_at=origin.registered_at - timedelta(seconds=1)
        )
    elif changed_root == "lease_issuer":
        lease = _rebuilt_lease(lease, issuer_id="credential-authority/v2")
    elif changed_root == "attestation_issuer":
        attestation = _rebuilt_attestation(
            attestation, issuer_id="payload-admission-policy/v2"
        )
    elif changed_root == "attestation_assessed_at":
        attestation = _rebuilt_attestation(
            attestation, assessed_at=attestation.assessed_at - timedelta(seconds=1)
        )
    elif changed_root == "event_content":
        event = _rebuilt_event(event, dedupe_key="source-1:revision-2")
        origin = _origin(event, credential)
        attestation = _attestation(event)
    elif changed_root in {"binding_version", "binding_digest"}:
        binding = mandate.allowed_environment_bindings[0].model_copy(
            update={
                "version": 5 if changed_root == "binding_version" else 4,
                "binding_digest": (
                    "2" * 64 if changed_root == "binding_digest" else BINDING_DIGEST
                ),
            }
        )
        mandate = mandate.model_copy(update={"allowed_environment_bindings": (binding,)})
    else:
        mandate = mandate.model_copy(update={"correction_epoch": 4})
        lease = _rebuilt_lease(lease, correction_epoch=4)
    restarted_authority = InMemorySituationalControlPlane((mandate,))
    restarted, _, writer = _build_service(
        tmp_path,
        event=event,
        credential=credential,
        lease=lease,
        origin=origin,
        attestation=attestation,
        authority=restarted_authority,
        database_name="shared.sqlite3",
        writer_wrapper=_WriterSpy,
    )

    with pytest.raises(EventAdmissionPersistenceConflict):
        restarted.admit("event-1", lease.lease_id, admitted_at=ADMITTED_AT)

    assert writer.calls == 0


def test_restart_does_not_short_circuit_current_authority_revocation(
    tmp_path: Path,
) -> None:
    authority = InMemorySituationalControlPlane((_mandate(),))
    first, _, _ = _build_service(
        tmp_path, authority=authority, database_name="shared.sqlite3"
    )
    lease = _lease(_credential())
    original = first.admit("event-1", lease.lease_id, admitted_at=ADMITTED_AT)
    authority.revoke("mandate-1", expected_epoch=3)
    restarted, reader, writer = _build_service(
        tmp_path,
        authority=authority,
        database_name="shared.sqlite3",
        writer_wrapper=_WriterSpy,
    )

    with pytest.raises(SituationalTrustDenied):
        restarted.admit(
            "event-1", lease.lease_id, admitted_at=ADMITTED_AT + timedelta(minutes=1)
        )

    assert reader.by_event_id("event-1") == original
    assert writer.calls == 0


def test_concurrent_same_material_returns_one_durable_receipt(tmp_path: Path) -> None:
    barrier = Barrier(2)
    wrappers: list[_BarrierWriter] = []

    def wrap(delegate: Any) -> _BarrierWriter:
        wrapper = _BarrierWriter(delegate, barrier)
        wrappers.append(wrapper)
        return wrapper

    first, reader, _ = _build_service(
        tmp_path, database_name="shared.sqlite3", writer_wrapper=wrap
    )
    second, _, _ = _build_service(
        tmp_path, database_name="shared.sqlite3", writer_wrapper=wrap
    )
    lease = _lease(_credential())
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(first.admit, "event-1", lease.lease_id, admitted_at=ADMITTED_AT),
            executor.submit(second.admit, "event-1", lease.lease_id, admitted_at=ADMITTED_AT),
        )
        receipts = tuple(future.result(timeout=10) for future in futures)

    assert receipts[0] == receipts[1]
    assert reader.by_event_id("event-1") == receipts[0]
    assert sum(wrapper.calls for wrapper in wrappers) == 2


def test_concurrent_changed_material_has_one_success_and_one_conflict(
    tmp_path: Path,
) -> None:
    barrier = Barrier(2)

    def wrap(delegate: Any) -> _BarrierWriter:
        return _BarrierWriter(delegate, barrier)

    first, reader, _ = _build_service(
        tmp_path, database_name="shared.sqlite3", writer_wrapper=wrap
    )
    credential = _credential()
    changed_event = _rebuilt_event(_event(), dedupe_key="source-1:revision-2")
    second, _, _ = _build_service(
        tmp_path,
        event=changed_event,
        origin=_origin(changed_event, credential),
        attestation=_attestation(changed_event),
        database_name="shared.sqlite3",
        writer_wrapper=wrap,
    )
    lease = _lease(credential)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(first.admit, "event-1", lease.lease_id, admitted_at=ADMITTED_AT),
            executor.submit(second.admit, "event-1", lease.lease_id, admitted_at=ADMITTED_AT),
        )
        outcomes: list[EnvironmentEventAdmissionReceipt | Exception] = []
        for future in futures:
            try:
                outcomes.append(future.result(timeout=10))
            except Exception as error:
                outcomes.append(error)

    successes = [item for item in outcomes if isinstance(item, EnvironmentEventAdmissionReceipt)]
    conflicts = [item for item in outcomes if isinstance(item, EventAdmissionPersistenceConflict)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert reader.by_event_id("event-1") == successes[0]


def test_service_api_binds_principal_and_scopes_at_construction() -> None:
    constructor = inspect.signature(EnvironmentEventAdmissionService.__init__)
    assert tuple(constructor.parameters) == (
        "self",
        "trust",
        "authority",
        "origins",
        "leases",
        "credentials",
        "attestations",
        "admission_reader",
        "admission_writer",
        "principal_id",
        "required_credential_scopes",
    )
    signature = inspect.signature(EnvironmentEventAdmissionService.admit)
    assert tuple(signature.parameters) == ("self", "event_id", "lease_id", "admitted_at")
    assert "principal_id" not in signature.parameters
    assert "required_credential_scopes" not in signature.parameters


@pytest.mark.parametrize(
    "required_scopes", [frozenset(), frozenset({""}), frozenset({"   "})]
)
def test_constructor_rejects_empty_required_credential_scopes(
    tmp_path: Path, required_scopes: frozenset[str]
) -> None:
    with pytest.raises(ValueError, match="required credential scopes"):
        _build_service(tmp_path, required_scopes=required_scopes)


@pytest.mark.parametrize(
    ("created_at", "denied"),
    [
        (ADMITTED_AT, False),
        (ADMITTED_AT + timedelta(microseconds=1), True),
    ],
)
def test_credential_creation_time_boundary_is_enforced_before_write(
    tmp_path: Path, created_at: datetime, denied: bool
) -> None:
    credential = _credential().model_copy(update={"created_at": created_at})
    event = _event()
    lease = _lease(credential)
    service, reader, writer = _build_service(
        tmp_path,
        event=event,
        credential=credential,
        lease=lease,
        origin=_origin(event, credential),
        writer_wrapper=_WriterSpy,
    )

    if denied:
        with pytest.raises(SituationalTrustDenied, match="created"):
            service.admit("event-1", lease.lease_id, admitted_at=ADMITTED_AT)
        assert writer.calls == 0
        assert reader.by_event_id("event-1") is None
    else:
        receipt = service.admit("event-1", lease.lease_id, admitted_at=ADMITTED_AT)
        assert reader.by_event_id("event-1") == receipt


def test_source_has_no_provider_assessor_task_or_effect_dependency() -> None:
    module = importlib.import_module("agent_os_core.srl_event_admission")
    tree = ast.parse(inspect.getsource(module))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    forbidden_modules = {
        "app",
        "apps",
        "application",
        "connector",
        "connectors",
        "data_agent",
        "dataagent",
        "provider",
        "relevance",
        "task_service",
        "task_aggregate",
        "execution",
        "capability",
    }
    forbidden_names = {
        "ProviderPort",
        "RelevanceAssessorPort",
        "Task",
        "TaskService",
        "CapabilityBroker",
        "ConnectorPort",
        "DataAgent",
        "Effect",
        "EffectPort",
        "AgentOSApplication",
        "RunCoordinator",
    }
    referenced_names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    } | {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }
    assert not any(
        forbidden_modules.intersection(module.split("."))
        for module in imported_modules
    )
    assert imported_names.isdisjoint(forbidden_names)
    assert referenced_names.isdisjoint(forbidden_names)


def test_positive_admission_makes_zero_provider_assessor_task_or_effect_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_os_core.capability import CapabilityBroker
    from agent_os_core.provider import ProviderPort
    from agent_os_core.situated import OperationalProposalService, RelevanceAssessorPort
    from agent_os_core.task_service import TaskService

    calls = {
        "provider_complete": 0,
        "provider_decide": 0,
        "assess": 0,
        "proposal": 0,
        "task": 0,
        "effect": 0,
    }

    def forbidden(name: str) -> Any:
        def fail(*args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            calls[name] += 1
            raise AssertionError(f"admission reached forbidden runtime entry: {name}")

        return fail

    monkeypatch.setattr(ProviderPort, "complete", forbidden("provider_complete"))
    monkeypatch.setattr(ProviderPort, "decide", forbidden("provider_decide"))
    monkeypatch.setattr(RelevanceAssessorPort, "assess", forbidden("assess"))
    monkeypatch.setattr(OperationalProposalService, "propose", forbidden("proposal"))
    monkeypatch.setattr(TaskService, "create_task", forbidden("task"))
    monkeypatch.setattr(CapabilityBroker, "invoke", forbidden("effect"))
    service, reader, _ = _build_service(tmp_path)
    lease = _lease(_credential())

    receipt = service.admit("event-1", lease.lease_id, admitted_at=ADMITTED_AT)

    assert reader.by_event_id("event-1") == receipt
    assert calls == {name: 0 for name in calls}


def test_adapter_exception_is_sanitized_and_leaves_no_durable_sentinel(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    sentinel = "ADAPTER-RAW-EXCEPTION-MUST-NOT-LEAK-0A"
    service, reader, _ = _build_service(tmp_path)

    class _ExplodingOrigin:
        def resolve_event(self, event_id: str) -> EventOriginRegistration | None:
            del event_id
            raise RuntimeError(sentinel)

    service._origins = _ExplodingOrigin()  # type: ignore[assignment,attr-defined]
    with pytest.raises(SituationalTrustDenied) as captured:
        service.admit("event-1", _lease(_credential()).lease_id, admitted_at=ADMITTED_AT)

    assert sentinel not in str(captured.value)
    assert sentinel not in caplog.text
    assert reader.by_event_id("event-1") is None
    assert sentinel.encode() not in (tmp_path / "admission.sqlite3").read_bytes()
