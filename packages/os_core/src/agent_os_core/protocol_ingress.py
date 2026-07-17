from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from agent_os_contracts import (
    ExternalEnvelopeAssertion,
    SourceBindingAuthorizationReceipt,
    ProtocolIngressReceipt,
    WorkloadIdentityRegistration,
    canonical_json,
    content_digest,
)

from .errors import (
    ProtocolIngressConflict,
    SituationalScopeMismatch,
    SituationalTrustDenied,
)


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class EventEnvelopeAdapter:
    """Parse transport assertions only; this adapter grants no authority."""

    @staticmethod
    def parse(raw: Mapping[str, Any]) -> ExternalEnvelopeAssertion:
        if raw.get("specversion") == "1.0":
            protocol = "CLOUDEVENTS"
            message_id = raw.get("id")
            source = raw.get("source")
            data = raw.get("data")
            trace_id = data.get("trace_id") if isinstance(data, Mapping) else None
        elif raw.get("protocol") == "A2A":
            protocol = "A2A"
            message_id = raw.get("message_id")
            source = raw.get("source")
            payload = raw.get("payload")
            trace_id = payload.get("trace_id") if isinstance(payload, Mapping) else None
        elif raw.get("protocol") == "MCP":
            protocol = "MCP"
            message_id = raw.get("request_id")
            source = raw.get("source")
            params = raw.get("params")
            trace_id = params.get("trace_id") if isinstance(params, Mapping) else None
        else:
            raise SituationalTrustDenied("unsupported external envelope")
        if not isinstance(message_id, str) or not message_id.strip():
            raise SituationalTrustDenied("external envelope assertions are incomplete")
        if not isinstance(source, str) or not source.strip():
            raise SituationalTrustDenied("external envelope assertions are incomplete")
        if not isinstance(trace_id, str) or not trace_id.strip():
            raise SituationalTrustDenied("external envelope assertions are incomplete")
        return ExternalEnvelopeAssertion(
            protocol=protocol,
            protocol_message_id=message_id,
            source_assertion=source,
            trace_id=trace_id,
            envelope_digest=_sha256(raw),
        )


class WorkloadIdentityAdapter:
    """Authenticate an internal workload registration separately from wire claims."""

    __slots__ = ("_by_assertion",)

    def __init__(self, registrations: Sequence[WorkloadIdentityRegistration]) -> None:
        by_assertion: dict[str, WorkloadIdentityRegistration] = {}
        for registration in registrations:
            if registration.workload_assertion_digest in by_assertion:
                raise ValueError("duplicate workload assertion registration")
            by_assertion[registration.workload_assertion_digest] = registration
        self._by_assertion = by_assertion

    def authenticate(
        self,
        workload_assertion: str,
        envelope: ExternalEnvelopeAssertion,
        expected_scope: tuple[str, str, str],
    ) -> SourceBindingAuthorizationReceipt:
        if not workload_assertion:
            raise SituationalTrustDenied("workload assertion is required")
        registration = self._by_assertion.get(_sha256(workload_assertion))
        if registration is None:
            raise SituationalTrustDenied("workload assertion is not authenticated")
        actual_scope = (
            registration.principal.principal_id,
            registration.principal.tenant_id,
            registration.principal.workspace_id,
        )
        if actual_scope != expected_scope:
            raise SituationalScopeMismatch("workload identity scope mismatch")
        if registration.source_id != envelope.source_assertion:
            raise SituationalTrustDenied("wire source does not match authenticated source")
        binding_digest = content_digest(
            {
                "principal_id": actual_scope[0],
                "tenant_id": actual_scope[1],
                "workspace_id": actual_scope[2],
                "source_binding_id": registration.source_binding_id,
                "protocol": envelope.protocol,
                "protocol_message_id": envelope.protocol_message_id,
                "envelope_digest": envelope.envelope_digest,
                "registration_id": registration.registration_id,
                "actor_ref_digest": content_digest(registration.actor),
                "workload_ref_digest": content_digest(registration.workload),
                "delegation_ref_digest": content_digest(registration.delegation),
            }
        )
        return SourceBindingAuthorizationReceipt(
            registration_id=registration.registration_id,
            principal=registration.principal,
            actor_ref_digest=content_digest(registration.actor),
            workload_ref_digest=content_digest(registration.workload),
            delegation_ref_digest=content_digest(registration.delegation),
            source_id=registration.source_id,
            source_binding_id=registration.source_binding_id,
            envelope_digest=envelope.envelope_digest,
            binding_digest=binding_digest,
        )


class SQLiteProtocolIngressStore:
    """Scoped replay binding in the existing situated admission database."""

    __slots__ = ("_database",)

    def __init__(self, database: str | Path) -> None:
        self._database = str(database)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS protocol_ingress_receipts (
                    principal_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    source_binding_id TEXT NOT NULL,
                    protocol TEXT NOT NULL,
                    protocol_message_id TEXT NOT NULL,
                    envelope_digest TEXT NOT NULL,
                    authorization_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    receipt_json BLOB,
                    PRIMARY KEY (
                        principal_id, tenant_id, workspace_id, source_binding_id,
                        protocol, protocol_message_id
                    )
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, timeout=10.0)
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @staticmethod
    def _key(
        authorization: SourceBindingAuthorizationReceipt,
        envelope: ExternalEnvelopeAssertion,
    ) -> tuple[str, str, str, str, str, str]:
        return (
            authorization.principal.principal_id,
            authorization.principal.tenant_id,
            authorization.principal.workspace_id,
            authorization.source_binding_id,
            envelope.protocol,
            envelope.protocol_message_id,
        )

    def replay_or_reserve(
        self,
        authorization: SourceBindingAuthorizationReceipt,
        envelope: ExternalEnvelopeAssertion,
    ) -> ProtocolIngressReceipt | None:
        key = self._key(authorization, envelope)
        authorization_digest = content_digest(authorization)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT envelope_digest, authorization_digest, status, receipt_json
                FROM protocol_ingress_receipts
                WHERE principal_id = ? AND tenant_id = ? AND workspace_id = ?
                  AND source_binding_id = ? AND protocol = ?
                  AND protocol_message_id = ?
                """,
                key,
            ).fetchone()
            if row is not None:
                if row[0] != envelope.envelope_digest or row[1] != authorization_digest:
                    raise ProtocolIngressConflict(
                        "scoped protocol message id conflicts with durable binding"
                    )
                if row[2] != "COMPLETED" or row[3] is None:
                    raise ProtocolIngressConflict(
                        "scoped protocol message is already pending"
                    )
                receipt = ProtocolIngressReceipt.model_validate_json(row[3], strict=True)
                if receipt.source_binding_authorization_digest != authorization_digest:
                    raise ProtocolIngressConflict("durable receipt auth chain mismatch")
                connection.rollback()
                return receipt
            connection.execute(
                """
                INSERT INTO protocol_ingress_receipts (
                    principal_id, tenant_id, workspace_id, source_binding_id,
                    protocol, protocol_message_id, envelope_digest,
                    authorization_digest, status, receipt_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', NULL)
                """,
                (*key, envelope.envelope_digest, authorization_digest),
            )
            connection.commit()
            return None
        except sqlite3.Error as exc:
            connection.rollback()
            raise ProtocolIngressConflict("protocol replay persistence failed") from exc
        finally:
            connection.close()

    def complete(
        self,
        authorization: SourceBindingAuthorizationReceipt,
        envelope: ExternalEnvelopeAssertion,
        receipt: ProtocolIngressReceipt,
    ) -> ProtocolIngressReceipt:
        key = self._key(authorization, envelope)
        authorization_digest = content_digest(authorization)
        if receipt.source_binding_authorization_digest != authorization_digest:
            raise ProtocolIngressConflict("receipt does not bind authenticated chain")
        payload = canonical_json(receipt).encode("utf-8")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE protocol_ingress_receipts
                SET status = 'COMPLETED', receipt_json = ?
                WHERE principal_id = ? AND tenant_id = ? AND workspace_id = ?
                  AND source_binding_id = ? AND protocol = ?
                  AND protocol_message_id = ? AND envelope_digest = ?
                  AND authorization_digest = ? AND status = 'PENDING'
                """,
                (payload, *key, envelope.envelope_digest, authorization_digest),
            )
            if cursor.rowcount != 1:
                raise ProtocolIngressConflict("protocol replay reservation changed")
        return receipt

    def abandon(
        self,
        authorization: SourceBindingAuthorizationReceipt,
        envelope: ExternalEnvelopeAssertion,
    ) -> None:
        key = self._key(authorization, envelope)
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM protocol_ingress_receipts
                WHERE principal_id = ? AND tenant_id = ? AND workspace_id = ?
                  AND source_binding_id = ? AND protocol = ?
                  AND protocol_message_id = ? AND status = 'PENDING'
                """,
                key,
            )


__all__ = [
    "EventEnvelopeAdapter",
    "SQLiteProtocolIngressStore",
    "WorkloadIdentityAdapter",
]
