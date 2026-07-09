from __future__ import annotations

import json
from enum import Enum
from typing import Any, Mapping

from pydantic import Field, field_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime, canonical_json


class TaskStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTED = "COMMITTED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    PAUSED = "PAUSED"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RunStatus(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    WAITING_EVENT = "WAITING_EVENT"
    PAUSED = "PAUSED"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskEventType(str, Enum):
    TASK_CREATED = "TASK_CREATED"
    TASK_COMMITTED = "TASK_COMMITTED"
    RUN_STARTED = "RUN_STARTED"


class TaskEventDraft(ContractModel):
    event_id: NonEmptyStr
    task_id: NonEmptyStr
    event_type: TaskEventType
    payload_json: NonEmptyStr
    occurred_at: UtcDateTime
    correlation_id: NonEmptyStr | None = None
    causation_id: NonEmptyStr | None = None

    @field_validator("payload_json", mode="after")
    @classmethod
    def _canonicalize_payload_json(cls, value: str) -> str:
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("event payload_json must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("event payload_json must encode an object")
        return canonical_json(payload)

    @classmethod
    def build(
        cls,
        *,
        event_id: str,
        task_id: str,
        event_type: TaskEventType,
        payload: Mapping[str, Any],
        occurred_at: UtcDateTime,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> TaskEventDraft:
        return cls(
            event_id=event_id,
            task_id=task_id,
            event_type=event_type,
            payload_json=canonical_json(payload),
            occurred_at=occurred_at,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )

    def decoded_payload(self) -> dict[str, Any]:
        payload = json.loads(self.payload_json)
        if not isinstance(payload, dict):
            raise ValueError("event payload_json must encode an object")
        return payload


class TaskEvent(TaskEventDraft):
    sequence: int = Field(ge=1)


class AgentRun(ContractModel):
    run_id: NonEmptyStr
    task_id: NonEmptyStr
    commitment_id: NonEmptyStr
    workflow_id: NonEmptyStr
    workflow_version: int = Field(ge=1)
    workflow_digest: NonEmptyStr
    expected_outcome_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    status: RunStatus = RunStatus.CREATED
    created_at: UtcDateTime
