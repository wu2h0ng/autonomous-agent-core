from __future__ import annotations

import re
from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType
from typing import Any, Literal, cast

from pydantic import Field, model_validator

from .agent_spawn import ChildAgentTurnAttribution, ChildAgentType
from .authority import ApprovalDisposition
from .common import ContractModel, NonEmptyStr, UtcDateTime
from .provider import ProviderMessage, SessionRef
from .runtime import TaskEvent


SurfaceProtocolVersion = Literal["1.1", "1.2"]
"""Every Surface protocol version this build understands, ascending by minor.

The version is ``MAJOR.MINOR``. A MINOR step is additive only, so a reader at
minor *n* understands every payload at minor <= *n*; the MAJOR step is what
breaks. Growing this union is the only way to admit a new version.
"""

SURFACE_PROTOCOL_VERSION: SurfaceProtocolVersion = "1.2"
"""The version this build SPEAKS: E3 usage v2 cost-honesty (1.1) plus the
additive P3a-2 ``awaiting_approval`` session-listing field (1.2)."""

SURFACE_PROTOCOL_MIN_SUPPORTED: SurfaceProtocolVersion = "1.1"
"""The oldest minor this build still NEGOTIATES with.

An older reader is served a payload projected onto its own minor rather than
the current shape under an older version string: the two must never disagree.
"""

SURFACE_PROTOCOL_ADDITIVE_MINORS: Mapping[SurfaceProtocolVersion, tuple[str, ...]] = (
    MappingProxyType(
        {
            # minor -> the wire fields that minor ADDED, declared ascending.
            # Registration is mandatory: this is the ONLY thing
            # `downgrade_surface_payload` is permitted to remove, so an
            # unregistered additive field would leak to older readers.
            "1.2": ("awaiting_approval",),
        }
    )
)
"""Ordered registry of additive minors and the fields each one added."""


class SurfaceProtocolVersionError(ValueError):
    """A surface protocol version string is malformed, or names a version this
    build cannot negotiate with."""


_SURFACE_PROTOCOL_VERSION_PATTERN = re.compile(
    r"(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)"
)


def parse_surface_protocol_version(value: str) -> tuple[int, int]:
    """Parse ``MAJOR.MINOR`` into ``(major, minor)``.

    Raises ``SurfaceProtocolVersionError`` for anything else — a non-string, an
    empty string, a single segment, a non-numeric segment, or leading zeros.
    Callers must not fall back to a default: an unparsable version is not an
    older version.
    """

    if not isinstance(value, str):
        raise SurfaceProtocolVersionError(
            f"surface protocol version must be a string, got {type(value).__name__}"
        )
    match = _SURFACE_PROTOCOL_VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise SurfaceProtocolVersionError(
            f"surface protocol version {value!r} is not MAJOR.MINOR"
        )
    return int(match.group("major")), int(match.group("minor"))


def surface_protocol_supported_versions() -> tuple[SurfaceProtocolVersion, ...]:
    """Every version this build negotiates, ascending by minor.

    The floor plus the declared additive minors. Derived from the registry, so
    declaring a new minor is what makes it negotiable.
    """

    versions: list[SurfaceProtocolVersion] = [SURFACE_PROTOCOL_MIN_SUPPORTED]
    versions.extend(SURFACE_PROTOCOL_ADDITIVE_MINORS)
    return tuple(versions)


def negotiate_surface_protocol_version(supplied: str) -> SurfaceProtocolVersion:
    """Return the version to serve ``supplied`` at, or raise.

    Ordered rule — same MAJOR as this build and a minor inside
    ``[SURFACE_PROTOCOL_MIN_SUPPORTED, SURFACE_PROTOCOL_VERSION]``. A same-MAJOR
    minor below the floor, a higher MAJOR, and a malformed value are all
    rejected: compatibility is a declared set, never open-ended tolerance.
    """

    major, minor = parse_surface_protocol_version(supplied)
    supported = surface_protocol_supported_versions()
    normalized = f"{major}.{minor}"
    if normalized in supported:
        return cast(SurfaceProtocolVersion, normalized)
    raise SurfaceProtocolVersionError(
        f"unsupported surface protocol version {supplied!r}; this build "
        f"negotiates {', '.join(supported)}"
    )


def surface_protocol_readable_versions(reader: str) -> tuple[SurfaceProtocolVersion, ...]:
    """The versions a reader at ``reader`` may accept from a peer, ascending.

    Ordered and bounded: this build's declared supported set, filtered to the
    reader's own MAJOR and to minors no newer than the reader. A reader knows
    every shape at or below its own minor, so a newer client still reads an
    older server — while a version this build never declared, a foreign MAJOR
    and an unparsable value are all outside the set, so nothing is accepted by
    accident. Empty for a reader that is not itself a version.
    """

    try:
        reader_major, reader_minor = parse_surface_protocol_version(reader)
    except SurfaceProtocolVersionError:
        return ()
    return tuple(
        version
        for version in surface_protocol_supported_versions()
        if parse_surface_protocol_version(version)[0] == reader_major
        and parse_surface_protocol_version(version)[1] <= reader_minor
    )


def surface_protocol_unknown_fields(negotiated: str) -> tuple[str, ...]:
    """Every wire field a reader at ``negotiated`` cannot know about.

    The additive registry entries for all minors ABOVE ``negotiated``,
    concatenated in ascending minor order; empty at the newest minor. Ordering
    is part of the contract: the result is deterministic and depends only on the
    registered minors, so downgrading is reproducible rather than best-effort.
    """

    version = negotiate_surface_protocol_version(negotiated)
    negotiated_major, negotiated_minor = parse_surface_protocol_version(version)
    unknown: list[str] = []
    for minor, fields in SURFACE_PROTOCOL_ADDITIVE_MINORS.items():
        minor_major, minor_number = parse_surface_protocol_version(minor)
        if minor_major != negotiated_major or minor_number > negotiated_minor:
            unknown.extend(fields)
    return tuple(unknown)


def _downgrade_protocol_version(
    declared: str, negotiated: SurfaceProtocolVersion
) -> str:
    """The version to declare for ``negotiated`` given a payload's ``declared``.

    Downgrades only: a payload never claims a version newer than the shape it
    actually carries, and a version this build cannot parse is left untouched so
    the reader rejects it instead of being reassured.
    """

    try:
        declared_major, declared_minor = parse_surface_protocol_version(declared)
    except SurfaceProtocolVersionError:
        return declared
    negotiated_major, negotiated_minor = parse_surface_protocol_version(negotiated)
    if declared_major == negotiated_major and declared_minor > negotiated_minor:
        return negotiated
    return declared


def _project(value: Any, unknown: frozenset[str], negotiated: SurfaceProtocolVersion) -> Any:
    if isinstance(value, dict):
        projected: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and key in unknown:
                continue
            if key == "protocol_version" and isinstance(item, str):
                projected[key] = _downgrade_protocol_version(item, negotiated)
                continue
            projected[key] = _project(item, unknown, negotiated)
        return projected
    if isinstance(value, list):
        return [_project(item, unknown, negotiated) for item in value]
    if isinstance(value, tuple):
        return tuple(_project(item, unknown, negotiated) for item in value)
    return value


def downgrade_surface_payload(payload: Any, negotiated: str) -> Any:
    """Project a serialized server payload onto ``negotiated``.

    Two ordered effects, both driven by ``SURFACE_PROTOCOL_ADDITIVE_MINORS`` and
    nothing else:

    * every field added by a minor above ``negotiated`` is REMOVED, so a strict
      older reader never meets a field it must reject;
    * a ``protocol_version`` newer than ``negotiated`` is REWRITTEN to
      ``negotiated``, so the version on the wire is what actually governs the
      payload.

    What an older reader does with the CURRENT shape is therefore fixed, not
    vague: it is rejected, because `extra="forbid"` is unchanged and the current
    shape carries fields its contract never declared. That is why this
    projection exists instead of a tolerant parse.

    Everything else passes through untouched — this is not permission to accept
    unknown fields, and ``negotiated`` must be a version this build supports.
    """

    negotiated_version = negotiate_surface_protocol_version(negotiated)
    unknown = frozenset(surface_protocol_unknown_fields(negotiated_version))
    return _project(payload, unknown, negotiated_version)


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
    protocol_version: SurfaceProtocolVersion
    client: SurfaceClientRef
    statement: NonEmptyStr
    idempotency_key: NonEmptyStr
    requested_at: UtcDateTime


class SurfaceTurnCommand(ContractModel):
    protocol_version: SurfaceProtocolVersion
    client: SurfaceClientRef
    session_id: NonEmptyStr
    text: NonEmptyStr
    expected_event_sequence: int = Field(ge=0)
    idempotency_key: NonEmptyStr
    requested_at: UtcDateTime


class SurfaceApprovalCommand(ContractModel):
    protocol_version: SurfaceProtocolVersion
    client: SurfaceClientRef
    session_id: NonEmptyStr
    action_digest: NonEmptyStr
    disposition: Literal[ApprovalDisposition.APPROVE, ApprovalDisposition.REJECT]
    reason: NonEmptyStr
    expected_event_sequence: int = Field(ge=0)
    idempotency_key: NonEmptyStr
    requested_at: UtcDateTime


class SurfaceCorrectionCommand(ContractModel):
    protocol_version: SurfaceProtocolVersion
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

    protocol_version: SurfaceProtocolVersion
    client: SurfaceClientRef
    session_id: NonEmptyStr
    mode: PermissionMode
    expected_event_sequence: int = Field(ge=0)
    idempotency_key: NonEmptyStr
    requested_at: UtcDateTime


class SurfaceProviderStatus(ContractModel):
    """Redacted live provider configuration for the terminal.

    Never carries the credential value: only the non-secret profile metadata,
    the opaque ``credential_ref_id``, whether a non-secret config is persisted,
    and where the key comes from (keychain | env | none).
    """

    protocol_version: SurfaceProtocolVersion = SURFACE_PROTOCOL_VERSION
    configured: bool
    provider_id: NonEmptyStr | None = None
    model_id: NonEmptyStr | None = None
    endpoint_class: NonEmptyStr | None = None
    credential_ref_id: NonEmptyStr | None = None
    base_url: NonEmptyStr | None = None
    persisted: bool = False
    key_source: Literal["keychain", "env", "none"] | None = None


class SurfaceProviderClearCommand(ContractModel):
    """Operator-issued removal of the persisted provider config + key.

    Clears the non-secret config file and the stored keychain credential so the
    provider is no longer auto-loaded; the running process keeps its current
    provider until restart.
    """

    protocol_version: SurfaceProtocolVersion
    client: SurfaceClientRef


class SurfaceProviderConfigureCommand(ContractModel):
    """Operator-issued provider configuration over the surface protocol.

    ``api_key`` is a transient credential: the runtime keeps it in an
    environment-backed in-memory resolver for the process lifetime and never
    persists it to the database, state files, artifacts or logs.
    """

    protocol_version: SurfaceProtocolVersion
    client: SurfaceClientRef
    base_url: NonEmptyStr
    model: NonEmptyStr
    api_key: NonEmptyStr
    endpoint_class: NonEmptyStr = "openai-compatible"
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, ge=1)


class PendingSurfaceApproval(ContractModel):
    action_digest: NonEmptyStr
    capability_id: NonEmptyStr
    proposal_id: NonEmptyStr
    preview: NonEmptyStr
    requested_at: UtcDateTime


class SurfaceSessionSnapshot(ContractModel):
    protocol_version: SurfaceProtocolVersion
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

    ``awaiting_approval`` is the protocol-1.2 additive field: it is registered in
    ``SURFACE_PROTOCOL_ADDITIVE_MINORS`` so a negotiated 1.1 reader is served a
    1.1 projection without it, instead of being handed a field its contract
    would reject. Removing that registration would leak 1.2 to 1.1 readers.
    """

    session_id: NonEmptyStr
    task_id: NonEmptyStr
    status: SurfaceSessionStatus
    permission_mode: PermissionMode = "ASK"
    message_count: int = Field(ge=0)
    updated_at: UtcDateTime
    awaiting_approval: bool = False


class SurfaceSessionListResponse(ContractModel):
    protocol_version: SurfaceProtocolVersion
    sessions: tuple[SurfaceSessionSummary, ...] = ()
    next_cursor: NonEmptyStr | None = None


class ChildAgentOrphanProjection(ContractModel):
    """An in-flight child whose spawning runtime generation is gone.

    Read-only projection: it names what the operator would be reconciling. It
    carries no prompt or completion text.
    """

    spawn_id: NonEmptyStr
    child_session_id: NonEmptyStr
    child_task_id: NonEmptyStr
    description: NonEmptyStr
    agent_type: ChildAgentType
    spawn_runtime_boot_id: NonEmptyStr | None = None
    spawned_by_current_generation: bool = False


class SurfaceChildAgentReconcileCommand(ContractModel):
    """Operator-declared reconciliation of a session's ownerless children."""

    protocol_version: Literal["1.1"]
    client: SurfaceClientRef
    session_id: NonEmptyStr
    reason: NonEmptyStr
    idempotency_key: NonEmptyStr
    requested_at: UtcDateTime


class SurfaceChildAgentsResponse(ContractModel):
    """Attribution roll-up plus the burial picture for one session.

    ``turns`` reuses the frozen per-turn attribution (each turn's totals include
    its children and say so); ``orphaned`` lists in-flight children with no live
    runtime owner; ``buried`` lists what this call reconciled, if any.
    """

    protocol_version: Literal["1.1"]
    session_id: NonEmptyStr
    children_included_in_totals: Literal[True] = True
    turns: tuple[ChildAgentTurnAttribution, ...] = ()
    orphaned: tuple[ChildAgentOrphanProjection, ...] = ()
    buried: tuple[ChildAgentBurialRecord, ...] = ()


class ChildAgentBurialRecord(ContractModel):
    """One durable operator-declared burial, echoed to the operator."""

    spawn_id: NonEmptyStr
    child_session_id: NonEmptyStr
    child_task_id: NonEmptyStr
    reason_code: NonEmptyStr
    outcome: NonEmptyStr
    declared_by: NonEmptyStr
    declared_at: UtcDateTime
    runtime_boot_id: NonEmptyStr
    runtime_pid: int = Field(ge=1)
    reason: NonEmptyStr
    child_open_turn_id: NonEmptyStr | None = None


class SurfaceTurnResponse(ContractModel):
    """One completed turn. `stop_reason` is the durable stop reason verbatim.

    Defined non-success values include `stopped_by_operator`: the operator
    durably paused the session (`POST /v1/surface/sessions/{id}/pause`) while
    the turn was in flight, so the turn ended before its next provider call or
    capability dispatch and the Run stays PAUSED until an explicit resume.
    """

    protocol_version: SurfaceProtocolVersion

    snapshot: SurfaceSessionSnapshot
    turn_id: NonEmptyStr | None = None
    text: NonEmptyStr
    steps: tuple[ProviderMessage, ...] = ()
    stop_reason: NonEmptyStr
    total_tokens: int = Field(ge=0)


class SurfaceEventBatch(ContractModel):
    protocol_version: SurfaceProtocolVersion
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

    protocol_version: SurfaceProtocolVersion = SURFACE_PROTOCOL_VERSION
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

    protocol_version: SurfaceProtocolVersion
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

    protocol_version: SurfaceProtocolVersion = SURFACE_PROTOCOL_VERSION
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

    protocol_version: SurfaceProtocolVersion = SURFACE_PROTOCOL_VERSION
    runtime_boot_id: NonEmptyStr
    stream_id: NonEmptyStr


class SurfaceStreamBatch(ContractModel):
    """Bounded transient frame batch for the stream SSE endpoint (E1).

    Cursors are per-stream frame sequences (never durable Task event
    sequences). `next_sequence` is the resume cursor; a gap frame in `frames`
    tells the consumer frames were lost to overflow and a fresh subscription
    is required.
    """

    protocol_version: SurfaceProtocolVersion = SURFACE_PROTOCOL_VERSION
    session_id: NonEmptyStr
    after_sequence: int = Field(ge=0)
    next_sequence: int = Field(ge=0)
    frames: tuple[SurfaceStreamFrame, ...] = ()
