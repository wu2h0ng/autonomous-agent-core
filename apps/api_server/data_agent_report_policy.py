from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from agent_os_contracts import (
    ArtifactLocationClass,
    ArtifactRef,
    CredentialRef,
    EnvironmentEvent,
    EvidenceRef,
    EvidenceSourceKind,
    OperationalProjectionRef,
    ProjectionEpistemicStatus,
    canonical_json,
    content_digest,
)


ADAPTER_VERSION = "data-agent-external-report-adapter:v1"
POLICY_VERSION = "data-agent-external-report-envelope-policy:v1"
PROJECTION_SCHEMA = "schema://operational-projection/data-agent-report-metadata/v1"
SOURCE_ENVELOPE_CONTRACT = "data-agent.external-report.security-envelope.v1"
CREDENTIAL_PROVIDER = "data-agent-external-report"


class DataAgentReportPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class DataAgentReportPolicyConfig:
    source_id: str
    normalized_origin: str
    source_tenant_id: str
    credential: CredentialRef
    principal_id: str
    target_tenant_id: str
    target_workspace_id: str
    mandate_id: str
    environment_binding_id: str
    scope_ref: str
    allow_loopback_http: bool
    timeout_seconds: int
    max_response_bytes: int
    freshness_seconds: int

    def canonical_payload(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "normalized_origin": self.normalized_origin,
            "source_tenant_id": self.source_tenant_id,
            "credential_ref_digest": content_digest(self.credential),
            "principal_id": self.principal_id,
            "target_tenant_id": self.target_tenant_id,
            "target_workspace_id": self.target_workspace_id,
            "mandate_id": self.mandate_id,
            "environment_binding_id": self.environment_binding_id,
            "scope_ref": self.scope_ref,
            "allow_loopback_http": self.allow_loopback_http,
            "timeout_seconds": self.timeout_seconds,
            "max_response_bytes": self.max_response_bytes,
            "freshness_seconds": self.freshness_seconds,
        }


@dataclass(frozen=True)
class DataAgentReportPolicyDescriptor:
    adapter_version: str
    policy_version: str
    config_digest: str
    policy_digest: str
    event_schema_digest: str
    credential_ref_id: str
    credential_ref_digest: str
    required_credential_scopes: tuple[str, ...]
    source_id: str
    principal_id: str
    tenant_id: str
    workspace_id: str
    mandate_id: str
    environment_binding_id: str


@dataclass(frozen=True)
class DataAgentReportEnvelope:
    artifact: ArtifactRef
    evidence: EvidenceRef
    event: EnvironmentEvent
    projection: OperationalProjectionRef


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise DataAgentReportPolicyError(f"external report {name} is invalid")
    return value


def _strict_object(body: bytes) -> dict[str, object]:
    def reject_constant(value: str) -> None:
        raise DataAgentReportPolicyError(
            f"external report contains unsupported numeric value: {value}"
        )

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DataAgentReportPolicyError("external report has duplicate fields")
            result[key] = value
        return result

    try:
        parsed = json.loads(
            body.decode("utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=unique_pairs,
        )
    except DataAgentReportPolicyError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise DataAgentReportPolicyError("external report is not valid JSON") from None
    return _object(parsed, "payload")


class DataAgentReportEnvelopePolicy:
    """One executable envelope policy shared by ingress and later admission."""

    def __init__(self, config: DataAgentReportPolicyConfig) -> None:
        self._config = config
        self._descriptor = self._build_descriptor()

    def _build_descriptor(self) -> DataAgentReportPolicyDescriptor:
        config = self._config
        required_scopes = tuple(
            sorted(
                {
                    "reports:read",
                    f"data-agent-origin:{config.normalized_origin}",
                    f"data-agent-tenant:{config.source_tenant_id}",
                }
            )
        )
        config_digest = content_digest(config.canonical_payload())
        event_schema_digest = content_digest(
            {
                "contract": "EnvironmentEvent",
                "event_type_ref": "data-agent.external-report-observed.v1",
                "observation": "exact ArtifactRef",
                "evidence": "exact external EvidenceRef singleton",
                "time": "occurred_at == recorded_at == artifact.created_at",
            }
        )
        policy_digest = content_digest(
            {
                "adapter_version": ADAPTER_VERSION,
                "policy_version": POLICY_VERSION,
                "projection_schema": PROJECTION_SCHEMA,
                "source_envelope_contract": SOURCE_ENVELOPE_CONTRACT,
                "config_digest": config_digest,
                "max_response_bytes": config.max_response_bytes,
                "artifact_media_type": "application/json",
                "artifact_location_class": ArtifactLocationClass.OBJECT_STORE,
                "artifact_acl_scopes": ("situated:read",),
                "event_schema_digest": event_schema_digest,
                "required_credential_scopes": required_scopes,
            }
        )
        return DataAgentReportPolicyDescriptor(
            adapter_version=ADAPTER_VERSION,
            policy_version=POLICY_VERSION,
            config_digest=config_digest,
            policy_digest=policy_digest,
            event_schema_digest=event_schema_digest,
            credential_ref_id=config.credential.credential_ref_id,
            credential_ref_digest=content_digest(config.credential),
            required_credential_scopes=required_scopes,
            source_id=config.source_id,
            principal_id=config.principal_id,
            tenant_id=config.target_tenant_id,
            workspace_id=config.target_workspace_id,
            mandate_id=config.mandate_id,
            environment_binding_id=config.environment_binding_id,
        )

    @property
    def descriptor(self) -> DataAgentReportPolicyDescriptor:
        return self._descriptor

    def validate_body(self, body: bytes, trace_id: str) -> dict[str, object]:
        if len(body) > self._config.max_response_bytes:
            raise DataAgentReportPolicyError(
                "external report response exceeds configured size limit"
            )
        payload = _strict_object(body)
        if payload.get("trace_id") != trace_id:
            raise DataAgentReportPolicyError("external report trace binding mismatch")
        if payload.get("audience") != "external":
            raise DataAgentReportPolicyError("external report audience is not external")
        result = _object(payload.get("user_result"), "user_result")
        if result.get("trace_id") != trace_id:
            raise DataAgentReportPolicyError("external result trace binding mismatch")
        if result.get("audience") != "external":
            raise DataAgentReportPolicyError("external result audience is not external")
        redaction = _object(result.get("redaction"), "redaction")
        if (
            redaction.get("audience") != "external"
            or redaction.get("applied") is not True
        ):
            raise DataAgentReportPolicyError(
                "external result does not carry an applied external redaction"
            )
        business_action = _object(result.get("business_action"), "business_action")
        if business_action.get("trace_id") != trace_id:
            raise DataAgentReportPolicyError(
                "external business action trace binding mismatch"
            )
        return payload

    def stable_identity(self, trace_id: str, raw_digest: str) -> dict[str, object]:
        config = self._config
        return {
            "adapter_version": ADAPTER_VERSION,
            "source_id": config.source_id,
            "source_tenant_id": config.source_tenant_id,
            "trace_id": trace_id,
            "raw_digest": raw_digest,
            "principal_id": config.principal_id,
            "target_tenant_id": config.target_tenant_id,
            "target_workspace_id": config.target_workspace_id,
            "mandate_id": config.mandate_id,
            "environment_binding_id": config.environment_binding_id,
            "scope_ref": config.scope_ref,
        }

    def build(
        self,
        trace_id: str,
        body: bytes,
        observed_at: datetime,
    ) -> DataAgentReportEnvelope:
        self.validate_body(body, trace_id)
        raw_digest = hashlib.sha256(body).hexdigest()
        stable_identity = self.stable_identity(trace_id, raw_digest)
        dedupe_digest = content_digest(stable_identity)
        record_identity = {**stable_identity, "observed_at": observed_at.isoformat()}
        identity_digest = content_digest(record_identity)
        artifact_id = f"artifact:data-agent-report:{identity_digest}"
        evidence_id = f"evidence:data-agent-report:{identity_digest}"
        event_id = f"event:data-agent-report:{identity_digest}"
        projection_payload = {
            "kind": "data-agent-external-report-metadata-projection",
            "version": 1,
            "source_identity": stable_identity,
            "source_artifact_id": artifact_id,
            "source_content_digest": raw_digest,
            "authority": "none",
        }
        projection_bytes = canonical_json(projection_payload).encode("utf-8")
        projection_digest = hashlib.sha256(projection_bytes).hexdigest()
        projection_identity = content_digest(
            {
                **record_identity,
                "projection_digest": projection_digest,
                "schema": PROJECTION_SCHEMA,
            }
        )
        projection_artifact_id = f"artifact:data-agent-projection:{projection_identity}"
        config = self._config
        artifact = ArtifactRef(
            artifact_id=artifact_id,
            tenant_id=config.target_tenant_id,
            workspace_id=config.target_workspace_id,
            content_digest=raw_digest,
            media_type="application/json",
            location_class=ArtifactLocationClass.OBJECT_STORE,
            location_ref=(
                f"data-agent-report://{config.source_id}/{trace_id}/{raw_digest}"
            ),
            acl_scopes=("situated:read",),
            retention_policy="retain-source-observation",
            created_by=ADAPTER_VERSION,
            created_at=observed_at,
        )
        evidence = EvidenceRef(
            evidence_id=evidence_id,
            tenant_id=config.target_tenant_id,
            workspace_id=config.target_workspace_id,
            source_kind=EvidenceSourceKind.EXTERNAL_OBSERVATION,
            source_ref=f"{config.source_id}:{config.source_tenant_id}:{trace_id}",
            relation="observed-exact-external-report-bytes",
            artifact_ids=(artifact_id,),
            created_by=ADAPTER_VERSION,
            created_at=observed_at,
        )
        event = EnvironmentEvent(
            environment_event_id=event_id,
            environment_binding_id=config.environment_binding_id,
            mandate_id=config.mandate_id,
            tenant_id=config.target_tenant_id,
            workspace_id=config.target_workspace_id,
            event_type_ref="data-agent.external-report-observed.v1",
            dedupe_key=f"data-agent-report:{dedupe_digest}",
            observation=artifact,
            evidence=(evidence,),
            occurred_at=observed_at,
            recorded_at=observed_at,
        )
        projection_artifact = ArtifactRef(
            artifact_id=projection_artifact_id,
            tenant_id=config.target_tenant_id,
            workspace_id=config.target_workspace_id,
            content_digest=projection_digest,
            media_type="application/json",
            location_class=ArtifactLocationClass.OBJECT_STORE,
            location_ref=f"data-agent-projection://{projection_identity}",
            acl_scopes=("situated:read",),
            retention_policy="retain-derived-projection",
            created_by=ADAPTER_VERSION,
            created_at=observed_at,
        )
        projection_evidence = EvidenceRef(
            evidence_id=f"evidence:data-agent-projection:{projection_identity}",
            tenant_id=config.target_tenant_id,
            workspace_id=config.target_workspace_id,
            source_kind=EvidenceSourceKind.ARTIFACT,
            source_ref=artifact_id,
            relation="projects-source-observation-metadata-without-authority",
            artifact_ids=(projection_artifact_id, artifact_id),
            created_by=ADAPTER_VERSION,
            created_at=observed_at,
        )
        projection = OperationalProjectionRef(
            projection_id=f"projection:data-agent-report:{projection_identity}",
            environment_binding_id=config.environment_binding_id,
            mandate_id=config.mandate_id,
            tenant_id=config.target_tenant_id,
            workspace_id=config.target_workspace_id,
            source_event_ids=(event_id,),
            projection_artifact=projection_artifact,
            schema_uri=PROJECTION_SCHEMA,
            version=1,
            scope_ref=config.scope_ref,
            valid_from=observed_at,
            recorded_at=observed_at,
            fresh_until=observed_at + timedelta(seconds=config.freshness_seconds),
            evidence=(evidence, projection_evidence),
            epistemic_status=ProjectionEpistemicStatus.UNKNOWN,
            uncertainty_summary=(
                "Source bytes and external redaction are verified; domain significance "
                "and upstream snapshot immutability are not."
            ),
            conflict_refs=(),
            compatibility_digest=content_digest(
                {
                    "adapter_version": ADAPTER_VERSION,
                    "schema": PROJECTION_SCHEMA,
                    "source_envelope_contract": SOURCE_ENVELOPE_CONTRACT,
                }
            ),
        )
        return DataAgentReportEnvelope(artifact, evidence, event, projection)

    def validate(
        self,
        *,
        body: bytes,
        artifact: ArtifactRef,
        evidence: EvidenceRef,
        event: EnvironmentEvent,
        projection: OperationalProjectionRef | None = None,
    ) -> None:
        # The event id is content-addressed, not the source trace. Recover it from the
        # exact location that this policy itself created.
        prefix = f"data-agent-report://{self._config.source_id}/"
        if not artifact.location_ref.startswith(prefix):
            raise DataAgentReportPolicyError(
                "external report artifact origin is invalid"
            )
        remainder = artifact.location_ref.removeprefix(prefix)
        try:
            trace_id, raw_digest = remainder.rsplit("/", 1)
        except ValueError:
            raise DataAgentReportPolicyError(
                "external report artifact location is invalid"
            ) from None
        if raw_digest != hashlib.sha256(body).hexdigest():
            raise DataAgentReportPolicyError(
                "external report artifact digest is invalid"
            )
        expected = self.build(trace_id, body, event.recorded_at)
        actual = (artifact, evidence, event)
        expected_values = (expected.artifact, expected.evidence, expected.event)
        if actual != expected_values or (
            projection is not None and projection != expected.projection
        ):
            raise DataAgentReportPolicyError(
                "external report envelope binding is invalid"
            )

    def validate_and_describe(
        self,
        *,
        body: bytes,
        artifact: ArtifactRef,
        evidence: EvidenceRef,
        event: EnvironmentEvent,
        projection: OperationalProjectionRef | None = None,
    ) -> DataAgentReportPolicyDescriptor:
        current = self._build_descriptor()
        if current != self._descriptor:
            raise DataAgentReportPolicyError(
                "external report policy descriptor is inconsistent"
            )
        self.validate(
            body=body,
            artifact=artifact,
            evidence=evidence,
            event=event,
            projection=projection,
        )
        return current


__all__ = [
    "ADAPTER_VERSION",
    "CREDENTIAL_PROVIDER",
    "DataAgentReportEnvelope",
    "DataAgentReportEnvelopePolicy",
    "DataAgentReportPolicyConfig",
    "DataAgentReportPolicyDescriptor",
    "DataAgentReportPolicyError",
    "POLICY_VERSION",
    "PROJECTION_SCHEMA",
    "SOURCE_ENVELOPE_CONTRACT",
]
