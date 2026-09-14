from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field, model_validator

from .authority import ApprovalDisposition
from .common import ContractModel, NonEmptyStr, UtcDateTime
from .provider import ProviderMessage, SessionRef
from .runtime import TaskEvent


SURFACE_PROTOCOL_VERSION = "1.1"  # E3: usage v2 cost-honesty contract on the wire


PermissionMode = Literal["ASK", "ACCEPT_READ_ONLY", "ACCEPT_IN_WORKSPACE"]
"""E2 operator-issued session permission mode (frozen matrix, GC §E2).

ASK is the default interactive mode; ACCEPT_READ_ONLY auto-passes only the
pre-existing tier-default read surface; ACCEPT_IN_WORKSPACE additionally
policy auto-allows tier-2 in-sandbox edits with the durable provenance chain.
Tier-3+ always requires a real human ApprovalDecision; out-of-allowlist
actions are never executable in any mode.
"""


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
    protocol_version: Literal["1.1"]
    client: SurfaceClientRef
    statement: NonEmptyStr
    idempotency_key: NonEmptyStr
    requested_at: UtcDateTime


class SurfaceTurnCommand(ContractModel):
    protocol_version: Literal["1.1"]
    client: SurfaceClientRef
    session_id: NonEmptyStr
    text: NonEmptyStr
    expected_event_sequence: int = Field(ge=0)
    idempotency_key: NonEmptyStr
    requested_at: UtcDateTime


class SurfaceApprovalCommand(ContractModel):
    protocol_version: Literal["1.1"]
    client: SurfaceClientRef
    session_id: NonEmptyStr
    action_digest: NonEmptyStr
    disposition: Literal[ApprovalDisposition.APPROVE, ApprovalDisposition.REJECT]
    reason: NonEmptyStr
    expected_event_sequence: int = Field(ge=0)
    idempotency_key: NonEmptyStr
    requested_at: UtcDateTime


class SurfaceCorrectionCommand(ContractModel):
    protocol_version: Literal["1.1"]
    client: SurfaceClientRef
    session_id: NonEmptyStr
    reason: NonEmptyStr
    expected_event_sequence: int = Field(ge=0)
    idempotency_key: NonEmptyStr
    requested_at: UtcDateTime


class SurfaceSetPermissionModeCommand(ContractModel):
    """E2 operator-issued permission mode change (frozen).

    Runtime enforces operator-only issuance (principal scope + principal role);
    the model can never set a mode. Each change is recorded once as a durable
    `SESSION_PERMISSION_MODE_SET` event carrying who set it and the prior
    event's digest (provenance chain).
    """

    protocol_version: Literal["1.1"]
    client: SurfaceClientRef
    session_id: NonEmptyStr
    mode: PermissionMode
    expected_event_sequence: int = Field(ge=0)
    idempotency_key: NonEmptyStr
    requested_at: UtcDateTime


class SurfaceProviderStatus(ContractModel):
    """Redacted live provider configuration for the terminal.

    Never carries the credential value: only the non-secret profile metadata and
    the opaque ``credential_ref_id``.
    """

    protocol_version: Literal["1.1"] = "1.1"  # pyright: ignore[reportIncompatibleVariableOverride]
    configured: bool
    provider_id: NonEmptyStr | None = None
    model_id: NonEmptyStr | None = None
    endpoint_class: NonEmptyStr | None = None
    credential_ref_id: NonEmptyStr | None = None
    base_url: NonEmptyStr | None = None


class SurfaceProviderConfigureCommand(ContractModel):
    """Operator-issued provider configuration over the surface protocol.

    ``api_key`` is a transient credential: the runtime keeps it in an
    environment-backed in-memory resolver for the process lifetime and never
    persists it to the database, state files, artifacts or logs.
    """

    protocol_version: Literal["1.1"]
    client: SurfaceClientRef
    base_url: NonEmptyStr
    model: NonEmptyStr
    api_key: NonEmptyStr
    endpoint_class: NonEmptyStr = "openai-compatible"
    temperature: float | None = None


class PendingSurfaceApproval(ContractModel):
    action_digest: NonEmptyStr
    capability_id: NonEmptyStr
    proposal_id: NonEmptyStr
    preview: NonEmptyStr
    requested_at: UtcDateTime


class SurfaceSessionSnapshot(ContractModel):
    protocol_version: Literal["1.1"]
    session: SessionRef
    envelope_id: NonEmptyStr
    expected_outcome_id: NonEmptyStr
    status: SurfaceSessionStatus
    event_sequence: int = Field(ge=0)
    message_count: int = Field(ge=0)
    pending_approval: PendingSurfaceApproval | None = None
    permission_mode: PermissionMode = "ASK"
    updated_at: UtcDateTime


class SurfaceSessionSummary(ContractModel):
    """Read-only, minimal session projection for `/resume` listing.

    Deliberately excludes statement, envelope id, expected outcome, tokens and
    credentials: the list endpoint must never leak session content or secrets.
    """

    session_id: NonEmptyStr
    task_id: NonEmptyStr
    status: SurfaceSessionStatus
    permission_mode: PermissionMode = "ASK"
    message_count: int = Field(ge=0)
    updated_at: UtcDateTime


class SurfaceSessionListResponse(ContractModel):
    protocol_version: Literal["1.1"]
    sessions: tuple[SurfaceSessionSummary, ...] = ()
    next_cursor: NonEmptyStr | None = None


class SurfaceTurnResponse(ContractModel):
    protocol_version: Literal["1.1"]
    snapshot: SurfaceSessionSnapshot
    turn_id: NonEmptyStr | None = None
    text: NonEmptyStr
    steps: tuple[ProviderMessage, ...] = ()
    stop_reason: NonEmptyStr
    total_tokens: int = Field(ge=0)


class SurfaceEventBatch(ContractModel):
    protocol_version: Literal["1.1"]
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

    protocol_version: Literal["1.1"] = "1.1"
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
        if disposition not in {"REPLAN", "CONFLICT", "CANCEL"}:
            raise ValueError(
                "SurfaceConflictProjection is denial-only; "
                f"cannot project disposition {disposition!r}"
            )
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


class SurfaceStreamBinding(ContractModel):
    """Pre-subscribed stream identity a begin-turn command binds to.

    `runtime_boot_id` identifies the daemon process generation; it changes on
    every restart so a dead generation's streams can never collide with the new
    one.
    """

    runtime_boot_id: NonEmptyStr
    stream_id: NonEmptyStr


class SurfaceBeginTurnCommand(ContractModel):
    """E1 reserve/begin-turn: the single turn_id source (M2, frozen).

    Order of operations (frozen): the client subscribes to the session stream
    first, then issues this command carrying the pre-subscribed
    `{runtime_boot_id, stream_id}`. The server validates the stream is live,
    atomically binds the turn, durably records turn-start, and returns the
    authoritative `{turn_id, stream_id}`. The client never mints turn ids.
    """

    protocol_version: Literal["1.1"]
    client: SurfaceClientRef
    session_id: NonEmptyStr
    text: NonEmptyStr
    stream: SurfaceStreamBinding
    expected_event_sequence: int = Field(ge=0)
    idempotency_key: NonEmptyStr
    requested_at: UtcDateTime


class SurfaceBeginTurnResponse(ContractModel):
    """Authoritative begin-turn result; idempotent replays return this
    recorded response without re-invoking the provider."""

    protocol_version: Literal["1.1"] = "1.1"
    turn_id: NonEmptyStr
    stream_id: NonEmptyStr


class SurfaceStreamFrameKind(str, Enum):
    CHUNK = "CHUNK"
    GAP = "GAP"
    STREAM_END = "STREAM_END"
    # Transient provider reasoning: display-only, turn-bound, never durable
    # (same lifecycle class as CHUNK). See ADR REASONING-TRANSIENT-FRAME.
    REASONING = "REASONING"


class SurfaceStreamFrame(ContractModel):
    """Transient display frame; never a durable Task event (frozen).

    Every frame binds (runtime_boot_id, stream_id, turn_id, frame_sequence).
    Gap frames are priority control frames synthesized on the read path: they
    are never turn-bound, carry gap_from/gap_to, and are never buffer residents
    so they cannot be evicted by overflow.
    """

    kind: SurfaceStreamFrameKind
    runtime_boot_id: NonEmptyStr
    stream_id: NonEmptyStr
    turn_id: NonEmptyStr | None = None
    frame_sequence: int = Field(ge=0)
    gap_from: int | None = Field(default=None, ge=0)
    gap_to: int | None = Field(default=None, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_kind_invariants(self) -> SurfaceStreamFrame:
        if self.kind is SurfaceStreamFrameKind.GAP:
            if self.turn_id is not None:
                raise ValueError("gap frames are control frames, never turn-bound")
            if self.gap_from is None or self.gap_to is None:
                raise ValueError("gap frames require gap_from/gap_to")
            if self.gap_to < self.gap_from:
                raise ValueError("gap_to must be >= gap_from")
        else:
            if self.turn_id is None:
                raise ValueError(f"{self.kind.value} frames require turn binding")
            if self.gap_from is not None or self.gap_to is not None:
                raise ValueError("gap range is only valid on gap frames")
        return self


class SurfaceStreamSubscription(ContractModel):
    """Subscription-first identity for the transient stream channel (E1).

    The client subscribes before executing any turn and binds the returned
    {runtime_boot_id, stream_id} into every begin-turn. `runtime_boot_id`
    identifies the daemon process generation; a stale generation fails typed
    `SurfaceStreamGone` and can never collide with the new one.
    """

    protocol_version: Literal["1.1"] = "1.1"
    runtime_boot_id: NonEmptyStr
    stream_id: NonEmptyStr


class SurfaceStreamBatch(ContractModel):
    """Bounded transient frame batch for the stream SSE endpoint (E1).

    Cursors are per-stream frame sequences (never durable Task event
    sequences). `next_sequence` is the resume cursor; a gap frame in `frames`
    tells the consumer frames were lost to overflow and a fresh subscription
    is required.
    """

    protocol_version: Literal["1.1"] = "1.1"
    session_id: NonEmptyStr
    after_sequence: int = Field(ge=0)
    next_sequence: int = Field(ge=0)
    frames: tuple[SurfaceStreamFrame, ...] = ()
