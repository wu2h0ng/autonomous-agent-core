from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import pytest

from agent_os_contracts import (
    CredentialAuthorizationSnapshot,
    CredentialLeaseRef,
    CredentialRef,
    CredentialStatus,
    EventOriginRegistration,
    PayloadAdmissionAttestation,
    canonical_json,
    content_digest,
    credential_lease_digest,
    event_origin_registration_digest,
    payload_admission_attestation_digest,
)

from agent_os_core import (
    CanonicalCredentialLeaseRegistry,
    CanonicalCredentialAuthorizationReader,
    CredentialLeaseRegistryPort,
    CredentialAuthorizationReader,
    EventOriginRegistryPort,
    PayloadAdmissionRegistryPort,
)


NOW = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64
DIGEST_E = "e" * 64
DIGEST_F = "f" * 64


def _credential(
    *,
    credential_ref_id: str = "credential-ref-1",
    status: CredentialStatus = CredentialStatus.ACTIVE,
    scopes: tuple[str, ...] = ("source:read", "events:read", "source:read"),
    expires_at: datetime = NOW + timedelta(hours=2),
) -> CredentialRef:
    return CredentialRef(
        credential_ref_id=credential_ref_id,
        owner_principal_id="principal-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        provider_id="source-provider-1",
        resolver_key="opaque-resolver-key",
        scopes=scopes,
        status=status,
        created_at=NOW - timedelta(days=1),
        expires_at=expires_at,
    )


def _lease(
    *,
    credential: CredentialRef | None = None,
    issuer_id: str = "credential-authority/v1",
) -> CredentialLeaseRef:
    credential = credential or _credential()
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
        "issued_at": NOW,
        "valid_from": NOW + timedelta(seconds=1),
        "expires_at": NOW + timedelta(hours=1),
        "issuer_id": issuer_id,
    }
    digest = credential_lease_digest(payload)
    return CredentialLeaseRef(
        lease_id=f"credential-lease:{digest}",
        lease_digest=digest,
        **payload,
    )


def _authorization(credential: CredentialRef) -> CredentialAuthorizationSnapshot:
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


def _origin(event_id: str = "environment-event-1") -> EventOriginRegistration:
    payload = {
        "schema_version": "1.0",
        "environment_event_id": event_id,
        "source_id": "source-1",
        "source_config_digest": DIGEST_A,
        "credential_ref_id": "credential-ref-1",
        "credential_ref_digest": DIGEST_B,
        "principal_id": "principal-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "mandate_id": "mandate-1",
        "environment_binding_id": "binding-1",
        "event_digest": DIGEST_C,
        "observation_digest": DIGEST_D,
        "event_schema_digest": DIGEST_E,
        "payload_policy_digest": DIGEST_F,
        "registered_at": NOW,
    }
    digest = event_origin_registration_digest(payload)
    return EventOriginRegistration(
        registration_id=f"event-origin:{digest}",
        registration_digest=digest,
        **payload,
    )


def _attestation(
    event_id: str = "environment-event-1",
) -> PayloadAdmissionAttestation:
    payload = {
        "schema_version": "1.0",
        "environment_event_id": event_id,
        "source_id": "source-1",
        "observation_artifact_id": "artifact-1",
        "observation_digest": DIGEST_A,
        "policy_digest": DIGEST_B,
        "schema_digest": DIGEST_C,
        "issuer_id": "payload-admission-policy/v1",
        "assessed_at": NOW,
        "disposition": "ADMITTED_UNDER_POLICY",
        "credential_reflected": False,
    }
    digest = payload_admission_attestation_digest(payload)
    return PayloadAdmissionAttestation(
        attestation_id=f"payload-admission:{digest}",
        attestation_digest=digest,
        **payload,
    )


class _AdapterOriginReader:
    def __init__(self, registrations: Mapping[str, EventOriginRegistration]) -> None:
        self._registrations = dict(registrations)

    def resolve_event(self, event_id: str) -> EventOriginRegistration | None:
        return self._registrations.get(event_id)


class _AdapterAdmissionReader:
    def __init__(
        self, attestations: Mapping[str, PayloadAdmissionAttestation]
    ) -> None:
        self._attestations = dict(attestations)

    def resolve_event(self, event_id: str) -> PayloadAdmissionAttestation | None:
        return self._attestations.get(event_id)


def test_authority_ports_are_lookup_only() -> None:
    expected_methods = {
        EventOriginRegistryPort: {"resolve_event"},
        CredentialLeaseRegistryPort: {"resolve"},
        CredentialAuthorizationReader: {"resolve_authorization"},
        PayloadAdmissionRegistryPort: {"resolve_event"},
    }

    for port, expected in expected_methods.items():
        public_methods = {
            name
            for name, member in inspect.getmembers(port, inspect.isfunction)
            if not name.startswith("_")
        }
        assert public_methods == expected
        method = getattr(port, next(iter(expected)))
        assert len(inspect.signature(method).parameters) == 2


def test_origin_and_attestation_authority_comes_only_from_adapter_lookup() -> None:
    canonical_origin = _origin()
    canonical_attestation = _attestation()
    origins: EventOriginRegistryPort = _AdapterOriginReader(
        {canonical_origin.environment_event_id: canonical_origin}
    )
    attestations: PayloadAdmissionRegistryPort = _AdapterAdmissionReader(
        {canonical_attestation.environment_event_id: canonical_attestation}
    )

    assert origins.resolve_event("environment-event-1") is canonical_origin
    assert attestations.resolve_event("environment-event-1") is canonical_attestation
    assert origins.resolve_event("unknown-event") is None
    assert attestations.resolve_event("unknown-event") is None

    caller_origin = canonical_origin.model_copy()
    caller_attestation = canonical_attestation.model_copy()
    empty_origins: EventOriginRegistryPort = _AdapterOriginReader({})
    empty_attestations: PayloadAdmissionRegistryPort = _AdapterAdmissionReader({})
    assert caller_origin == canonical_origin
    assert caller_attestation == canonical_attestation
    assert empty_origins.resolve_event(caller_origin.environment_event_id) is None
    assert (
        empty_attestations.resolve_event(caller_attestation.environment_event_id) is None
    )


def test_canonical_readers_resolve_exact_stored_values_and_unknown_is_none() -> None:
    credential = _credential()
    lease = _lease(credential=credential)
    lease_reader: CredentialLeaseRegistryPort = CanonicalCredentialLeaseRegistry(
        [lease]
    )
    credential_reader: CredentialAuthorizationReader = CanonicalCredentialAuthorizationReader([credential])

    assert lease_reader.resolve(lease.lease_id) == lease
    assert credential_reader.resolve_authorization(credential.credential_ref_id) == _authorization(credential)
    assert lease_reader.resolve("unknown-lease") is None
    assert credential_reader.resolve_authorization("unknown-credential") is None


def test_credential_reader_preserves_current_digest_status_scope_owner_and_expiry() -> None:
    credential = _credential(
        status=CredentialStatus.REVOKED,
        scopes=("wrong:scope", "wrong:scope"),
        expires_at=NOW - timedelta(hours=1),
    )
    reader = CanonicalCredentialAuthorizationReader([credential])

    resolved = reader.resolve_authorization(credential.credential_ref_id)
    assert resolved is not None
    assert resolved.credential_ref_digest == content_digest(credential)
    assert resolved.status is CredentialStatus.REVOKED
    assert resolved.scopes == ("wrong:scope",)
    assert resolved.owner_principal_id == "principal-1"
    assert resolved.tenant_id == "tenant-1"
    assert resolved.workspace_id == "workspace-1"
    assert resolved.expires_at == NOW - timedelta(hours=1)


def test_constructor_inputs_are_defensively_copied() -> None:
    credential = _credential()
    lease = _lease(credential=credential)
    leases = [lease]
    credentials = {credential.credential_ref_id: credential}
    lease_reader = CanonicalCredentialLeaseRegistry(leases)
    credential_reader = CanonicalCredentialAuthorizationReader(credentials)

    leases.clear()
    credentials.clear()

    assert lease_reader.resolve(lease.lease_id) == lease
    assert credential_reader.resolve_authorization(credential.credential_ref_id) == _authorization(credential)


def test_mutating_original_objects_cannot_pollute_canonical_snapshots() -> None:
    credential = _credential(
        status=CredentialStatus.REVOKED,
        scopes=("wrong:scope",),
        expires_at=NOW - timedelta(hours=1),
    )
    lease = _lease(credential=credential)
    credential_bytes = canonical_json(_authorization(credential))
    credential_digest = content_digest(credential)
    lease_bytes = canonical_json(lease)
    lease_digest = content_digest(lease)
    credential_reader = CanonicalCredentialAuthorizationReader([credential])
    lease_reader = CanonicalCredentialLeaseRegistry([lease])

    object.__setattr__(credential, "status", CredentialStatus.ACTIVE)
    object.__setattr__(credential, "scopes", ("source:read", "events:read"))
    object.__setattr__(credential, "expires_at", NOW + timedelta(days=365))
    object.__setattr__(lease, "source_id", "attacker-source")
    object.__setattr__(lease, "issuer_id", "attacker-issuer")
    object.__setattr__(lease, "expires_at", NOW + timedelta(days=365))

    resolved_credential = credential_reader.resolve_authorization("credential-ref-1")
    resolved_lease = lease_reader.resolve(lease.lease_id)
    assert resolved_credential is not None
    assert resolved_lease is not None
    assert canonical_json(resolved_credential) == credential_bytes
    assert resolved_credential.credential_ref_digest == credential_digest
    assert resolved_credential.status is CredentialStatus.REVOKED
    assert resolved_credential.scopes == ("wrong:scope",)
    assert resolved_credential.expires_at == NOW - timedelta(hours=1)
    assert canonical_json(resolved_lease) == lease_bytes
    assert content_digest(resolved_lease) == lease_digest
    assert resolved_lease.source_id == "source-1"
    assert resolved_lease.issuer_id == "credential-authority/v1"
    assert resolved_lease.expires_at == NOW + timedelta(hours=1)


def test_mutating_resolved_objects_cannot_pollute_later_resolutions() -> None:
    credential = _credential(
        status=CredentialStatus.REVOKED,
        scopes=("wrong:scope",),
        expires_at=NOW - timedelta(hours=1),
    )
    lease = _lease(credential=credential)
    credential_bytes = canonical_json(_authorization(credential))
    lease_bytes = canonical_json(lease)
    credential_reader = CanonicalCredentialAuthorizationReader([credential])
    lease_reader = CanonicalCredentialLeaseRegistry([lease])

    first_credential = credential_reader.resolve_authorization(credential.credential_ref_id)
    first_lease = lease_reader.resolve(lease.lease_id)
    assert first_credential is not None
    assert first_lease is not None
    object.__setattr__(first_credential, "status", CredentialStatus.ACTIVE)
    object.__setattr__(
        first_credential, "scopes", ("source:read", "events:read")
    )
    object.__setattr__(
        first_credential, "expires_at", NOW + timedelta(days=365)
    )
    object.__setattr__(first_lease, "source_id", "attacker-source")
    object.__setattr__(first_lease, "issuer_id", "attacker-issuer")
    object.__setattr__(first_lease, "expires_at", NOW + timedelta(days=365))

    second_credential = credential_reader.resolve_authorization(credential.credential_ref_id)
    second_lease = lease_reader.resolve(lease.lease_id)
    assert second_credential is not None
    assert second_lease is not None
    assert second_credential is not first_credential
    assert second_lease is not first_lease
    assert canonical_json(second_credential) == credential_bytes
    assert canonical_json(second_lease) == lease_bytes
    assert second_credential.status is CredentialStatus.REVOKED
    assert second_credential.scopes == ("wrong:scope",)
    assert second_credential.expires_at == NOW - timedelta(hours=1)
    assert second_lease.source_id == "source-1"
    assert second_lease.issuer_id == "credential-authority/v1"
    assert second_lease.expires_at == NOW + timedelta(hours=1)


def test_malformed_lease_snapshot_fails_closed_at_ingestion() -> None:
    lease = _lease().model_copy(update={"issuer_id": "tampered-after-validation"})

    with pytest.raises(ValueError, match="lease_digest"):
        CanonicalCredentialLeaseRegistry([lease])


def test_non_canonical_credential_snapshot_fails_closed_at_ingestion() -> None:
    credential = _credential()
    object.__setattr__(credential, "scopes", ("z:scope", "a:scope", "z:scope"))

    with pytest.raises(ValueError, match="canonical contract snapshot"):
        CanonicalCredentialAuthorizationReader([credential])


@pytest.mark.parametrize(
    ("reader_type", "canonical", "conflicting"),
    [
        (
            CanonicalCredentialLeaseRegistry,
            _lease(),
            _lease().model_copy(update={"issuer_id": "same-id-different-content"}),
        ),
        (
            CanonicalCredentialAuthorizationReader,
            _credential(),
            _credential().model_copy(update={"provider_id": "different-provider"}),
        ),
    ],
)
def test_duplicate_canonical_id_with_different_content_fails_closed(
    reader_type: Any,
    canonical: CredentialLeaseRef | CredentialRef,
    conflicting: CredentialLeaseRef | CredentialRef,
) -> None:
    with pytest.raises(ValueError, match="duplicate canonical id"):
        reader_type([canonical, conflicting])


def test_exact_duplicates_may_deduplicate() -> None:
    credential = _credential()
    lease = _lease(credential=credential)

    assert CanonicalCredentialLeaseRegistry([lease, lease.model_copy()]).resolve(
        lease.lease_id
    ) == lease
    assert CanonicalCredentialAuthorizationReader(
        [credential, credential.model_copy()]
    ).resolve_authorization(credential.credential_ref_id) == _authorization(credential)


def test_issuer_string_equality_alone_cannot_resolve_a_lease() -> None:
    canonical = _lease(issuer_id="shared-issuer-label")
    caller_minted = _lease(issuer_id="shared-issuer-label")
    reader = CanonicalCredentialLeaseRegistry([canonical])

    assert caller_minted.issuer_id == canonical.issuer_id
    assert reader.resolve(caller_minted.issuer_id) is None
    assert reader.resolve(canonical.lease_id) == canonical


def test_public_readers_accept_no_authority_objects_or_boolean_verdicts() -> None:
    for reader_type in (
        CanonicalCredentialLeaseRegistry,
        CanonicalCredentialAuthorizationReader,
    ):
        public_methods = {
            name
            for name, member in inspect.getmembers(reader_type, inspect.isfunction)
            if not name.startswith("_")
        }
        expected_method = (
            "resolve_authorization"
            if reader_type is CanonicalCredentialAuthorizationReader
            else "resolve"
        )
        assert public_methods == {expected_method}
        resolve = getattr(reader_type, expected_method)
        parameters = inspect.signature(resolve).parameters
        assert tuple(parameters) in {("self", "lease_id"), ("self", "credential_ref_id")}
        assert not {"register", "put", "verify", "authorize", "admit"} & public_methods
