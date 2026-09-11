"""Stdlib loopback Surface client for the local Agent OS Runtime daemon.

Every state-changing call sends a versioned command with a fresh idempotency
key and the tracked event sequence for that session; every success is parsed
through the matching closed Pydantic contract. HTTP and network failures map
to closed client exceptions that never expose the bearer token or raw headers.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    ApprovalDisposition,
    ContractModel,
    PermissionMode,
    SurfaceApprovalCommand,
    SurfaceBeginTurnCommand,
    SurfaceBeginTurnResponse,
    SurfaceClientRef,
    SurfaceCorrectionCommand,
    SurfaceEventBatch,
    SurfaceOpenSessionCommand,
    SurfaceSessionSnapshot,
    SurfaceSetPermissionModeCommand,
    SurfaceStreamBatch,
    SurfaceStreamFrame,
    SurfaceStreamSubscription,
    SurfaceTurnCommand,
    SurfaceTurnResponse,
    TaskEvent,
    canonical_json,
)

from apps.runtime_daemon.descriptor import RuntimeDescriptor


class SurfaceClientError(RuntimeError):
    """Closed client-side error base (never carries secrets)."""


class SurfaceProtocolMismatch(SurfaceClientError):
    """The server responded with an unsupported protocol version."""


class SurfaceClientAuthenticationError(SurfaceClientError):
    """The local runtime rejected the descriptor bearer token."""


class SurfaceClientConnectionError(SurfaceClientError):
    """The local runtime could not be reached."""


class SurfaceHttpError(SurfaceClientError):
    """The local runtime returned a non-success status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class SurfaceStreamStaleError(SurfaceClientError):
    """The transient stream cursor is stale: dead daemon generation or a
    stream the current runtime does not host. Resubscribe and re-sync from
    durable session state; transient frames are never replayable."""


class SurfaceClient:
    """Loopback client over the authenticated Surface HTTP/SSE protocol."""

    def __init__(self, descriptor: RuntimeDescriptor) -> None:
        self._base_url = descriptor.base_url
        self._token = descriptor.bearer_token
        self._hostname = socket.gethostname() or "local"
        self._device_id = f"device:{uuid4().hex[:8]}"
        self._sequences: dict[str, int] = {}

    def _client_ref(self) -> SurfaceClientRef:
        return SurfaceClientRef(
            client_id=f"cli:{self._hostname}",
            client_type="CLI",
            principal_id="user:local",
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            device_id=self._device_id,
        )

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _track(self, session_id: str, snapshot: SurfaceSessionSnapshot) -> None:
        self._sequences[session_id] = snapshot.event_sequence

    def _sequence(self, session_id: str) -> int:
        return self._sequences.get(session_id, 0)

    def _request(self, method: str, path: str, payload: ContractModel | None) -> dict:
        data = None if payload is None else canonical_json(payload).encode("utf-8")
        request = urllib.request.Request(
            self._base_url + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "X-Agent-OS-Protocol": SURFACE_PROTOCOL_VERSION,
            },
        )
        return self._decode_json(request)

    def _decode_json(self, request: urllib.request.Request) -> dict:
        try:
            with urllib.request.urlopen(request) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            try:
                body = json.loads(exc.read())
            except (ValueError, UnicodeDecodeError):
                body = {}
            message = body.get("message") or body.get("error") or f"HTTP {status}"
            if status == 401:
                raise SurfaceClientAuthenticationError(message) from exc
            raise SurfaceHttpError(status, message) from exc
        except urllib.error.URLError as exc:
            raise SurfaceClientConnectionError(
                f"cannot reach the local runtime: {exc.reason}"
            ) from exc
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise SurfaceProtocolMismatch(
                "local runtime returned a non-JSON response"
            ) from exc
        if not isinstance(value, dict):
            raise SurfaceProtocolMismatch(
                "local runtime returned a non-object response"
            )
        return value

    def _check_protocol(self, value: object) -> None:
        if (
            not isinstance(value, dict)
            or value.get("protocol_version") != SURFACE_PROTOCOL_VERSION
        ):
            raise SurfaceProtocolMismatch(
                f"local runtime protocol is not {SURFACE_PROTOCOL_VERSION}"
            )

    def open_session(
        self, statement: str, *, idempotency_key: str | None = None
    ) -> SurfaceSessionSnapshot:
        if not statement.strip():
            raise ValueError("statement must be non-empty")
        command = SurfaceOpenSessionCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=self._client_ref(),
            statement=statement,
            idempotency_key=idempotency_key or f"cli-open:{uuid4().hex}",
            requested_at=self._now(),
        )
        response = self._request("POST", "/v1/surface/sessions", command)
        snapshot_value = response.get("snapshot")
        if not isinstance(snapshot_value, dict):
            raise SurfaceProtocolMismatch("local runtime returned no session snapshot")
        self._check_protocol(snapshot_value)
        snapshot = SurfaceSessionSnapshot.model_validate(snapshot_value)
        self._track(snapshot.session.session_id, snapshot)
        return snapshot

    def get_session(self, session_id: str) -> SurfaceSessionSnapshot:
        if not session_id.strip():
            raise ValueError("session_id must be non-empty")
        response = self._request("GET", f"/v1/surface/sessions/{session_id}", None)
        self._check_protocol(response)
        snapshot = SurfaceSessionSnapshot.model_validate(response)
        self._track(snapshot.session.session_id, snapshot)
        return snapshot

    def run_turn(
        self,
        session_id: str,
        text: str,
        *,
        expected_event_sequence: int | None = None,
        idempotency_key: str | None = None,
    ) -> SurfaceTurnResponse:
        if not text.strip():
            raise ValueError("turn text must be non-empty")
        command = SurfaceTurnCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=self._client_ref(),
            session_id=session_id,
            text=text,
            expected_event_sequence=(
                self._sequence(session_id)
                if expected_event_sequence is None
                else expected_event_sequence
            ),
            idempotency_key=idempotency_key or f"cli-turn:{uuid4().hex}",
            requested_at=self._now(),
        )
        response = self._request(
            "POST", f"/v1/surface/sessions/{session_id}/turns", command
        )
        return self._decode_turn(response)

    def decide_approval(
        self,
        session_id: str,
        action_digest: str,
        disposition: Literal[ApprovalDisposition.APPROVE, ApprovalDisposition.REJECT],
        reason: str,
        *,
        expected_event_sequence: int | None = None,
        idempotency_key: str | None = None,
    ) -> SurfaceTurnResponse:
        if not action_digest.strip() or not reason.strip():
            raise ValueError("action digest and reason must be non-empty")
        command = SurfaceApprovalCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=self._client_ref(),
            session_id=session_id,
            action_digest=action_digest,
            disposition=disposition,
            reason=reason,
            expected_event_sequence=(
                self._sequence(session_id)
                if expected_event_sequence is None
                else expected_event_sequence
            ),
            idempotency_key=idempotency_key or f"cli-approve:{uuid4().hex}",
            requested_at=self._now(),
        )
        response = self._request(
            "POST", f"/v1/surface/sessions/{session_id}/approvals", command
        )
        return self._decode_turn(response)

    def pause(
        self,
        session_id: str,
        reason: str = "paused by user",
        *,
        expected_event_sequence: int | None = None,
        idempotency_key: str | None = None,
    ) -> SurfaceSessionSnapshot:
        return self._control(
            session_id,
            "pause",
            reason,
            expected_event_sequence=expected_event_sequence,
            idempotency_key=idempotency_key,
        )

    def resume(
        self,
        session_id: str,
        reason: str = "resumed by user",
        *,
        expected_event_sequence: int | None = None,
        idempotency_key: str | None = None,
    ) -> SurfaceSessionSnapshot:
        return self._control(
            session_id,
            "resume",
            reason,
            expected_event_sequence=expected_event_sequence,
            idempotency_key=idempotency_key,
        )

    def correct(
        self,
        session_id: str,
        reason: str,
        *,
        expected_event_sequence: int | None = None,
        idempotency_key: str | None = None,
    ) -> SurfaceSessionSnapshot:
        if not reason.strip():
            raise ValueError("correction reason must be non-empty")
        return self._control(
            session_id,
            "correction",
            reason,
            expected_event_sequence=expected_event_sequence,
            idempotency_key=idempotency_key,
        )

    def set_permission_mode(
        self,
        session_id: str,
        mode: PermissionMode,
        *,
        expected_event_sequence: int | None = None,
        idempotency_key: str | None = None,
    ) -> SurfaceSessionSnapshot:
        """E2 operator-issued mode change (the model can never set a mode)."""
        command = SurfaceSetPermissionModeCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=self._client_ref(),
            session_id=session_id,
            mode=mode,
            expected_event_sequence=(
                self._sequence(session_id)
                if expected_event_sequence is None
                else expected_event_sequence
            ),
            idempotency_key=idempotency_key or f"cli-mode:{uuid4().hex}",
            requested_at=self._now(),
        )
        response = self._request(
            "POST", f"/v1/surface/sessions/{session_id}/mode", command
        )
        snapshot_value = response.get("snapshot")
        if not isinstance(snapshot_value, dict):
            raise SurfaceProtocolMismatch("local runtime returned no session snapshot")
        self._check_protocol(snapshot_value)
        snapshot = SurfaceSessionSnapshot.model_validate(snapshot_value)
        self._track(session_id, snapshot)
        return snapshot

    def _control(
        self,
        session_id: str,
        action: str,
        reason: str,
        *,
        expected_event_sequence: int | None,
        idempotency_key: str | None,
    ) -> SurfaceSessionSnapshot:
        command = SurfaceCorrectionCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=self._client_ref(),
            session_id=session_id,
            reason=reason,
            expected_event_sequence=(
                self._sequence(session_id)
                if expected_event_sequence is None
                else expected_event_sequence
            ),
            idempotency_key=idempotency_key or f"cli-{action}:{uuid4().hex}",
            requested_at=self._now(),
        )
        response = self._request(
            "POST", f"/v1/surface/sessions/{session_id}/{action}", command
        )
        snapshot_value = response.get("snapshot")
        if not isinstance(snapshot_value, dict):
            raise SurfaceProtocolMismatch("local runtime returned no session snapshot")
        self._check_protocol(snapshot_value)
        snapshot = SurfaceSessionSnapshot.model_validate(snapshot_value)
        self._track(session_id, snapshot)
        return snapshot

    def _decode_turn(self, response: dict) -> SurfaceTurnResponse:
        turn_value = response.get("turn")
        if not isinstance(turn_value, dict):
            raise SurfaceProtocolMismatch("local runtime returned no turn response")
        self._check_protocol(turn_value)
        snapshot_value = turn_value.get("snapshot")
        if isinstance(snapshot_value, dict):
            self._check_protocol(snapshot_value)
        turn = SurfaceTurnResponse.model_validate(turn_value)
        if turn.snapshot.session.session_id:
            self._track(turn.snapshot.session.session_id, turn.snapshot)
        return turn

    def events(
        self,
        task_id: str,
        *,
        after_sequence: int = 0,
        wait_ms: int = 0,
    ) -> SurfaceEventBatch:
        if not task_id.strip():
            raise ValueError("task_id must be non-empty")
        path = (
            f"/v1/surface/tasks/{task_id}/events"
            f"?after={after_sequence}&wait_ms={wait_ms}"
        )
        body = self._request_raw("GET", path)
        return self._decode_sse(task_id, after_sequence, body)

    def _request_raw(self, method: str, path: str) -> bytes:
        request = urllib.request.Request(
            self._base_url + path,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "X-Agent-OS-Protocol": SURFACE_PROTOCOL_VERSION,
            },
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            try:
                body = json.loads(exc.read())
            except (ValueError, UnicodeDecodeError):
                body = {}
            message = body.get("message") or body.get("error") or f"HTTP {status}"
            if status == 401:
                raise SurfaceClientAuthenticationError(message) from exc
            if status == 410:
                raise SurfaceStreamStaleError(message) from exc
            raise SurfaceHttpError(status, message) from exc
        except urllib.error.URLError as exc:
            raise SurfaceClientConnectionError(
                f"cannot reach the local runtime: {exc.reason}"
            ) from exc

    def subscribe_stream(self, session_id: str) -> SurfaceStreamSubscription:
        """Subscription-first: mint a transient stream under the current
        daemon generation before executing any turn (E1, frozen order)."""
        if not session_id.strip():
            raise ValueError("session_id must be non-empty")
        payload = self._request(
            "POST", f"/v1/surface/sessions/{session_id}/streams", None
        )
        subscription = payload.get("subscription")
        if not isinstance(subscription, dict):
            raise SurfaceProtocolMismatch(
                "local runtime returned no stream subscription"
            )
        self._check_protocol(subscription)
        return SurfaceStreamSubscription.model_validate(subscription)

    def begin_turn(self, command: SurfaceBeginTurnCommand) -> SurfaceBeginTurnResponse:
        """E1 reserve/begin-turn: bind the pre-subscribed stream and return
        the authoritative {turn_id, stream_id} without blocking on the
        provider stream."""
        payload = self._request(
            "POST",
            f"/v1/surface/sessions/{command.session_id}/begin-turn",
            command,
        )
        begin_turn = payload.get("begin_turn")
        if not isinstance(begin_turn, dict):
            raise SurfaceProtocolMismatch(
                "local runtime returned no begin-turn response"
            )
        self._check_protocol(begin_turn)
        return SurfaceBeginTurnResponse.model_validate(begin_turn)

    def stream_frames(
        self,
        session_id: str,
        *,
        stream_id: str,
        runtime_boot_id: str,
        after_sequence: int = 0,
        wait_ms: int = 0,
        last_event_id: int | None = None,
    ) -> SurfaceStreamBatch:
        """Bounded incremental read of transient display frames (E1).

        410 maps to typed `SurfaceStreamStaleError`: the generation is dead or
        the stream is unknown; resubscribe, never replay.
        """
        if not session_id.strip():
            raise ValueError("session_id must be non-empty")
        if not stream_id.strip():
            raise ValueError("stream_id must be non-empty")
        if not runtime_boot_id.strip():
            raise ValueError("runtime_boot_id must be non-empty")
        cursor = last_event_id if last_event_id is not None else after_sequence
        path = (
            f"/v1/surface/sessions/{session_id}/stream"
            f"?stream_id={stream_id}&after={cursor}&wait_ms={wait_ms}"
        )
        body = self._request_raw("GET", path)
        return self._decode_frame_sse(session_id, cursor, body)

    @staticmethod
    def _decode_frame_sse(
        session_id: str, after_sequence: int, body: bytes
    ) -> SurfaceStreamBatch:
        frames: list[SurfaceStreamFrame] = []
        next_sequence = after_sequence
        current_event: str | None = None
        data_lines: list[str] = []
        for line in body.decode("utf-8", errors="strict").splitlines():
            if line.startswith("event: "):
                current_event = line[7:]
            elif line.startswith("data: "):
                data_lines.append(line[6:])
            elif line == "":
                if current_event == "cursor":
                    cursor_payload = json.loads("\n".join(data_lines))
                    next_sequence = cursor_payload["next_sequence"]
                elif current_event is not None and data_lines:
                    frames.append(
                        SurfaceStreamFrame.model_validate(
                            json.loads("\n".join(data_lines))
                        )
                    )
                current_event = None
                data_lines = []
        return SurfaceStreamBatch(
            session_id=session_id,
            after_sequence=after_sequence,
            next_sequence=next_sequence,
            frames=tuple(frames),
        )

    @staticmethod
    def _decode_sse(
        task_id: str, after_sequence: int, body: bytes
    ) -> SurfaceEventBatch:
        events: list[TaskEvent] = []
        current_id: int | None = None
        data_lines: list[str] = []
        in_cursor = False
        next_sequence = after_sequence
        for line in body.decode("utf-8", errors="strict").splitlines():
            if line.startswith("id: "):
                current_id = int(line[4:])
            elif line.startswith("event: cursor"):
                in_cursor = True
                data_lines = []
            elif line.startswith("data: "):
                data_lines.append(line[6:])
            elif line == "":
                if in_cursor:
                    cursor_payload = json.loads("\n".join(data_lines))
                    next_sequence = cursor_payload["next_sequence"]
                    in_cursor = False
                elif current_id is not None and data_lines:
                    payload = json.loads("\n".join(data_lines))
                    events.append(TaskEvent.model_validate(payload))
                current_id = None
                data_lines = []
        return SurfaceEventBatch(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            task_id=task_id,
            after_sequence=after_sequence,
            next_sequence=next_sequence,
            events=tuple(events),
        )
