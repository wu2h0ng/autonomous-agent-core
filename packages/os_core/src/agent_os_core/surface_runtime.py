"""Concurrency-safe application service over the versioned Surface protocol.

SurfaceRuntime serializes every state-changing Surface command per session,
enforces protocol version, principal scope, exact durable event sequence, and
idempotency-key/digest rules before any provider invocation, and delegates the
effect itself to the composition-root application port. It never appends
Surface-only truth: all durable state remains the Task event stream.
"""

from __future__ import annotations

import hashlib
import time
from threading import RLock
from typing import Any, Protocol, TypeVar

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    PrincipalIdentity,
    SurfaceApprovalCommand,
    SurfaceBeginTurnCommand,
    SurfaceBeginTurnResponse,
    SurfaceClientRef,
    SurfaceCorrectionCommand,
    SurfaceEventBatch,
    SurfaceOpenSessionCommand,
    SurfaceProviderClearCommand,
    SurfaceProviderConfigureCommand,
    SurfaceProviderStatus,
    SurfaceSessionListResponse,
    SurfaceSessionSnapshot,
    SurfaceSessionStatus,
    SurfaceSetPermissionModeCommand,
    SurfaceStreamBatch,
    SurfaceTurnCommand,
    SurfaceTurnResponse,
    TurnTrace,
    canonical_json,
)

from .session_stream import SessionStreamRegistry, StreamCursor, SurfaceStreamGone

ResponseT = TypeVar(
    "ResponseT",
    SurfaceSessionSnapshot,
    SurfaceTurnResponse,
    SurfaceBeginTurnResponse,
)


class SurfaceProtocolError(ValueError):
    """A Surface command failed protocol validation."""


class SurfaceScopeError(PermissionError):
    """The Surface client scope does not bind the runtime principal."""


class SurfaceSequenceConflict(RuntimeError):
    """The expected event sequence does not match durable task truth."""


class SurfaceIdempotencyConflict(RuntimeError):
    """An idempotency key was reused with a different canonical command."""


class SurfaceSessionNotFound(LookupError):
    """No durable session binds the requested identity."""


class SurfaceTurnInProgress(RuntimeError):
    """A begin-turn arrived while the session's prior turn is uncommitted.

    Frozen (rev 9): one in-flight turn per session; the provider is never
    started and no second turn is queued, multiplexed, or bound.
    """


class SurfaceApplicationPort(Protocol):
    """Composition-root authority consumed by the Surface runtime service."""

    @property
    def principal(self) -> PrincipalIdentity: ...

    def surface_open_session(
        self, command: SurfaceOpenSessionCommand
    ) -> SurfaceSessionSnapshot: ...

    def surface_run_turn(self, command: SurfaceTurnCommand) -> SurfaceTurnResponse: ...

    def surface_has_uncommitted_turn(self, session_id: str) -> bool: ...

    def surface_begin_turn(
        self, command: SurfaceBeginTurnCommand
    ) -> SurfaceBeginTurnResponse: ...

    def surface_decide_approval(
        self, command: SurfaceApprovalCommand
    ) -> SurfaceTurnResponse: ...

    def surface_pause_session(
        self, command: SurfaceCorrectionCommand
    ) -> SurfaceSessionSnapshot: ...

    def surface_resume_session(
        self, command: SurfaceCorrectionCommand
    ) -> SurfaceSessionSnapshot: ...

    def surface_correct_session(
        self, command: SurfaceCorrectionCommand
    ) -> SurfaceSessionSnapshot: ...

    def surface_set_permission_mode(
        self, command: SurfaceSetPermissionModeCommand
    ) -> SurfaceSessionSnapshot: ...

    def surface_provider_status(self) -> SurfaceProviderStatus: ...

    def surface_configure_provider(
        self, command: SurfaceProviderConfigureCommand
    ) -> SurfaceProviderStatus: ...

    def surface_clear_provider(
        self, command: SurfaceProviderClearCommand
    ) -> SurfaceProviderStatus: ...

    def surface_session_snapshot(self, session_id: str) -> SurfaceSessionSnapshot: ...
    def surface_sessions_listing(
        self, limit: int, cursor: str | None
    ) -> SurfaceSessionListResponse: ...

    def surface_event_batch(
        self, task_id: str, after_sequence: int
    ) -> SurfaceEventBatch: ...

    def surface_files_listing(self, task_id: str) -> list[dict[str, Any]]: ...

    def surface_task_overview(self, task_id: str) -> dict[str, Any]: ...

    def surface_turn_trace(
        self, session_id: str, turn_id: str | None = None
    ) -> TurnTrace: ...

    def surface_task_for_session(self, session_id: str) -> str: ...

    def surface_conflict_projection(self, session_id: str) -> Any | None: ...

    def surface_current_sequence(self, task_id: str) -> int: ...

    def surface_idempotency_record(
        self, scope: str, key: str
    ) -> dict[str, Any] | None: ...

    def surface_store_idempotency(
        self, scope: str, key: str, record: dict[str, Any]
    ) -> bool: ...


def command_digest(command: Any) -> str:
    """Canonical digest of the exact serialized command."""

    payload = command.model_dump(mode="json")
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class SurfaceRuntime:
    """Serialized, idempotent Surface command authority for one workspace."""

    def __init__(
        self,
        application: SurfaceApplicationPort,
        stream_registry: SessionStreamRegistry | None = None,
    ) -> None:
        self._application = application
        self._stream_registry = stream_registry
        self._locks: dict[str, RLock] = {}
        self._locks_guard = RLock()

    def _session_lock(self, session_id: str) -> RLock:
        with self._locks_guard:
            return self._locks.setdefault(session_id, RLock())

    def open_session(
        self, command: SurfaceOpenSessionCommand
    ) -> SurfaceSessionSnapshot:
        self._require_protocol(command.protocol_version)
        self._require_principal_scope(command.client)
        with self._session_lock(f"open:{command.idempotency_key}"):
            return self._idempotent(
                scope="surface:open",
                key=command.idempotency_key,
                command=command,
                response_type=SurfaceSessionSnapshot,
                operation=lambda: self._application.surface_open_session(command),
            )

    def get_session(self, session_id: str) -> SurfaceSessionSnapshot:
        if not session_id.strip():
            raise ValueError("session_id must be non-empty")
        return self._application.surface_session_snapshot(session_id)

    def list_sessions(
        self, limit: int = 20, cursor: str | None = None
    ) -> SurfaceSessionListResponse:
        """Read-only, bounded session listing (C2)."""
        if not 1 <= limit <= 100:
            raise ValueError("session list limit must be between 1 and 100")
        if cursor is not None and not cursor.strip():
            raise ValueError("session list cursor must be non-empty when present")
        return self._application.surface_sessions_listing(limit, cursor)

    def run_turn(self, command: SurfaceTurnCommand) -> SurfaceTurnResponse:
        with self._session_lock(command.session_id):
            return self._idempotent(
                scope=f"surface:turn:{command.session_id}",
                key=command.idempotency_key,
                command=command,
                response_type=SurfaceTurnResponse,
                operation=lambda: self._run_turn_once(command),
            )

    def begin_turn(self, command: SurfaceBeginTurnCommand) -> SurfaceBeginTurnResponse:
        """E1 reserve/begin-turn: the single turn_id source (frozen).

        Idempotent replays return the recorded `{turn_id, stream_id}` without
        re-invoking the provider; the same key with a different canonical
        digest fails typed `SurfaceIdempotencyConflict` with no re-bind.
        """
        with self._session_lock(command.session_id):
            return self._idempotent(
                scope=f"surface:begin-turn:{command.session_id}",
                key=command.idempotency_key,
                command=command,
                response_type=SurfaceBeginTurnResponse,
                operation=lambda: self._begin_turn_once(command),
            )

    def subscribe_stream(self, session_id: str) -> str:
        """Mint a new transient stream under the current daemon generation.

        The TUI subscribes first (subscription-before-execution, frozen), then
        binds a begin-turn to the returned stream_id."""
        if self._stream_registry is None:
            raise SurfaceProtocolError("stream registry is not configured")
        return self._stream_registry.subscribe(session_id)

    @property
    def stream_runtime_boot_id(self) -> str:
        """Daemon generation identity binding every transient stream cursor."""
        if self._stream_registry is None:
            raise SurfaceProtocolError("stream registry is not configured")
        return self._stream_registry.runtime_boot_id

    def stream_batch(
        self,
        session_id: str,
        cursor: StreamCursor,
        wait_ms: int = 0,
    ) -> SurfaceStreamBatch:
        """Bounded long-poll read of transient frames after the cursor.

        Stale generations and unknown streams fail typed `SurfaceStreamGone`;
        gap frames are synthesized on the read path and are never buffer
        residents. `wait_ms` is clamped to the same bound as durable events.
        """
        if self._stream_registry is None:
            raise SurfaceProtocolError("stream registry is not configured")
        if isinstance(wait_ms, bool) or not 0 <= wait_ms <= 25000:
            raise ValueError("wait_ms must be within 0..25000")
        deadline = time.monotonic() + wait_ms / 1000.0
        frames: list[Any] = []
        while True:
            frames = self._stream_registry.read(session_id, cursor)
            if frames or time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        next_sequence = cursor.frame_sequence
        for frame in frames:
            next_sequence = max(next_sequence, frame.frame_sequence)
        return SurfaceStreamBatch(
            session_id=session_id,
            after_sequence=cursor.frame_sequence,
            next_sequence=next_sequence,
            frames=tuple(frames),
        )

    def decide_approval(self, command: SurfaceApprovalCommand) -> SurfaceTurnResponse:
        with self._session_lock(command.session_id):
            return self._idempotent(
                scope=f"surface:approval:{command.session_id}",
                key=command.idempotency_key,
                command=command,
                response_type=SurfaceTurnResponse,
                operation=lambda: self._decide_approval_once(command),
            )

    def pause(self, command: SurfaceCorrectionCommand) -> SurfaceSessionSnapshot:
        return self._control_command(
            command,
            f"surface:pause:{command.session_id}",
            self._application.surface_pause_session,
        )

    def resume(self, command: SurfaceCorrectionCommand) -> SurfaceSessionSnapshot:
        return self._control_command(
            command,
            f"surface:resume:{command.session_id}",
            self._application.surface_resume_session,
        )

    def correct(self, command: SurfaceCorrectionCommand) -> SurfaceSessionSnapshot:
        return self._control_command(
            command,
            f"surface:correct:{command.session_id}",
            self._application.surface_correct_session,
        )

    def set_permission_mode(
        self, command: SurfaceSetPermissionModeCommand
    ) -> SurfaceSessionSnapshot:
        """E2 operator-issued mode change: idempotent, sequence-exact,
        principal-scoped (operator-only; the model can never set a mode)."""
        with self._session_lock(command.session_id):
            return self._idempotent(
                scope=f"surface:mode:{command.session_id}",
                key=command.idempotency_key,
                command=command,
                response_type=SurfaceSessionSnapshot,
                operation=lambda: self._set_permission_mode_once(command),
            )

    def _set_permission_mode_once(
        self, command: SurfaceSetPermissionModeCommand
    ) -> SurfaceSessionSnapshot:
        self._require_protocol(command.protocol_version)
        task_id = self._application.surface_task_for_session(command.session_id)
        self._require_principal_scope(command.client)
        self._require_sequence(task_id, command.expected_event_sequence)
        self._require_open_session(command.session_id)
        return self._application.surface_set_permission_mode(command)

    def provider_status(self) -> SurfaceProviderStatus:
        return self._application.surface_provider_status()

    def configure_provider(
        self, command: SurfaceProviderConfigureCommand
    ) -> SurfaceProviderStatus:
        """Operator-issued live provider configuration over the surface protocol.

        The credential is transient: the application keeps it in an in-memory
        env resolver and never persists it. This validates protocol version and
        principal scope before delegating; it is not a policy gate input and
        does not alter permit/approval for any capability.
        """

        self._require_protocol(command.protocol_version)
        self._require_principal_scope(command.client)
        return self._application.surface_configure_provider(command)

    def clear_provider(
        self, command: SurfaceProviderClearCommand
    ) -> SurfaceProviderStatus:
        """Operator-issued removal of the persisted provider config + key."""

        self._require_protocol(command.protocol_version)
        self._require_principal_scope(command.client)
        return self._application.surface_clear_provider(command)

    def event_batch(self, task_id: str, after_sequence: int) -> SurfaceEventBatch:
        if not task_id.strip():
            raise ValueError("task_id must be non-empty")
        if isinstance(after_sequence, bool) or after_sequence < 0:
            raise ValueError("after_sequence must be a non-negative integer")
        return self._application.surface_event_batch(task_id, after_sequence)

    def turn_trace(self, session_id: str, turn_id: str | None = None) -> TurnTrace:
        """Read-only trace of one governed turn.

        A projection read, not a command: it holds no session lock, writes no
        idempotency record and changes no state, because a read that could change
        behaviour is not a read. ``turn_id=None`` asks the application for the
        session's most recently started turn.
        """

        if not session_id.strip():
            raise ValueError("session_id must be non-empty")
        if turn_id is not None and not turn_id.strip():
            raise ValueError("turn_id must be non-empty when provided")
        return self._application.surface_turn_trace(session_id, turn_id)

    def conflict_projection(self, session_id: str) -> Any | None:
        if not session_id.strip():
            raise ValueError("session_id must be non-empty")
        return self._application.surface_conflict_projection(session_id)

    def _control_command(
        self,
        command: SurfaceCorrectionCommand,
        scope: str,
        operation: Any,
    ) -> SurfaceSessionSnapshot:
        with self._session_lock(command.session_id):
            return self._idempotent(
                scope=scope,
                key=command.idempotency_key,
                command=command,
                response_type=SurfaceSessionSnapshot,
                operation=lambda: self._control_once(command, operation),
            )

    def _run_turn_once(self, command: SurfaceTurnCommand) -> SurfaceTurnResponse:
        self._require_protocol(command.protocol_version)
        task_id = self._application.surface_task_for_session(command.session_id)
        self._require_principal_scope(command.client)
        self._require_sequence(task_id, command.expected_event_sequence)
        self._require_open_session(command.session_id)
        return self._application.surface_run_turn(command)

    def _begin_turn_once(
        self, command: SurfaceBeginTurnCommand
    ) -> SurfaceBeginTurnResponse:
        self._require_protocol(command.protocol_version)
        task_id = self._application.surface_task_for_session(command.session_id)
        self._require_principal_scope(command.client)
        self._require_sequence(task_id, command.expected_event_sequence)
        self._require_open_session(command.session_id)
        if self._stream_registry is not None and not self._stream_registry.is_live(
            command.session_id,
            command.stream.runtime_boot_id,
            command.stream.stream_id,
        ):
            # Frozen: invalid stream fails typed STREAM_GONE; the provider is
            # never started.
            raise SurfaceStreamGone(
                "referenced stream is not live in this daemon generation"
            )
        if self._application.surface_has_uncommitted_turn(command.session_id):
            # Frozen (rev 9): one in-flight turn per session; no queueing, no
            # multiplexing, provider never started.
            raise SurfaceTurnInProgress(
                "a prior turn is still uncommitted for this session"
            )
        response = self._application.surface_begin_turn(command)
        if self._stream_registry is not None:
            self._stream_registry.bind_turn(
                command.session_id, command.stream.stream_id, response.turn_id
            )
        return response

    def _decide_approval_once(
        self, command: SurfaceApprovalCommand
    ) -> SurfaceTurnResponse:
        self._require_protocol(command.protocol_version)
        task_id = self._application.surface_task_for_session(command.session_id)
        self._require_principal_scope(command.client)
        self._require_sequence(task_id, command.expected_event_sequence)
        self._require_open_session(command.session_id)
        return self._application.surface_decide_approval(command)

    def _control_once(
        self,
        command: SurfaceCorrectionCommand,
        operation: Any,
    ) -> SurfaceSessionSnapshot:
        self._require_protocol(command.protocol_version)
        task_id = self._application.surface_task_for_session(command.session_id)
        self._require_principal_scope(command.client)
        self._require_sequence(task_id, command.expected_event_sequence)
        self._require_open_session(command.session_id)
        return operation(command)

    def _idempotent(
        self,
        *,
        scope: str,
        key: str,
        command: Any,
        response_type: type[ResponseT],
        operation: Any,
    ) -> ResponseT:
        digest = command_digest(command)
        record = self._application.surface_idempotency_record(scope, key)
        if record is not None:
            stored_response = record.get("response")
            if record.get("command_digest") != digest or not isinstance(
                stored_response, dict
            ):
                raise SurfaceIdempotencyConflict(
                    "idempotency key reused with a different canonical command"
                )
            return response_type.model_validate(stored_response)
        response = operation()
        stored = self._application.surface_store_idempotency(
            scope,
            key,
            {
                "command_digest": digest,
                "response": response.model_dump(mode="json"),
            },
        )
        if not stored:
            winner = self._application.surface_idempotency_record(scope, key)
            winning_response = None if winner is None else winner.get("response")
            if (
                winner is None
                or winner.get("command_digest") != digest
                or not isinstance(winning_response, dict)
            ):
                raise SurfaceIdempotencyConflict(
                    "idempotency key was claimed by a different command"
                )
            return response_type.model_validate(winning_response)
        return response

    def _require_protocol(self, protocol_version: str) -> None:
        if protocol_version != SURFACE_PROTOCOL_VERSION:
            raise SurfaceProtocolError(
                f"unsupported surface protocol version {protocol_version}"
            )

    def _require_principal_scope(self, client: SurfaceClientRef) -> None:
        principal = self._application.principal
        if (
            client.tenant_id != principal.tenant_id
            or client.workspace_id != principal.workspace_id
            or client.principal_id != principal.principal_id
        ):
            raise SurfaceScopeError(
                "surface client scope does not bind the runtime principal"
            )

    def _require_sequence(self, task_id: str, expected_event_sequence: int) -> None:
        current_sequence = self._application.surface_current_sequence(task_id)
        if expected_event_sequence != current_sequence:
            raise SurfaceSequenceConflict(
                "expected event sequence "
                f"{expected_event_sequence} does not match "
                f"current sequence {current_sequence}"
            )

    def _require_open_session(self, session_id: str) -> None:
        snapshot = self._application.surface_session_snapshot(session_id)
        if snapshot.status is SurfaceSessionStatus.CLOSED:
            raise SurfaceProtocolError("surface session is closed")
