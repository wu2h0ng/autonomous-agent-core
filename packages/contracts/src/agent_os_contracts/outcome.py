from __future__ import annotations

import math
from enum import Enum

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime


class OutcomeStatus(str, Enum):
    VERIFIED = "VERIFIED"
    NOT_MET = "NOT_MET"
    UNRESOLVED = "UNRESOLVED"
    INVALID = "INVALID"


class ExpectedOutcome(ContractModel):
    expected_outcome_id: NonEmptyStr
    task_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    evaluator_type: NonEmptyStr
    evaluator_version: NonEmptyStr
    evidence_requirements: tuple[NonEmptyStr, ...] = Field(min_length=1)
    failure_semantics: tuple[NonEmptyStr, ...] = Field(min_length=1)
    threshold: float
    observation_window_seconds: int = Field(ge=1)
    frozen_at: UtcDateTime

    @field_validator("threshold", mode="after")
    @classmethod
    def _require_finite_threshold(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("threshold must be finite")
        return value


class ObservedOutcome(ContractModel):
    observed_outcome_id: NonEmptyStr
    expected_outcome_id: NonEmptyStr
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    evaluator_type: NonEmptyStr
    evaluator_version: NonEmptyStr
    status: OutcomeStatus
    score: float | None = None
    confidence: float = Field(ge=0, le=1)
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    unresolved_gaps: tuple[NonEmptyStr, ...] = ()
    observed_at: UtcDateTime

    @model_validator(mode="after")
    def _require_verified_evidence(self) -> ObservedOutcome:
        if self.status is OutcomeStatus.VERIFIED and (
            self.score is None or not self.evidence_refs
        ):
            raise ValueError("verified outcome requires score and evidence")
        if self.status is OutcomeStatus.UNRESOLVED and not self.unresolved_gaps:
            raise ValueError("unresolved outcome requires at least one unresolved gap")
        return self
