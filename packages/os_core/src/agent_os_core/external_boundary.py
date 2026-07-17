from __future__ import annotations

from typing import Protocol

from agent_os_contracts import (
    BoundaryDisposition,
    CredentialRef,
    ExecutionCheckpointCandidate,
    ExternalBoundaryReceipt,
    ExternalExecutionResourceRef,
    PrincipalIdentity,
    RedactedTraceExportRecord,
    SituatedEvaluationTrace,
    content_digest,
)
from pydantic import ValidationError

from .task_service import TaskService


class DurableExecutionBackend(Protocol):
    backend_id: str
    version: int

    def load_checkpoint(self, resource: ExternalExecutionResourceRef) -> object: ...


class TraceExporterBackend(Protocol):
    exporter_id: str
    version: int

    def export(self, record: RedactedTraceExportRecord) -> None: ...


def _receipt(
    *,
    boundary_kind: str,
    disposition: BoundaryDisposition,
    backend_id: str,
    backend_version: int,
    resource_id: str,
    subject_digest: str | None,
    principal_id: str,
    tenant_id: str,
    workspace_id: str,
    reason_code: str,
    redacted_fields: tuple[str, ...] = (),
    checkpoint_candidate: ExecutionCheckpointCandidate | None = None,
) -> ExternalBoundaryReceipt:
    payload = {
        "schema_version": "1.0",
        "boundary_kind": boundary_kind,
        "disposition": disposition,
        "backend_id": backend_id,
        "backend_version": backend_version,
        "resource_id": resource_id,
        "subject_digest": subject_digest,
        "principal_id": principal_id,
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "reason_code": reason_code,
        "redacted_fields": redacted_fields,
        "checkpoint_candidate": checkpoint_candidate,
        "activation_authorized": False,
        "capability_grant_authorized": False,
        "outcome_verification_authorized": False,
    }
    digest = content_digest(payload)
    return ExternalBoundaryReceipt(
        receipt_id=f"external-boundary:{digest}",
        receipt_digest=digest,
        **payload,
    )


class DurableExecutionBoundary:
    """Mirror external durability state as a non-authoritative resume candidate."""

    def __init__(self, tasks: TaskService, backend: DurableExecutionBackend) -> None:
        if not backend.backend_id.strip() or backend.version < 1:
            raise ValueError("durable execution backend identity is invalid")
        self._tasks = tasks
        self._backend = backend

    def mirror_checkpoint(
        self,
        resource: ExternalExecutionResourceRef,
        principal: PrincipalIdentity,
    ) -> ExternalBoundaryReceipt:
        denied = lambda reason: _receipt(  # noqa: E731
            boundary_kind="DURABLE_EXECUTION",
            disposition=BoundaryDisposition.DENIED,
            backend_id=self._backend.backend_id,
            backend_version=self._backend.version,
            resource_id=resource.resource_id,
            subject_digest=None,
            principal_id=principal.principal_id,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            reason_code=reason,
        )
        if (
            resource.backend_id != self._backend.backend_id
            or resource.backend_version != self._backend.version
        ):
            return denied("BACKEND_BINDING_MISMATCH")
        if (
            resource.principal_id != principal.principal_id
            or resource.tenant_id != principal.tenant_id
            or resource.workspace_id != principal.workspace_id
        ):
            return denied("RESOURCE_SCOPE_MISMATCH")
        try:
            aggregate = self._tasks.get_task(resource.task_id)
        except Exception:
            return denied("TASK_AUTHORITY_UNAVAILABLE")
        if (
            aggregate.goal is None
            or aggregate.goal.tenant_id != principal.tenant_id
            or aggregate.goal.workspace_id != principal.workspace_id
            or aggregate.goal.created_by != principal.principal_id
        ):
            return denied("TASK_SCOPE_MISMATCH")
        try:
            raw = self._backend.load_checkpoint(resource)
        except Exception:
            return denied("EXECUTION_BACKEND_UNAVAILABLE")
        try:
            candidate = ExecutionCheckpointCandidate.model_validate(raw)
        except (TypeError, ValidationError, ValueError):
            return denied("CHECKPOINT_MALFORMED")
        exact = (
            candidate.backend_id == resource.backend_id,
            candidate.backend_version == resource.backend_version,
            candidate.checkpoint_id == resource.resource_id,
            candidate.task_id == resource.task_id,
            candidate.principal_id == resource.principal_id,
            candidate.tenant_id == resource.tenant_id,
            candidate.workspace_id == resource.workspace_id,
        )
        if not all(exact):
            return denied("CHECKPOINT_SCOPE_MISMATCH")
        if aggregate.run is not None and candidate.run_id != aggregate.run.run_id:
            return denied("CHECKPOINT_RUN_MISMATCH")
        candidate_digest = content_digest(candidate)
        return _receipt(
            boundary_kind="DURABLE_EXECUTION",
            disposition=BoundaryDisposition.CANDIDATE_MIRRORED,
            backend_id=self._backend.backend_id,
            backend_version=self._backend.version,
            resource_id=resource.resource_id,
            subject_digest=candidate_digest,
            principal_id=principal.principal_id,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            reason_code="CHECKPOINT_CANDIDATE_ONLY",
            checkpoint_candidate=candidate,
        )


class TraceExportBoundary:
    """Redact a situated trace before calling an OTel-shaped exporter."""

    _SECRET_MARKERS = (
        "secret",
        "token",
        "password",
        "api_key",
        "credential",
        "cookie",
        "authorization",
    )
    _SECRET_VALUE_PREFIXES = ("bearer ", "sk-", "token=", "api_key=")

    def __init__(self, exporter: TraceExporterBackend) -> None:
        if not exporter.exporter_id.strip() or exporter.version < 1:
            raise ValueError("trace exporter identity is invalid")
        self._exporter = exporter

    def export_situated_trace(
        self,
        trace: SituatedEvaluationTrace,
        principal: PrincipalIdentity,
        *,
        resource_id: str,
        credential_ref: CredentialRef | None,
        attributes: dict[str, object],
    ) -> ExternalBoundaryReceipt:
        def denied(reason: str) -> ExternalBoundaryReceipt:
            return _receipt(
                boundary_kind="TRACE_EXPORT",
                disposition=BoundaryDisposition.DENIED,
                backend_id=self._exporter.exporter_id,
                backend_version=self._exporter.version,
                resource_id=resource_id,
                subject_digest=None,
                principal_id=principal.principal_id,
                tenant_id=principal.tenant_id,
                workspace_id=principal.workspace_id,
                reason_code=reason,
            )

        if not resource_id.strip():
            return denied("RESOURCE_ID_INVALID")
        if (
            trace.tenant_id != principal.tenant_id
            or trace.workspace_id != principal.workspace_id
        ):
            return denied("TRACE_SCOPE_MISMATCH")
        if credential_ref is not None and type(credential_ref) is not CredentialRef:
            return denied("CREDENTIAL_VALUE_FORBIDDEN")
        if credential_ref is not None and (
            credential_ref.owner_principal_id != principal.principal_id
            or credential_ref.tenant_id != principal.tenant_id
            or credential_ref.workspace_id != principal.workspace_id
        ):
            return denied("CREDENTIAL_REF_SCOPE_MISMATCH")
        sanitized: dict[str, str | int | float | bool | None] = {}
        redacted: list[str] = []
        for key in sorted(attributes):
            value = attributes[key]
            normalized = key.strip().lower()
            if not normalized:
                return denied("TRACE_ATTRIBUTE_MALFORMED")
            if isinstance(value, (bytes, bytearray, memoryview)):
                return denied("RAW_SENSITIVE_BYTES_FORBIDDEN")
            if any(marker in normalized for marker in self._SECRET_MARKERS):
                sanitized[key] = "[REDACTED]"
                redacted.append(key)
                continue
            if isinstance(value, str) and value.strip().lower().startswith(
                self._SECRET_VALUE_PREFIXES
            ):
                sanitized[key] = "[REDACTED]"
                redacted.append(key)
                continue
            if value is not None and not isinstance(
                value, (str, int, float, bool)
            ):
                return denied("TRACE_ATTRIBUTE_MALFORMED")
            sanitized[key] = value
        record_payload = {
            "schema_version": "1.0",
            "exporter_id": self._exporter.exporter_id,
            "exporter_version": self._exporter.version,
            "trace_id": trace.trace_id,
            "resource_id": resource_id,
            "principal_id": principal.principal_id,
            "tenant_id": principal.tenant_id,
            "workspace_id": principal.workspace_id,
            "trace_digest": content_digest(trace),
            "credential_ref": credential_ref,
            "attributes": sanitized,
            "redacted_fields": tuple(redacted),
        }
        record_digest = content_digest(record_payload)
        record = RedactedTraceExportRecord(
            export_record_id=f"trace-export:{record_digest}",
            **record_payload,
        )
        try:
            self._exporter.export(record)
        except Exception:
            return denied("TRACE_EXPORT_UNAVAILABLE")
        return _receipt(
            boundary_kind="TRACE_EXPORT",
            disposition=BoundaryDisposition.EXPORTED,
            backend_id=self._exporter.exporter_id,
            backend_version=self._exporter.version,
            resource_id=resource_id,
            subject_digest=content_digest(record),
            principal_id=principal.principal_id,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            reason_code="TRACE_REDACTED_AND_EXPORTED",
            redacted_fields=tuple(redacted),
        )


__all__ = [
    "DurableExecutionBackend",
    "DurableExecutionBoundary",
    "TraceExportBoundary",
    "TraceExporterBackend",
]
