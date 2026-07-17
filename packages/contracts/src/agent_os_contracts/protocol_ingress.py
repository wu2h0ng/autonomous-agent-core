from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, NonEmptyStr, content_digest
from .evidence import Sha256Digest
from .situated import HelpRequest, TaskDraftProposal


class PrincipalRef(ContractModel):
    principal_id: NonEmptyStr
    principal_kind: Literal["USER", "SERVICE", "ORGANIZATION"] = "USER"
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr

    @model_validator(mode="after")
    def validate_principal_kind(self) -> PrincipalRef:
        prefixes = {
            "USER": "user:",
            "SERVICE": "principal-service:",
            "ORGANIZATION": "organization:",
        }
        if not self.principal_id.startswith(prefixes[self.principal_kind]):
            raise ValueError("principal id is not valid for principal kind")
        return self


class ActorRef(ContractModel):
    actor_id: NonEmptyStr
    actor_kind: Literal["HUMAN", "SERVICE", "AGENT"]
    principal_ref_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_actor_kind(self) -> ActorRef:
        prefixes = {"HUMAN": "user:", "SERVICE": "service:", "AGENT": "agent:"}
        if not self.actor_id.startswith(prefixes[self.actor_kind]):
            raise ValueError("actor id is not valid for actor kind")
        return self


class WorkloadRef(ContractModel):
    workload_id: NonEmptyStr
    trust_domain: NonEmptyStr
    principal_ref_digest: Sha256Digest

    @field_validator("workload_id")
    @classmethod
    def validate_workload_id(cls, value: str) -> str:
        if not value.startswith("workload:"):
            raise ValueError("workload id must use workload namespace")
        return value


class DelegationRef(ContractModel):
    delegation_id: NonEmptyStr
    principal_ref_digest: Sha256Digest
    actor_ref_digest: Sha256Digest
    workload_ref_digest: Sha256Digest
    allowed_source_binding_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)

    @field_validator("delegation_id")
    @classmethod
    def validate_delegation_id(cls, value: str) -> str:
        if not value.startswith("delegation:"):
            raise ValueError("delegation id must use delegation namespace")
        return value


class WorkloadIdentityRegistration(ContractModel):
    """Static local binding; it is not production SPIFFE/SVID attestation."""

    registration_id: NonEmptyStr
    workload_assertion_digest: Sha256Digest
    principal: PrincipalRef
    actor: ActorRef
    workload: WorkloadRef
    delegation: DelegationRef
    source_id: NonEmptyStr
    source_binding_id: NonEmptyStr
    identity_assurance: Literal["STATIC_LOCAL_ONLY"] = "STATIC_LOCAL_ONLY"

    @model_validator(mode="after")
    def validate_reference_chain(self) -> WorkloadIdentityRegistration:
        principal_digest = content_digest(self.principal)
        if self.actor.principal_ref_digest != principal_digest:
            raise ValueError("actor principal reference mismatch")
        if self.workload.principal_ref_digest != principal_digest:
            raise ValueError("workload principal reference mismatch")
        if self.delegation.principal_ref_digest != principal_digest:
            raise ValueError("delegation principal reference mismatch")
        if self.delegation.actor_ref_digest != content_digest(self.actor):
            raise ValueError("delegation actor reference mismatch")
        if self.delegation.workload_ref_digest != content_digest(self.workload):
            raise ValueError("delegation workload reference mismatch")
        if self.source_binding_id not in self.delegation.allowed_source_binding_ids:
            raise ValueError("source binding is outside delegation")
        stable_ids = {
            self.principal.principal_id,
            self.actor.actor_id,
            self.workload.workload_id,
            self.delegation.delegation_id,
        }
        if len(stable_ids) != 4:
            raise ValueError("principal, actor, workload, and delegation ids cannot alias")
        return self


class ExternalEnvelopeAssertion(ContractModel):
    protocol: Literal["CLOUDEVENTS", "A2A", "MCP"]
    protocol_message_id: NonEmptyStr
    source_assertion: NonEmptyStr
    trace_id: NonEmptyStr
    envelope_digest: Sha256Digest


class SourceBindingAuthorizationReceipt(ContractModel):
    registration_id: NonEmptyStr
    principal: PrincipalRef
    actor_ref_digest: Sha256Digest
    workload_ref_digest: Sha256Digest
    delegation_ref_digest: Sha256Digest
    source_id: NonEmptyStr
    source_binding_id: NonEmptyStr
    envelope_digest: Sha256Digest
    binding_digest: Sha256Digest


class ProtocolIngressReceipt(ContractModel):
    receipt_id: NonEmptyStr
    receipt_digest: Sha256Digest
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    source_binding_id: NonEmptyStr
    protocol: Literal["CLOUDEVENTS", "A2A", "MCP"]
    protocol_message_id: NonEmptyStr
    binding_digest: Sha256Digest
    envelope_digest: Sha256Digest
    source_binding_authorization_digest: Sha256Digest
    admission_receipt_id: NonEmptyStr
    outcome_kind: Literal["TASK_DRAFT", "HELP_REQUEST", "NO_PROPOSAL"]
    task_draft: TaskDraftProposal | None = None
    help_request: HelpRequest | None = None
    activation_authorized: Literal[False] = False
    capability_grant_authorized: Literal[False] = False
    external_effects_authorized: Literal[False] = False

    @model_validator(mode="after")
    def validate_non_executing_outcome(self) -> ProtocolIngressReceipt:
        if (self.task_draft is not None) != (self.outcome_kind == "TASK_DRAFT"):
            raise ValueError("task draft must match outcome kind")
        if (self.help_request is not None) != (self.outcome_kind == "HELP_REQUEST"):
            raise ValueError("help request must match outcome kind")
        payload = self.model_dump(
            mode="json", exclude={"receipt_id", "receipt_digest"}
        )
        expected_digest = content_digest(payload)
        if self.receipt_digest != expected_digest:
            raise ValueError("receipt digest does not seal canonical receipt content")
        if self.receipt_id != f"protocol-ingress:{expected_digest}":
            raise ValueError("receipt id does not match sealed receipt digest")
        return self
