from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .authority import ApprovalDisposition
from .common import ContractModel, NonEmptyStr, UtcDateTime
from .provider import ProviderMessage, SessionRef
from .runtime import TaskEvent


SURFACE_PROTOCOL_VERSION = "1.0"


class SurfaceClientRef(ContractModel):
    client_id: NonEmptyStr
    client_type: Literal["DESKTOP", "CLI", "TEST"]
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    device_id: NonEmptyStr


class SurfaceSessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PAUSED = "PAUSED"
    CORRECTION_HALTED = "CORRECTION_HALTED"
    CLOSED = "CLOSED"


class SurfaceOpenSessionCommand(ContractModel):
    protocol_version: Literal["1.0"]
    client: SurfaceClientRef
    statement: NonEmptyStr
    idempotency_key: NonEmptyStr
    requested_at: UtcDateTime


class SurfaceTurnCommand(ContractModel):
    protocol_version: Literal["1.0"]
    client: SurfaceClientRef
    session_id: NonEmptyStr
    text: NonEmptyStr
    expected_event_sequence: int = Field(ge=0)
    idempotency_key: NonEmptyStr
    requested_at: UtcDateTime


class SurfaceApprovalCommand(ContractModel):
    protocol_version: Literal["1.0"]
    client: SurfaceClientRef
    session_id: NonEmptyStr
    action_digest: NonEmptyStr
    disposition: Literal[
        ApprovalDisposition.APPROVE, ApprovalDisposition.REJECT
    ]
    reason: NonEmptyStr
    expected_event_sequence: int = Field(ge=0)
    idempotency_key: NonEmptyStr
    requested_at: UtcDateTime


class SurfaceCorrectionCommand(ContractModel):
    protocol_version: Literal["1.0"]
    client: SurfaceClientRef
    session_id: NonEmptyStr
    reason: NonEmptyStr
    expected_event_sequence: int = Field(ge=0)
    idempotency_key: NonEmptyStr
    requested_at: UtcDateTime


class PendingSurfaceApproval(ContractModel):
    action_digest: NonEmptyStr
    capability_id: NonEmptyStr
    proposal_id: NonEmptyStr
    preview: NonEmptyStr
    requested_at: UtcDateTime


class SurfaceSessionSnapshot(ContractModel):
    protocol_version: Literal["1.0"]
    session: SessionRef
    envelope_id: NonEmptyStr
    expected_outcome_id: NonEmptyStr
    status: SurfaceSessionStatus
    event_sequence: int = Field(ge=0)
    message_count: int = Field(ge=0)
    pending_approval: PendingSurfaceApproval | None = None
    updated_at: UtcDateTime


class SurfaceTurnResponse(ContractModel):
    protocol_version: Literal["1.0"]
    snapshot: SurfaceSessionSnapshot
    turn_id: NonEmptyStr | None = None
    text: NonEmptyStr
    steps: tuple[ProviderMessage, ...] = ()
    stop_reason: NonEmptyStr
    total_tokens: int = Field(ge=0)


class SurfaceEventBatch(ContractModel):
    protocol_version: Literal["1.0"]
    task_id: NonEmptyStr
    after_sequence: int = Field(ge=0)
    next_sequence: int = Field(ge=0)
    events: tuple[TaskEvent, ...]

    @model_validator(mode="after")
    def _validate_event_ownership_and_sequence(self) -> SurfaceEventBatch:
        previous_sequence = self.after_sequence
        for event in self.events:
            if event.task_id != self.task_id:
                raise ValueError("surface events must belong to the requested task")
            if event.sequence <= previous_sequence:
                raise ValueError(
                    "surface event sequences must strictly increase above after_sequence"
                )
            previous_sequence = event.sequence
        if self.next_sequence != previous_sequence:
            raise ValueError(
                "surface next_sequence must equal the last event sequence or after_sequence"
            )
        return self


class SurfaceConflictProjection(ContractModel):
    """Typed, read-only projection of a collaboration fence denial for the Surface.

    Derived from a `WorkspaceWriteDecision` so the renderer can show the
    conflicting scope, provenance and a suggested operator action without
    touching authority or fence state.
    """

    protocol_version: Literal["1.0"] = "1.0"
    action_id: NonEmptyStr
    lease_id: NonEmptyStr
    disposition: Literal["REPLAN", "CONFLICT", "CANCEL"]
    reason: NonEmptyStr
    write_scope_uris: tuple[NonEmptyStr, ...]
    relevant_event_ids: tuple[NonEmptyStr, ...] = ()
    suggested_action: Literal["REPLAN", "REVIEW_DIFF", "NONE"]

    @classmethod
    def from_decision(cls, decision) -> SurfaceConflictProjection:
        disposition = decision.disposition.value
        if disposition == "REPLAN":
            suggested_action: Literal["REPLAN", "REVIEW_DIFF", "NONE"] = "REPLAN"
        elif disposition == "CONFLICT":
            suggested_action = "REVIEW_DIFF"
        else:
            suggested_action = "NONE"
        return cls(
            action_id=decision.action_id,
            lease_id=decision.lease_id,
            disposition=disposition,
            reason=decision.reason,
            write_scope_uris=tuple(
                scope.resource_uri for scope in decision.write_scopes
            ),
            relevant_event_ids=decision.relevant_event_ids,
            suggested_action=suggested_action,
        )
