from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, content_digest
from .evidence import Sha256Digest
from .situated import HelpRequest, TaskDraftProposal


class PrincipalRef(ContractModel):
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr


class ActorRef(ContractModel):
    actor_id: NonEmptyStr
    actor_kind: Literal["HUMAN", "SERVICE", "AGENT"]
    principal_ref_digest: Sha256Digest


class WorkloadRef(ContractModel):
    workload_id: NonEmptyStr
    trust_domain: NonEmptyStr
    principal_ref_digest: Sha256Digest


class DelegationRef(ContractModel):
    delegation_id: NonEmptyStr
    principal_ref_digest: Sha256Digest
    actor_ref_digest: Sha256Digest
    workload_ref_digest: Sha256Digest
    allowed_source_binding_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)


class WorkloadIdentityRegistration(ContractModel):
    registration_id: NonEmptyStr
    workload_assertion_digest: Sha256Digest
    principal: PrincipalRef
    actor: ActorRef
    workload: WorkloadRef
    delegation: DelegationRef
    source_id: NonEmptyStr
    source_binding_id: NonEmptyStr

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
    protocol: Literal["CLOUDEVENTS", "A2A", "MCP"]
    protocol_message_id: NonEmptyStr
    binding_digest: Sha256Digest
    envelope_digest: Sha256Digest
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
        return self
