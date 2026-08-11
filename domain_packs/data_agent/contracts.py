from __future__ import annotations

import json
from enum import Enum

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


class BusinessActionProposalRef(ContractModel):
    proposal_id: NonEmptyStr
    action_digest: Sha256Digest
    capability_id: NonEmptyStr


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
