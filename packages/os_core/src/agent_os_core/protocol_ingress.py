from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from agent_os_contracts import (
    ExternalEnvelopeAssertion,
    SourceBindingAuthorizationReceipt,
    WorkloadIdentityRegistration,
    canonical_json,
    content_digest,
)

from .errors import SituationalScopeMismatch, SituationalTrustDenied


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


__all__ = ["EventEnvelopeAdapter", "WorkloadIdentityAdapter"]
