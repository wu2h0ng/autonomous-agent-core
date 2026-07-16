from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import NoReturn, Protocol

from agent_os_contracts import (
    CredentialLeaseRef,
    CredentialRef,
    CredentialStatus,
    EnvironmentEvent,
    EnvironmentEventAdmissionReceipt,
    EventOriginRegistration,
    PayloadAdmissionAttestation,
    canonical_json,
    content_digest,
    environment_event_admission_receipt_digest,
)
from pydantic import BaseModel

from .errors import SituationalTrustDenied
from .situated import SituationalTrustResolver
from .situated_persistence import SituatedAssessmentStore
from .srl_event_authority import (
    CredentialLeaseRegistryPort,
    CredentialRefReader,
    EventOriginRegistryPort,
    PayloadAdmissionRegistryPort,
)
from .srl_event_store import (
    EventAdmissionPersistenceConflict,
    SQLiteEventAdmissionStore,
)


class _AdmissionWriter(Protocol):
    def persist_receipt(
        self, receipt: EnvironmentEventAdmissionReceipt
    ) -> EnvironmentEventAdmissionReceipt: ...


def _deny(message: str) -> NoReturn:
    raise SituationalTrustDenied(message)


def _utc(value: datetime) -> datetime:
    try:
        if value.tzinfo is None or value.utcoffset() is None:
            _deny("admission time must be timezone-aware")
        return value.astimezone(timezone.utc)
    except (AttributeError, OverflowError, TypeError, ValueError):
        _deny("admission time cannot be normalized to UTC")


def _same_admission_material(
    durable: EnvironmentEventAdmissionReceipt,
    proposed: EnvironmentEventAdmissionReceipt,
) -> bool:
    excluded = {"receipt_id", "receipt_digest", "admitted_at"}
    return durable.model_dump(exclude=excluded) == proposed.model_dump(exclude=excluded)


def _require_canonical_contract(
    value: BaseModel,
    model_type: type[BaseModel],
) -> None:
    payload = canonical_json(value)
    try:
        decoded = model_type.model_validate_json(payload, strict=True)
    except (TypeError, ValueError):
        _deny("resolved admission authority is not canonical")
    if decoded != value or canonical_json(decoded) != payload:
        _deny("resolved admission authority is not canonical")


class EnvironmentEventAdmissionService:
    """Admit canonical environment events without granting work authority."""

    def __init__(
        self,
        *,
        trust: SituationalTrustResolver,
        authority: SituatedAssessmentStore,
        origins: EventOriginRegistryPort,
        leases: CredentialLeaseRegistryPort,
        credentials: CredentialRefReader,
        attestations: PayloadAdmissionRegistryPort,
        admission_reader: SQLiteEventAdmissionStore,
        admission_writer: _AdmissionWriter,
        principal_id: str,
        required_credential_scopes: frozenset[str],
    ) -> None:
        self._trust = trust
        self._authority = authority
        self._origins = origins
        self._leases = leases
        self._credentials = credentials
        self._attestations = attestations
        self._admission_reader = admission_reader
        self._admission_writer = admission_writer
        self._principal_id = principal_id
        self._required_credential_scopes = frozenset(required_credential_scopes)

    def admit(
        self,
        event_id: str,
        lease_id: str,
        *,
        admitted_at: datetime,
    ) -> EnvironmentEventAdmissionReceipt:
        evaluated_at = _utc(admitted_at)
        event = self._trust.resolve_event(event_id)
        origin = self._origins.resolve_event(event_id)
        lease = self._leases.resolve(lease_id)
        attestation = self._attestations.resolve_event(event_id)
        if event is None or origin is None or lease is None or attestation is None:
            _deny("canonical event admission material is unavailable")
        if event.environment_event_id != event_id or lease.lease_id != lease_id:
            _deny("resolved event or lease identity is not canonical")
        for value, model_type in (
            (event, EnvironmentEvent),
            (origin, EventOriginRegistration),
            (lease, CredentialLeaseRef),
            (attestation, PayloadAdmissionAttestation),
        ):
            _require_canonical_contract(value, model_type)
        credential = self._credentials.resolve(lease.credential_ref_id)
        if credential is None:
            _deny("current credential is unavailable")
        _require_canonical_contract(credential, CredentialRef)

        event_digest = content_digest(event)
        credential_digest = content_digest(credential)
        if origin.environment_event_id != event.environment_event_id:
            _deny("origin event identity does not match canonical event")
        if origin.event_digest != event_digest:
            _deny("origin event digest does not match canonical event")
        if origin.observation_digest != event.observation.content_digest:
            _deny("origin observation digest does not match canonical event")
        if (
            origin.credential_ref_id != credential.credential_ref_id
            or origin.credential_ref_digest != credential_digest
            or lease.credential_ref_id != credential.credential_ref_id
            or lease.credential_ref_digest != credential_digest
        ):
            _deny("current credential does not match canonical admission material")
        if credential.status is not CredentialStatus.ACTIVE:
            _deny("current credential is not active")
        if (
            origin.principal_id != self._principal_id
            or lease.principal_id != self._principal_id
            or credential.owner_principal_id != self._principal_id
        ):
            _deny("event credential principal is not authorized")
        if not self._required_credential_scopes.issubset(credential.scopes):
            _deny("current credential lacks required event scopes")
        if not (
            lease.valid_from <= evaluated_at < lease.expires_at
            and lease.expires_at <= credential.expires_at
        ):
            _deny("credential lease is not active within credential validity")
        if not (
            event.recorded_at <= evaluated_at
            and origin.registered_at <= evaluated_at
            and attestation.assessed_at <= evaluated_at
        ):
            _deny("admission material cannot postdate admission")

        scopes = (
            (event.tenant_id, event.workspace_id, event.mandate_id, event.environment_binding_id),
            (origin.tenant_id, origin.workspace_id, origin.mandate_id, origin.environment_binding_id),
            (lease.tenant_id, lease.workspace_id, lease.mandate_id, lease.environment_binding_id),
        )
        if len(set(scopes)) != 1:
            _deny("event admission scopes do not match")
        if (
            credential.tenant_id != event.tenant_id
            or credential.workspace_id != event.workspace_id
        ):
            _deny("credential scope does not match canonical event")
        if not (origin.source_id == lease.source_id == attestation.source_id):
            _deny("adapter source assertions do not match")

        mandate, binding = self._authority.resolve_active(
            event.mandate_id,
            event.environment_binding_id,
            principal_id=self._principal_id,
            tenant_id=event.tenant_id,
            workspace_id=event.workspace_id,
            evaluated_at=evaluated_at,
        )
        if (
            mandate.mandate_id != event.mandate_id
            or mandate.tenant_id != event.tenant_id
            or mandate.workspace_id != event.workspace_id
            or mandate.owner_principal_id != self._principal_id
            or binding.environment_binding_id != event.environment_binding_id
        ):
            _deny("resolved authority does not match canonical event")
        if lease.correction_epoch != mandate.correction_epoch:
            _deny("credential lease correction epoch is stale")

        if (
            attestation.environment_event_id != event.environment_event_id
            or attestation.observation_artifact_id != event.observation.artifact_id
            or attestation.observation_digest != event.observation.content_digest
            or attestation.policy_digest != origin.payload_policy_digest
            or attestation.schema_digest != origin.event_schema_digest
        ):
            _deny("payload attestation does not bind the canonical event")

        resolved_artifact = self._trust.resolve_artifact(event.observation.artifact_id)
        if resolved_artifact is None or resolved_artifact[0] != event.observation:
            _deny("exact observation artifact is unavailable")
        if "situated:read" not in resolved_artifact[0].acl_scopes:
            _deny("observation artifact lacks situated read scope")
        if hashlib.sha256(resolved_artifact[1]).hexdigest() != event.observation.content_digest:
            _deny("observation artifact bytes do not match canonical digest")

        payload = {
            "schema_version": "1.0",
            "environment_event_id": event.environment_event_id,
            "event_digest": event_digest,
            "event_origin_digest": origin.registration_digest,
            "credential_lease_digest": lease.lease_digest,
            "payload_attestation_digest": attestation.attestation_digest,
            "mandate_id": mandate.mandate_id,
            "environment_binding_id": binding.environment_binding_id,
            "environment_binding_version": binding.version,
            "environment_binding_digest": binding.binding_digest,
            "correction_epoch": mandate.correction_epoch,
            "principal_id": self._principal_id,
            "tenant_id": event.tenant_id,
            "workspace_id": event.workspace_id,
            "admitted_at": evaluated_at,
            "issued_by": "event-admission-service/v1",
            "grants_authority": False,
            "authorizes_effects": False,
        }
        digest = environment_event_admission_receipt_digest(payload)
        receipt = EnvironmentEventAdmissionReceipt(
            receipt_id=f"event-admission:{digest}",
            receipt_digest=digest,
            **payload,
        )
        existing = self._admission_reader.by_event_id(event.environment_event_id)
        if existing is not None:
            if _same_admission_material(existing, receipt):
                return existing
            raise EventAdmissionPersistenceConflict(
                "event admission material conflicts with durable receipt"
            )
        try:
            return self._admission_writer.persist_receipt(receipt)
        except EventAdmissionPersistenceConflict:
            concurrent = self._admission_reader.by_event_id(event.environment_event_id)
            if concurrent is not None and _same_admission_material(concurrent, receipt):
                return concurrent
            raise


__all__ = ["EnvironmentEventAdmissionService"]
