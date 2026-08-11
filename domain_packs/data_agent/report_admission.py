from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from agent_os_contracts import (
    CredentialAuthorizationSnapshot,
    CredentialStatus,
    EventOriginRegistration,
    PayloadAdmissionAttestation,
    canonical_json,
    content_digest,
    event_origin_registration_digest,
    payload_admission_attestation_digest,
)
from agent_os_core import CredentialAuthorizationReader
from .report_adapter import (
    DataAgentReportAdapter,
    DataAgentReportAdapterError,
)
from .report_policy import DataAgentReportPolicyError


Clock = Callable[[], datetime]


class DataAgentReportAdmissionError(RuntimeError):
    """Fail-closed error for compiled external-report admission material."""


@dataclass(frozen=True)
class DataAgentReportAdmissionMaterial:
    origin: EventOriginRegistration
    attestation: PayloadAdmissionAttestation


class SQLiteDataAgentReportAdmissionMaterialStore:
    """A scope-bound, insert-only row for one event's exact admission material."""

    def __init__(
        self,
        database: str | Path,
        *,
        principal_id: str,
        tenant_id: str,
        workspace_id: str,
    ) -> None:
        if not all((principal_id.strip(), tenant_id.strip(), workspace_id.strip())):
            raise DataAgentReportAdmissionError("admission store scope cannot be empty")
        self._database = str(database)
        self._scope = (principal_id, tenant_id, workspace_id)
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS data_agent_report_admission_material (
                        principal_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        event_id TEXT NOT NULL,
                        origin_blob BLOB NOT NULL,
                        attestation_blob BLOB NOT NULL,
                        source_config_digest TEXT NOT NULL,
                        policy_digest TEXT NOT NULL,
                        adapter_version TEXT NOT NULL,
                        event_digest TEXT NOT NULL,
                        observation_digest TEXT NOT NULL,
                        PRIMARY KEY (principal_id, tenant_id, workspace_id, event_id)
                    )
                    """
                )
        except sqlite3.Error:
            raise DataAgentReportAdmissionError(
                "admission material store is unavailable"
            ) from None

    @property
    def principal_scope(self) -> tuple[str, str, str]:
        return self._scope

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, timeout=10)
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @staticmethod
    def _blob(value: object) -> bytes:
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise DataAgentReportAdmissionError(
                "admission material encoding is invalid"
            )
        return bytes(value)

    def _insert_or_resolve(
        self,
        material: DataAgentReportAdmissionMaterial,
        *,
        source_config_digest: str,
        policy_digest: str,
        adapter_version: str,
        event_digest: str,
        observation_digest: str,
    ) -> DataAgentReportAdmissionMaterial:
        origin_blob = canonical_json(material.origin).encode("utf-8")
        attestation_blob = canonical_json(material.attestation).encode("utf-8")
        event_id = material.origin.environment_event_id
        values = (
            *self._scope,
            event_id,
            origin_blob,
            attestation_blob,
            source_config_digest,
            policy_digest,
            adapter_version,
            event_digest,
            observation_digest,
        )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT origin_blob, attestation_blob, source_config_digest,
                           policy_digest, adapter_version, event_digest,
                           observation_digest
                    FROM data_agent_report_admission_material
                    WHERE principal_id = ? AND tenant_id = ?
                      AND workspace_id = ? AND event_id = ?
                    """,
                    (*self._scope, event_id),
                ).fetchone()
                if row is None:
                    connection.execute(
                        """
                        INSERT INTO data_agent_report_admission_material (
                            principal_id, tenant_id, workspace_id, event_id,
                            origin_blob, attestation_blob, source_config_digest,
                            policy_digest, adapter_version, event_digest,
                            observation_digest
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        values,
                    )
                    return material
                current = tuple(str(value) for value in row[2:])
                expected = (
                    source_config_digest,
                    policy_digest,
                    adapter_version,
                    event_digest,
                    observation_digest,
                )
                if current != expected:
                    raise DataAgentReportAdmissionError(
                        "stored admission material no longer matches current policy"
                    )
                origin_bytes = self._blob(row[0])
                attestation_bytes = self._blob(row[1])
                try:
                    origin = EventOriginRegistration.model_validate_json(
                        origin_bytes, strict=True
                    )
                    attestation = PayloadAdmissionAttestation.model_validate_json(
                        attestation_bytes, strict=True
                    )
                except ValueError:
                    raise DataAgentReportAdmissionError(
                        "stored admission material is corrupt"
                    ) from None
                if (
                    canonical_json(origin).encode("utf-8") != origin_bytes
                    or canonical_json(attestation).encode("utf-8") != attestation_bytes
                    or origin.model_dump(
                        mode="json",
                        exclude={
                            "registration_id",
                            "registration_digest",
                            "registered_at",
                        },
                    )
                    != material.origin.model_dump(
                        mode="json",
                        exclude={
                            "registration_id",
                            "registration_digest",
                            "registered_at",
                        },
                    )
                    or attestation.model_dump(
                        mode="json",
                        exclude={"attestation_id", "attestation_digest", "assessed_at"},
                    )
                    != material.attestation.model_dump(
                        mode="json",
                        exclude={"attestation_id", "attestation_digest", "assessed_at"},
                    )
                ):
                    raise DataAgentReportAdmissionError(
                        "stored admission material binding is invalid"
                    )
                return DataAgentReportAdmissionMaterial(origin, attestation)
        except DataAgentReportAdmissionError:
            raise
        except sqlite3.Error:
            raise DataAgentReportAdmissionError(
                "admission material transaction failed"
            ) from None


class _DataAgentReportAdmissionRegistrar:
    """Private composition object; callers may supply only an event id."""

    def __init__(
        self,
        adapter: DataAgentReportAdapter,
        store: SQLiteDataAgentReportAdmissionMaterialStore,
        authorizations: CredentialAuthorizationReader,
        *,
        clock: Clock,
    ) -> None:
        if type(adapter) is not DataAgentReportAdapter:
            raise TypeError("registrar requires the concrete Data Agent report adapter")
        if type(store) is not SQLiteDataAgentReportAdmissionMaterialStore:
            raise TypeError("registrar requires the concrete admission material store")
        if store.principal_scope != adapter.principal_scope:
            raise DataAgentReportAdmissionError(
                "admission store scope does not match adapter scope"
            )
        self._adapter = adapter
        self._store = store
        self._authorizations = authorizations
        self._clock = clock

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise DataAgentReportAdmissionError(
                "admission clock must be timezone-aware"
            )
        return value.astimezone(timezone.utc)

    @staticmethod
    def _freeze_authorization(
        value: object,
    ) -> CredentialAuthorizationSnapshot:
        if type(value) is not CredentialAuthorizationSnapshot:
            raise DataAgentReportAdmissionError(
                "credential authorization is not a canonical snapshot"
            )
        if (
            set(value.__dict__) != set(CredentialAuthorizationSnapshot.model_fields)
            or value.__pydantic_extra__
            or value.__pydantic_private__
        ):
            raise DataAgentReportAdmissionError(
                "credential authorization contains unknown state"
            )
        try:
            encoded = canonical_json(value).encode("utf-8")
            frozen = CredentialAuthorizationSnapshot.model_validate_json(
                encoded, strict=True
            )
        except (TypeError, ValueError):
            raise DataAgentReportAdmissionError(
                "credential authorization is invalid"
            ) from None
        if canonical_json(frozen).encode("utf-8") != encoded or frozen != value:
            raise DataAgentReportAdmissionError(
                "credential authorization is not canonical"
            )
        return frozen

    def prepare(self, event_id: str) -> DataAgentReportAdmissionMaterial:
        if not isinstance(event_id, str) or not event_id.strip():
            raise DataAgentReportAdmissionError("event id cannot be empty")
        event = self._adapter.resolve_event(event_id)
        if event is None:
            raise DataAgentReportAdmissionError("external report event is unavailable")
        resolved = self._adapter.resolve_artifact(event.observation.artifact_id)
        if resolved is None:
            raise DataAgentReportAdmissionError(
                "external report artifact is unavailable"
            )
        artifact, body = resolved
        if event.observation != artifact or len(event.evidence) != 1:
            raise DataAgentReportAdmissionError(
                "external report event binding is invalid"
            )
        evidence = self._adapter.resolve_evidence(event.evidence[0].evidence_id)
        if evidence is None or event.evidence[0] != evidence:
            raise DataAgentReportAdmissionError(
                "external report evidence is unavailable"
            )
        try:
            descriptor = (
                self._adapter._admission_policy_for_composition.validate_and_describe(
                    body=body,
                    artifact=artifact,
                    evidence=evidence,
                    event=event,
                )
            )
        except DataAgentReportPolicyError as exc:
            raise DataAgentReportAdmissionError(str(exc)) from None
        if (
            (descriptor.principal_id, descriptor.tenant_id, descriptor.workspace_id)
            != self._store.principal_scope
            or event.tenant_id != descriptor.tenant_id
            or event.workspace_id != descriptor.workspace_id
            or event.mandate_id != descriptor.mandate_id
            or event.environment_binding_id != descriptor.environment_binding_id
        ):
            raise DataAgentReportAdmissionError(
                "external report admission scope mismatch"
            )
        assessed_at = self._utc(self._clock())
        try:
            authorization = self._freeze_authorization(
                self._authorizations.resolve_authorization(descriptor.credential_ref_id)
            )
        except Exception:
            raise DataAgentReportAdmissionError(
                "credential authorization is unavailable"
            ) from None
        if (
            authorization.credential_ref_digest != descriptor.credential_ref_digest
            or authorization.owner_principal_id != descriptor.principal_id
            or authorization.tenant_id != descriptor.tenant_id
            or authorization.workspace_id != descriptor.workspace_id
            or authorization.provider_id != "data-agent-external-report"
            or not set(descriptor.required_credential_scopes).issubset(
                authorization.scopes
            )
            or authorization.status is not CredentialStatus.ACTIVE
            or assessed_at < authorization.created_at
            or assessed_at >= authorization.expires_at
        ):
            raise DataAgentReportAdmissionError("credential authorization is invalid")
        try:
            self._adapter._assert_current_credential_unreflected(
                body, assessed_at=assessed_at
            )
        except DataAgentReportAdapterError as exc:
            raise DataAgentReportAdmissionError(str(exc)) from None
        event_digest = content_digest(event)
        origin_payload = {
            "schema_version": "1.0",
            "environment_event_id": event.environment_event_id,
            "source_id": descriptor.source_id,
            "source_config_digest": descriptor.config_digest,
            "credential_ref_id": descriptor.credential_ref_id,
            "credential_ref_digest": descriptor.credential_ref_digest,
            "principal_id": descriptor.principal_id,
            "tenant_id": descriptor.tenant_id,
            "workspace_id": descriptor.workspace_id,
            "mandate_id": descriptor.mandate_id,
            "environment_binding_id": descriptor.environment_binding_id,
            "event_digest": event_digest,
            "observation_digest": artifact.content_digest,
            "event_schema_digest": descriptor.event_schema_digest,
            "payload_policy_digest": descriptor.policy_digest,
            "registered_at": assessed_at,
        }
        origin_digest = event_origin_registration_digest(origin_payload)
        origin = EventOriginRegistration(
            registration_id=f"event-origin:{origin_digest}",
            registration_digest=origin_digest,
            **origin_payload,
        )
        attestation_payload = {
            "schema_version": "1.0",
            "environment_event_id": event.environment_event_id,
            "source_id": descriptor.source_id,
            "observation_artifact_id": artifact.artifact_id,
            "observation_digest": artifact.content_digest,
            "policy_digest": descriptor.policy_digest,
            "schema_digest": descriptor.event_schema_digest,
            "issuer_id": descriptor.policy_version,
            "assessed_at": assessed_at,
            "disposition": "ADMITTED_UNDER_POLICY",
            "credential_reflected": False,
        }
        attestation_digest = payload_admission_attestation_digest(attestation_payload)
        attestation = PayloadAdmissionAttestation(
            attestation_id=f"payload-admission:{attestation_digest}",
            attestation_digest=attestation_digest,
            **attestation_payload,
        )
        return self._store._insert_or_resolve(
            DataAgentReportAdmissionMaterial(origin, attestation),
            source_config_digest=descriptor.config_digest,
            policy_digest=descriptor.policy_digest,
            adapter_version=descriptor.adapter_version,
            event_digest=event_digest,
            observation_digest=artifact.content_digest,
        )


__all__ = [
    "DataAgentReportAdmissionError",
    "DataAgentReportAdmissionMaterial",
    "SQLiteDataAgentReportAdmissionMaterialStore",
]
