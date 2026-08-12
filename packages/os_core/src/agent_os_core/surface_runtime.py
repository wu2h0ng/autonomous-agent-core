"""Concurrency-safe application service over the versioned Surface protocol.

SurfaceRuntime serializes every state-changing Surface command per session,
enforces protocol version, principal scope, exact durable event sequence, and
idempotency-key/digest rules before any provider invocation, and delegates the
effect itself to the composition-root application port. It never appends
Surface-only truth: all durable state remains the Task event stream.
"""

from __future__ import annotations

import hashlib
from threading import RLock
from typing import Any, Protocol, TypeVar

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    PrincipalIdentity,
    SurfaceApprovalCommand,
    SurfaceClientRef,
    SurfaceCorrectionCommand,
    SurfaceEventBatch,
    SurfaceOpenSessionCommand,
    SurfaceSessionSnapshot,
    SurfaceSessionStatus,
    SurfaceTurnCommand,
    SurfaceTurnResponse,
    canonical_json,
)

ResponseT = TypeVar(
    "ResponseT",
    SurfaceSessionSnapshot,
    SurfaceTurnResponse,
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


class SurfaceApplicationPort(Protocol):
    """Composition-root authority consumed by the Surface runtime service."""

    @property
    def principal(self) -> PrincipalIdentity: ...

    def surface_open_session(
        self, command: SurfaceOpenSessionCommand
    ) -> SurfaceSessionSnapshot: ...

    def surface_run_turn(self, command: SurfaceTurnCommand) -> SurfaceTurnResponse: ...

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

    def surface_session_snapshot(self, session_id: str) -> SurfaceSessionSnapshot: ...

    def surface_event_batch(self, task_id: str, after_sequence: int) -> SurfaceEventBatch: ...

    def surface_task_for_session(self, session_id: str) -> str: ...

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

    def __init__(self, application: SurfaceApplicationPort) -> None:
        self._application = application
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

    def run_turn(self, command: SurfaceTurnCommand) -> SurfaceTurnResponse:
        with self._session_lock(command.session_id):
            return self._idempotent(
                scope=f"surface:turn:{command.session_id}",
                key=command.idempotency_key,
                command=command,
                response_type=SurfaceTurnResponse,
                operation=lambda: self._run_turn_once(command),
            )

    def decide_approval(
        self, command: SurfaceApprovalCommand
    ) -> SurfaceTurnResponse:
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

    def event_batch(self, task_id: str, after_sequence: int) -> SurfaceEventBatch:
        if not task_id.strip():
            raise ValueError("task_id must be non-empty")
        if isinstance(after_sequence, bool) or after_sequence < 0:
            raise ValueError("after_sequence must be a non-negative integer")
        return self._application.surface_event_batch(task_id, after_sequence)

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
