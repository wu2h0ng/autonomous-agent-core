from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime


class EnvironmentBindingMode(str, Enum):
    POLL = "POLL"
    SUBSCRIBE = "SUBSCRIBE"
    SCHEDULED = "SCHEDULED"


class EnvironmentBinding(ContractModel):
    binding_id: NonEmptyStr
    mandate_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    source_type: NonEmptyStr
    source_scope: NonEmptyStr
    mode: EnvironmentBindingMode
    cursor_type: NonEmptyStr
    freshness_seconds: int = Field(ge=1)
    read_capability_id: NonEmptyStr
    write_capability_id: NonEmptyStr | None = None  # None in V0
    wake_budget_per_window: int = Field(ge=0)
    query_budget_per_window: int = Field(ge=0)
    dedupe_key_fields: tuple[NonEmptyStr, ...] = Field(min_length=1)
    secret_policy: NonEmptyStr


class SrlEnvironmentEvent(ContractModel):
    event_id: NonEmptyStr
    binding_id: NonEmptyStr
    mandate_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    source_cursor: NonEmptyStr
    occurred_at: UtcDateTime
    received_at: UtcDateTime
    event_class: NonEmptyStr
    payload_digest: NonEmptyStr
    dedupe_key: NonEmptyStr
    provenance: tuple[NonEmptyStr, ...] = ()


class SrlRelevanceDisposition(str, Enum):
    IGNORE = "IGNORE"
    OBSERVE = "OBSERVE"
    INVESTIGATE = "INVESTIGATE"
    CREATE_TASK = "CREATE_TASK"
    HELP = "HELP"
    ABSTAIN = "ABSTAIN"


class SrlRelevanceAssessment(ContractModel):
    assessment_id: NonEmptyStr
    mandate_id: NonEmptyStr
    standing_mission_id: NonEmptyStr
    trigger_event_id: NonEmptyStr | None = None
    trigger_gap_id: NonEmptyStr | None = None
    affected_commitment_ids: tuple[NonEmptyStr, ...] = ()
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    uncertainty_summary: NonEmptyStr
    urgency: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    expected_loss_of_delay_seconds: int | None = None
    proposed_attention_budget_seconds: int = Field(ge=0)
    disposition: SrlRelevanceDisposition
    confidence: float = Field(ge=0.0, le=1.0)
    false_positive_recorded: bool = False
    assessor_version: NonEmptyStr
    assessor_policy_digest: NonEmptyStr
    provider_invocation_receipt_digest: NonEmptyStr | None = None
    proposed_goal_statement: NonEmptyStr | None = None
    minimum_external_input: NonEmptyStr | None = None
    proposed_task_class: NonEmptyStr | None = None
    assessed_at: UtcDateTime

    @model_validator(mode="after")
    def _validate_assessment(self) -> "SrlRelevanceAssessment":
        if self.trigger_event_id is None and self.trigger_gap_id is None:
            raise ValueError("assessment must be triggered by an event or a gap")

        task_dispositions = {
            SrlRelevanceDisposition.INVESTIGATE,
            SrlRelevanceDisposition.CREATE_TASK,
        }
        if self.disposition in task_dispositions:
            if self.proposed_goal_statement is None:
                raise ValueError("task disposition requires proposed_goal_statement")
            if self.minimum_external_input is not None:
                raise ValueError(
                    "minimum_external_input is only valid for HELP disposition"
                )
            if self.disposition is SrlRelevanceDisposition.CREATE_TASK:
                if self.proposed_task_class is None:
                    raise ValueError(
                        "CREATE_TASK disposition requires proposed_task_class"
                    )
            else:
                if self.proposed_task_class is not None:
                    raise ValueError(
                        "proposed_task_class is only valid for CREATE_TASK disposition"
                    )
            if not self.false_positive_recorded:
                raise ValueError(
                    "task disposition requires false_positive_recorded=True"
                )
            if not self.evidence_refs:
                raise ValueError("task disposition requires non-empty evidence_refs")
        elif self.disposition is SrlRelevanceDisposition.HELP:
            if self.minimum_external_input is None:
                raise ValueError("HELP disposition requires minimum_external_input")
            if self.proposed_goal_statement is not None:
                raise ValueError(
                    "proposed_goal_statement is not valid for HELP disposition"
                )
            if self.proposed_task_class is not None:
                raise ValueError(
                    "proposed_task_class is not valid for HELP disposition"
                )
        else:
            if self.proposed_goal_statement is not None:
                raise ValueError(
                    "proposed_goal_statement is not valid for non-work disposition"
                )
            if self.minimum_external_input is not None:
                raise ValueError(
                    "minimum_external_input is not valid for non-work disposition"
                )
            if self.proposed_task_class is not None:
                raise ValueError(
                    "proposed_task_class is not valid for non-work disposition"
                )
        return self


class SrlOperationalProjectionRef(ContractModel):
    projection_id: NonEmptyStr
    artifact_digest: NonEmptyStr
    schema_version: NonEmptyStr  # pyright: ignore[reportGeneralTypeIssues, reportIncompatibleVariableOverride]
    mandate_id: NonEmptyStr
    task_id: NonEmptyStr | None = None
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    valid_from: UtcDateTime
    valid_until: UtcDateTime | None = None
    evidence_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    uncertainty_conflict_summary: NonEmptyStr
    freshness_at: UtcDateTime
    compatibility_digest: NonEmptyStr
