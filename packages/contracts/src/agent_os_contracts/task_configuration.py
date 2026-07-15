from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import Field, field_validator, model_validator

from .authority import CorrectionEpochVector
from .capability import CapabilityGrant, CapabilityGrantStatus
from .common import ContractModel, NonEmptyStr, UtcDateTime, content_digest
from .evidence import Sha256Digest
from .materialization import CandidateProvenance
from .outcome import ExpectedOutcome
from .provider import ProviderProfile
from .workflow import NodeKind, WorkflowGraph


SEAL_REQUEST_DIGEST_SCHEMA = "ADM-P4-SEAL-REQUEST-V1"
GRANT_SET_DIGEST_SCHEMA = "ADM-P4-EXECUTION-GRANTS-V1"
PRIOR_PROVENANCE_DIGEST_SCHEMA = "ADM-P4-PRIOR-PROVENANCE-V1"


class DomainPriorSelector(ContractModel):
    candidate_task_id: NonEmptyStr
    candidate_digest: Sha256Digest
    prior_artifact_id: NonEmptyStr


class PriorEvaluationSource(ContractModel):
    evaluation_task_id: NonEmptyStr
    evaluation_run_id: NonEmptyStr
    evaluation_digest: Sha256Digest
    evaluator_id: NonEmptyStr
    recorded_by: NonEmptyStr


def domain_prior_provenance_digest(
    provenance: tuple[CandidateProvenance, ...],
) -> str:
    return content_digest(
        {
            "schema": PRIOR_PROVENANCE_DIGEST_SCHEMA,
            "provenance": provenance,
        }
    )


def domain_prior_binding_digest(value: Mapping[str, Any] | DomainPriorBinding) -> str:
    return content_digest(value)


class DomainPriorBinding(ContractModel):
    prior_artifact_id: NonEmptyStr
    prior_version: int = Field(ge=1)
    prior_digest: Sha256Digest
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    candidate_id: NonEmptyStr
    candidate_task_id: NonEmptyStr
    materialization_run_id: NonEmptyStr
    candidate_digest: Sha256Digest
    candidate_payload_digest: Sha256Digest
    promotion_id: NonEmptyStr
    promotion_task_id: NonEmptyStr
    promotion_run_id: NonEmptyStr
    promotion_digest: Sha256Digest
    evaluation_head_digest: Sha256Digest
    evaluation_receipt_digests: tuple[Sha256Digest, ...] = Field(min_length=1)
    receipt_chain_digest: Sha256Digest
    evaluation_sources: tuple[PriorEvaluationSource, ...] = Field(min_length=1)
    representation_patch_digest: Sha256Digest
    provenance: tuple[CandidateProvenance, ...] = Field(min_length=1)
    provenance_digest: Sha256Digest
    policy_digest: Sha256Digest
    source_state: Literal["INERT"] = "INERT"
    source_activation_authority: Literal["NONE"] = "NONE"
    consumption_mode: Literal["REFERENCE_ONLY"] = "REFERENCE_ONLY"

    @model_validator(mode="after")
    def _validate_lineage(self) -> DomainPriorBinding:
        receipt_digests = self.evaluation_receipt_digests
        if len(receipt_digests) != len(set(receipt_digests)):
            raise ValueError("prior binding evaluation receipt digests must be unique")
        if self.evaluation_head_digest != receipt_digests[-1]:
            raise ValueError("prior binding evaluation head must equal latest receipt")
        source_digests = tuple(
            source.evaluation_digest for source in self.evaluation_sources
        )
        if source_digests != receipt_digests:
            raise ValueError("prior binding evaluation sources must match receipt chain")
        source_keys = tuple(
            (source.evaluation_task_id, source.evaluation_run_id)
            for source in self.evaluation_sources
        )
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("prior binding evaluation Task/Run sources must be unique")
        if self.provenance_digest != domain_prior_provenance_digest(self.provenance):
            raise ValueError("prior binding provenance digest mismatch")
        return self


class TaskConfigurationSnapshotCommand(ContractModel):
    prior_selector: DomainPriorSelector | None = None


def task_configuration_seal_request_digest(
    consumer_task_id: str,
    command: TaskConfigurationSnapshotCommand,
) -> str:
    return content_digest(
        {
            "schema": SEAL_REQUEST_DIGEST_SCHEMA,
            "consumer_task_id": consumer_task_id,
            "prior_selector": command.prior_selector,
        }
    )


def task_configuration_grants_digest(
    grants: tuple[CapabilityGrant, ...],
) -> str:
    ordered = tuple(
        sorted(
            grants,
            key=lambda grant: (
                grant.capability_id,
                grant.capability_version,
                grant.grant_id,
            ),
        )
    )
    return content_digest(
        {
            "schema": GRANT_SET_DIGEST_SCHEMA,
            "grants": ordered,
        }
    )


def task_configuration_snapshot_digest(payload: Mapping[str, Any]) -> str:
    if "snapshot_digest" in payload:
        raise ValueError("snapshot_digest must be excluded from its own digest payload")
    normalized = dict(payload)
    normalized.setdefault("schema_version", "1.0")
    return content_digest(normalized)


class TaskConfigurationSnapshot(ContractModel):
    snapshot_id: NonEmptyStr
    snapshot_version: Literal[1] = 1
    snapshot_digest: Sha256Digest
    seal_request_digest: Sha256Digest
    consumer_task_id: NonEmptyStr
    reserved_run_id: NonEmptyStr
    commitment_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    principal_id: NonEmptyStr
    workflow: WorkflowGraph
    workflow_digest: Sha256Digest
    policy_version: NonEmptyStr
    policy_digest: Sha256Digest
    provider_profile: ProviderProfile
    provider_profile_digest: Sha256Digest
    execution_grants: tuple[CapabilityGrant, ...] = ()
    execution_grants_digest: Sha256Digest
    expected_outcome: ExpectedOutcome
    expected_outcome_digest: Sha256Digest
    observed_correction_epochs: CorrectionEpochVector
    optional_prior: DomainPriorBinding | None = None
    sealed_by: Literal["system:task-configuration-sealer:v1"]
    sealed_at: UtcDateTime
    state: Literal["SEALED"] = "SEALED"
    prior_consumption_mode: Literal["REFERENCE_ONLY"] = "REFERENCE_ONLY"

    @field_validator("execution_grants", mode="after")
    @classmethod
    def _order_execution_grants(
        cls,
        grants: tuple[CapabilityGrant, ...],
    ) -> tuple[CapabilityGrant, ...]:
        return tuple(
            sorted(
                grants,
                key=lambda grant: (
                    grant.capability_id,
                    grant.capability_version,
                    grant.grant_id,
                ),
            )
        )

    @model_validator(mode="after")
    def _validate_bindings(self) -> TaskConfigurationSnapshot:
        if (
            self.workflow.tenant_id != self.tenant_id
            or self.workflow.workspace_id != self.workspace_id
        ):
            raise ValueError("snapshot workflow scope mismatch")
        if self.workflow_digest != self.workflow.canonical_digest():
            raise ValueError("snapshot workflow digest mismatch")
        if self.policy_version != self.workflow.policy_version:
            raise ValueError("snapshot policy version mismatch")
        if self.provider_profile_digest != content_digest(self.provider_profile):
            raise ValueError("snapshot provider profile digest mismatch")
        if self.execution_grants_digest != task_configuration_grants_digest(
            self.execution_grants
        ):
            raise ValueError("snapshot execution grants digest mismatch")

        required_capabilities = {
            node.capability
            for node in self.workflow.nodes
            if node.kind is NodeKind.TOOL and node.capability is not None
        }
        granted_capabilities = {
            grant.capability_id for grant in self.execution_grants
        }
        if required_capabilities != granted_capabilities:
            raise ValueError("snapshot execution grants do not match workflow tools")
        grant_keys = tuple(grant.capability_id for grant in self.execution_grants)
        if len(grant_keys) != len(set(grant_keys)):
            raise ValueError("snapshot execution grants contain duplicate capability")
        for grant in self.execution_grants:
            if grant.status is not CapabilityGrantStatus.ACTIVE:
                raise ValueError("snapshot execution grant must be active")
            if grant.expires_at <= self.sealed_at:
                raise ValueError("snapshot execution grant must be unexpired")
            if (
                grant.principal_id != self.principal_id
                or grant.tenant_id != self.tenant_id
                or grant.workspace_id != self.workspace_id
            ):
                raise ValueError("snapshot execution grant identity or scope mismatch")

        if (
            self.expected_outcome.task_id != self.consumer_task_id
            or self.expected_outcome.tenant_id != self.tenant_id
            or self.expected_outcome.workspace_id != self.workspace_id
        ):
            raise ValueError("snapshot expected outcome scope mismatch")
        if self.expected_outcome_digest != content_digest(self.expected_outcome):
            raise ValueError("snapshot expected outcome digest mismatch")
        if self.optional_prior is not None and (
            self.optional_prior.tenant_id != self.tenant_id
            or self.optional_prior.workspace_id != self.workspace_id
        ):
            raise ValueError("snapshot optional prior scope mismatch")
        if self.optional_prior is not None:
            source_task_ids = {
                self.optional_prior.candidate_task_id,
                self.optional_prior.promotion_task_id,
                *(
                    source.evaluation_task_id
                    for source in self.optional_prior.evaluation_sources
                ),
            }
            source_run_ids = {
                self.optional_prior.materialization_run_id,
                self.optional_prior.promotion_run_id,
                *(
                    source.evaluation_run_id
                    for source in self.optional_prior.evaluation_sources
                ),
            }
            if (
                self.consumer_task_id in source_task_ids
                or self.reserved_run_id in source_run_ids
            ):
                raise ValueError(
                    "snapshot consumer Task/Run must differ from every prior source"
                )

        selector = (
            DomainPriorSelector(
                candidate_task_id=self.optional_prior.candidate_task_id,
                candidate_digest=self.optional_prior.candidate_digest,
                prior_artifact_id=self.optional_prior.prior_artifact_id,
            )
            if self.optional_prior is not None
            else None
        )
        expected_request_digest = task_configuration_seal_request_digest(
            self.consumer_task_id,
            TaskConfigurationSnapshotCommand(prior_selector=selector),
        )
        if self.seal_request_digest != expected_request_digest:
            raise ValueError("snapshot seal request digest mismatch")

        payload = self.model_dump(mode="json", exclude={"snapshot_digest"})
        if self.snapshot_digest != task_configuration_snapshot_digest(payload):
            raise ValueError("snapshot digest mismatch")
        return self
