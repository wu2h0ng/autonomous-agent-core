from __future__ import annotations

import json
from enum import Enum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from agent_os_contracts import PrincipalIdentity
from agent_os_contracts.common import ContractModel, NonEmptyStr, canonical_json
from agent_os_contracts.evidence import Sha256Digest


class MetricContractRef(ContractModel):
    metric_id: NonEmptyStr
    metric_version: NonEmptyStr
    contract_digest: Sha256Digest


class SafeQueryRequest(ContractModel):
    query_id: NonEmptyStr
    metric: MetricContractRef
    sql: NonEmptyStr
    parameters_json: NonEmptyStr
    provider_contract_id: NonEmptyStr

    @field_validator("parameters_json", mode="after")
    @classmethod
    def _canonicalize_parameters(cls, value: str) -> str:
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("parameters_json must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("parameters_json must encode an object")
        return canonical_json(payload)


class SafeQueryResult(ContractModel):
    query_id: NonEmptyStr
    sql_fingerprint: Sha256Digest
    query_result_digest: Sha256Digest
    row_count: int = Field(ge=0)
    rows_json: NonEmptyStr


class DataSQLSafetyIssue(ContractModel):
    code: NonEmptyStr
    message: NonEmptyStr
    severity: NonEmptyStr = "error"


class DataSQLSafetyResult(ContractModel):
    allowed: bool
    reasons: tuple[str, ...]
    checked_schemas: tuple[str, ...]
    checked_tables: tuple[str, ...] = ()
    bound_parameters: tuple[str, ...] = ()
    limit_value: int | None = None
    issues: tuple[DataSQLSafetyIssue, ...] = ()


class DataProductRef(ContractModel):
    data_product_id: NonEmptyStr
    data_product_version: NonEmptyStr
    contract_digest: Sha256Digest


class DataEvidenceRef(ContractModel):
    evidence_id: NonEmptyStr
    generic_evidence_ref: NonEmptyStr
    metric_contract_digest: Sha256Digest
    query_result_digest: Sha256Digest
    provider_contract_id: NonEmptyStr
    query_id: NonEmptyStr
    sql_fingerprint: Sha256Digest
    confidence_score: float = Field(ge=0.0, le=1.0)
    confidence_flags: tuple[NonEmptyStr, ...]
    lineage_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_confidence_and_lineage(self) -> DataEvidenceRef:
        flags = set(self.confidence_flags)
        if "freshness_unknown" in flags and self.confidence_score > 0.60:
            raise ValueError("unknown freshness confidence cap exceeded")
        if "unverified_template" in flags and self.confidence_score > 0.55:
            raise ValueError("unverified template confidence cap exceeded")
        required_lineage = {
            self.generic_evidence_ref,
            self.provider_contract_id,
            self.query_id,
        }
        if not required_lineage.issubset(self.lineage_refs):
            raise ValueError("evidence lineage is incomplete")
        return self


class BusinessActionProposalRef(ContractModel):
    proposal_id: NonEmptyStr
    action_digest: Sha256Digest
    capability_id: NonEmptyStr
    approval_requirement: Literal["external_exact"] = "external_exact"
    consequence_preview: NonEmptyStr
    alternatives: tuple[NonEmptyStr, ...] = Field(min_length=1)


class BusinessActionProposalRequest(ContractModel):
    request_id: NonEmptyStr
    principal: PrincipalIdentity
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    expected_outcome_id: NonEmptyStr
    target_capability_id: NonEmptyStr
    payload_json: NonEmptyStr
    consequence_preview: NonEmptyStr
    alternatives: tuple[NonEmptyStr, ...] = Field(min_length=1)
    risk_tier: int = Field(ge=1, le=5)

    @field_validator("payload_json", mode="after")
    @classmethod
    def _canonicalize_payload(cls, value: str) -> str:
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("payload_json must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("payload_json must encode an object")
        return canonical_json(payload)

    @model_validator(mode="after")
    def _bind_principal_scope(self) -> BusinessActionProposalRequest:
        if (
            self.principal.tenant_id != self.tenant_id
            or self.principal.workspace_id != self.workspace_id
        ):
            raise ValueError("principal scope must match action proposal scope")
        if not self.target_capability_id.startswith("data.action."):
            raise ValueError("target capability must be Data Agent action-scoped")
        if self.target_capability_id == "data.action.propose":
            raise ValueError("proposal capability cannot target itself")
        return self


class DataAgentRequest(ContractModel):
    request_id: NonEmptyStr
    principal: PrincipalIdentity
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    expected_outcome_id: NonEmptyStr
    safe_query: SafeQueryRequest
    data_product: DataProductRef | None = None

    @model_validator(mode="after")
    def _bind_principal_scope(self) -> DataAgentRequest:
        if (
            self.principal.tenant_id != self.tenant_id
            or self.principal.workspace_id != self.workspace_id
        ):
            raise ValueError("principal scope must match Data Agent request scope")
        return self


class DataAgentStatus(str, Enum):
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"
    HELP_REQUIRED = "HELP_REQUIRED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"


class DataAgentResult(ContractModel):
    request_id: NonEmptyStr
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    status: DataAgentStatus
    trace_id: NonEmptyStr
    query_result: SafeQueryResult | None = None
    evidence: DataEvidenceRef | None = None
    observed_outcome_id: NonEmptyStr | None = None
    action_proposal: BusinessActionProposalRef | None = None
    failure_code: NonEmptyStr | None = None
    resend_attempts: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_status_payload(self) -> DataAgentResult:
        if self.status is DataAgentStatus.COMPLETED:
            if self.evidence is None or self.observed_outcome_id is None:
                raise ValueError(
                    "completed result requires evidence and observed outcome"
                )
            if self.failure_code is not None:
                raise ValueError("completed result cannot include a failure code")
        elif self.status is DataAgentStatus.AWAITING_APPROVAL:
            if self.action_proposal is None:
                raise ValueError("awaiting approval requires an action proposal")
        elif self.failure_code is None:
            raise ValueError("denied/help-required result requires a failure code")
        return self


__all__ = [
    "BusinessActionProposalRef",
    "BusinessActionProposalRequest",
    "DataAgentRequest",
    "DataAgentResult",
    "DataAgentStatus",
    "DataEvidenceRef",
    "DataProductRef",
    "DataSQLSafetyIssue",
    "DataSQLSafetyResult",
    "MetricContractRef",
    "SafeQueryRequest",
    "SafeQueryResult",
]
