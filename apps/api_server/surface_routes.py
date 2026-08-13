"""Authenticated Surface HTTP/SSE routes for the local runtime protocol.

The Surface command contracts are parsed into closed Pydantic models before
dispatch; authentication, scope, sequence, idempotency, and validation errors
are mapped to stable HTTP statuses without leaking tracebacks, secret-bearing
values, or Python reprs. SSE cursors are monotonic and resumable via
``Last-Event-ID`` with bounded long-poll.
"""

from __future__ import annotations

import secrets
import time
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

from ._cors import _tauri_origin_cors

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    SurfaceApprovalCommand,
    SurfaceCorrectionCommand,
    SurfaceOpenSessionCommand,
    SurfaceTurnCommand,
    canonical_json,
)
from agent_os_core import (
    InvalidTransitionError,
    SurfaceIdempotencyConflict,
    SurfaceProtocolError,
    SurfaceRuntime,
    SurfaceScopeError,
    SurfaceSequenceConflict,
    SurfaceSessionNotFound,
    TaskNotFoundError,
)



class SurfaceAuthenticationError(PermissionError):
    """The local bearer token was missing or did not match."""


def _surface_error_status(exc: BaseException) -> int:
    if isinstance(exc, SurfaceAuthenticationError):
        return 401
    if isinstance(exc, (SurfaceScopeError, PermissionError)):
        return 403
    if isinstance(exc, (SurfaceSessionNotFound, TaskNotFoundError)):
        return 404
    if isinstance(
        exc,
        (
            SurfaceSequenceConflict,
            SurfaceIdempotencyConflict,
            InvalidTransitionError,
        ),
    ):
        return 409
    if isinstance(exc, (SurfaceProtocolError, ValidationError, ValueError)):
        return 422
    return 503


def _match_surface_session_leaf(path: str, leaf: str) -> str | None:
    parsed = urlparse(path)
    if parsed.query or parsed.fragment or parsed.path.endswith("/"):
        return None
    parts = parsed.path.split("/")
    leaf_parts = leaf.split("/") if leaf else []
    if (
        len(parts) == 5 + len(leaf_parts)
        and parts[:4] == ["", "v1", "surface", "sessions"]
        and parts[5:] == leaf_parts
    ):
        value = parts[4]
        if value and "/" not in value and "\\" not in value:
            return value
    return None


def _match_surface_task_events(path: str) -> str | None:
    parsed = urlparse(path)
    if parsed.fragment:
        return None
    parts = parsed.path.split("/")
    if not (
        len(parts) == 6
        and parts[:4] == ["", "v1", "surface", "tasks"]
        and parts[5] == "events"
    ):
        return None
    value = parts[4]
    if value and "/" not in value and "\\" not in value:
        return value
    return None


def _match_surface_task_overview(path: str) -> str | None:
    parsed = urlparse(path)
    if parsed.fragment:
        return None
    parts = parsed.path.split("/")
    if not (
        len(parts) == 6
        and parts[:4] == ["", "v1", "surface", "tasks"]
        and parts[5] == "overview"
    ):
        return None
    value = parts[4]
    if value and "/" not in value and "\\" not in value:
        return value
    return None


def _match_surface_task_files(path: str) -> str | None:
    parsed = urlparse(path)
    if parsed.fragment:
        return None
    parts = parsed.path.split("/")
    if not (
        len(parts) == 6
        and parts[:4] == ["", "v1", "surface", "tasks"]
        and parts[5] == "files"
    ):
        return None
    value = parts[4]
    if value and "/" not in value and "\\" not in value:
        return value
    return None


class SurfaceRoutes:
    """Authenticated route parsing and response mapping for Surface commands."""

    def __init__(self, runtime: SurfaceRuntime, bearer_token: str) -> None:
        self._runtime = runtime
        self._bearer_token = bearer_token

    def authenticate(self, authorization: str | None) -> None:
        supplied = (
            ""
            if authorization is None
            else authorization.removeprefix("Bearer ")
        )
        if not secrets.compare_digest(supplied, self._bearer_token):
            raise SurfaceAuthenticationError(
                "local runtime authentication failed"
            )

    def dispatch(self, handler: Any) -> None:
        try:
            self.authenticate(handler.headers.get("Authorization"))
        except SurfaceAuthenticationError:
            handler._json(401, {"error": "local_authentication_failed"})
            return
        parsed = urlparse(handler.path)
        method = handler.command
        try:
            if method == "POST" and parsed.path == "/v1/surface/sessions":
                self._post_open_session(handler)
                return
            if method == "GET":
                session_id = _match_surface_session_leaf(handler.path, "")
                if session_id is not None:
                    self._get_session(handler, session_id)
                    return
                task_id = _match_surface_task_events(handler.path)
                if task_id is not None:
                    self._get_events(handler, task_id)
                    return
                task_id = _match_surface_task_files(handler.path)
                if task_id is not None:
                    self._get_files(handler, task_id)
                    return
                task_id = _match_surface_task_overview(handler.path)
                if task_id is not None:
                    self._get_overview(handler, task_id)
                    return
            if method == "POST":
                session_id = _match_surface_session_leaf(
                    handler.path, "turns"
                )
                if session_id is not None:
                    self._post_turn(handler, session_id)
                    return
                session_id = _match_surface_session_leaf(
                    handler.path, "approvals"
                )
                if session_id is not None:
                    self._post_approval(handler, session_id)
                    return
                session_id = _match_surface_session_leaf(
                    handler.path, "pause"
                )
                if session_id is not None:
                    self._post_pause(handler, session_id)
                    return
                session_id = _match_surface_session_leaf(
                    handler.path, "resume"
                )
                if session_id is not None:
                    self._post_resume(handler, session_id)
                    return
                session_id = _match_surface_session_leaf(
                    handler.path, "correction"
                )
                if session_id is not None:
                    self._post_correction(handler, session_id)
                    return
            handler._json(404, {"error": "surface_route_not_found"})
        except Exception as exc:
            handler._json(
                _surface_error_status(exc),
                {"error": type(exc).__name__, "message": str(exc)},
            )

    def _post_open_session(self, handler: Any) -> None:
        body = handler._body()
        command = SurfaceOpenSessionCommand.model_validate(body)
        self._require_protocol_header(handler)
        handler._json(200, {"snapshot": self._runtime.open_session(command).model_dump(mode="json")})

    def _get_session(self, handler: Any, session_id: str) -> None:
        handler._json(200, self._runtime.get_session(session_id).model_dump(mode="json"))

    def _post_turn(self, handler: Any, session_id: str) -> None:
        body = handler._body()
        command = SurfaceTurnCommand.model_validate(body)
        if command.session_id != session_id:
            raise SurfaceProtocolError(
                "surface command session does not bind the route"
            )
        self._require_protocol_header(handler)
        handler._json(200, {"turn": self._runtime.run_turn(command).model_dump(mode="json")})

    def _post_approval(self, handler: Any, session_id: str) -> None:
        body = handler._body()
        command = SurfaceApprovalCommand.model_validate(body)
        if command.session_id != session_id:
            raise SurfaceProtocolError(
                "surface command session does not bind the route"
            )
        self._require_protocol_header(handler)
        handler._json(200, {"turn": self._runtime.decide_approval(command).model_dump(mode="json")})

    def _post_pause(self, handler: Any, session_id: str) -> None:
        body = handler._body()
        command = SurfaceCorrectionCommand.model_validate(body)
        if command.session_id != session_id:
            raise SurfaceProtocolError(
                "surface command session does not bind the route"
            )
        self._require_protocol_header(handler)
        handler._json(200, {"snapshot": self._runtime.pause(command).model_dump(mode="json")})

    def _post_resume(self, handler: Any, session_id: str) -> None:
        body = handler._body()
        command = SurfaceCorrectionCommand.model_validate(body)
        if command.session_id != session_id:
            raise SurfaceProtocolError(
                "surface command session does not bind the route"
            )
        self._require_protocol_header(handler)
        handler._json(200, {"snapshot": self._runtime.resume(command).model_dump(mode="json")})

    def _post_correction(self, handler: Any, session_id: str) -> None:
        body = handler._body()
        command = SurfaceCorrectionCommand.model_validate(body)
        if command.session_id != session_id:
            raise SurfaceProtocolError(
                "surface command session does not bind the route"
            )
        self._require_protocol_header(handler)
        handler._json(200, {"snapshot": self._runtime.correct(command).model_dump(mode="json")})

    def _get_overview(self, handler: Any, task_id: str) -> None:
        handler._json(
            200,
            {"overview": self._runtime._application.surface_task_overview(task_id)},
        )

    def _get_files(self, handler: Any, task_id: str) -> None:
        handler._json(
            200,
            {"files": self._runtime._application.surface_files_listing(task_id)},
        )

    def _get_events(self, handler: Any, task_id: str) -> None:
        parsed = urlparse(handler.path)
        query: dict[str, list[str]] = {}
        for raw in parsed.query.split("&"):
            if not raw:
                continue
            name, separator, value = raw.partition("=")
            query.setdefault(name, []).append(value)
        after_values = query.get("after", [])
        if len(after_values) > 1:
            raise ValueError("after must be provided at most once")
        wait_values = query.get("wait_ms", ["0"])
        if len(wait_values) != 1:
            raise ValueError("wait_ms must be provided exactly once")
        try:
            wait_ms = int(wait_values[0])
        except ValueError as exc:
            raise ValueError("wait_ms must be an integer") from exc
        if isinstance(wait_ms, bool) or not 0 <= wait_ms <= 25000:
            raise ValueError("wait_ms must be within 0..25000")

        last_event_id = handler.headers.get("Last-Event-ID")
        after_sequence = 0
        if last_event_id is not None:
            try:
                last_sequence = int(last_event_id)
            except ValueError as exc:
                raise ValueError(
                    "Last-Event-ID must be an integer sequence"
                ) from exc
            if after_values:
                try:
                    query_after = int(after_values[0])
                except ValueError as exc:
                    raise ValueError("after must be an integer sequence") from exc
                if query_after != last_sequence:
                    raise ValueError(
                        "Last-Event-ID and after disagree on the cursor"
                    )
            after_sequence = last_sequence
        elif after_values:
            try:
                after_sequence = int(after_values[0])
            except ValueError as exc:
                raise ValueError("after must be an integer sequence") from exc

        batch = self._wait_for_events(task_id, after_sequence, wait_ms)
        self._write_sse(handler, batch, after_sequence)

    def _wait_for_events(self, task_id: str, after_sequence: int, wait_ms: int) -> Any:
        deadline = time.monotonic() + wait_ms / 1000.0
        batch = self._runtime.event_batch(task_id, after_sequence)
        while not batch.events and time.monotonic() < deadline:
            time.sleep(0.05)
            batch = self._runtime.event_batch(task_id, after_sequence)
        return batch

    def _write_sse(self, handler: Any, batch: Any, after_sequence: int) -> None:
        payload: list[str] = []
        for event in batch.events:
            payload.append(f"id: {event.sequence}\n")
            payload.append(f"event: {event.event_type.value}\n")
            payload.append(f"data: {canonical_json(event.model_dump(mode='json'))}\n\n")
        cursor = {"next_sequence": batch.next_sequence}
        payload.append("event: cursor\n")
        payload.append(
            f"data: {canonical_json(cursor)}\n\n"
        )
        body = "".join(payload).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        for name, value in _tauri_origin_cors(
            handler.headers.get("Origin")
        ).items():
            handler.send_header(name, value)
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Accel-Buffering", "no")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _require_protocol_header(self, handler: Any) -> None:
        supplied = handler.headers.get("X-Agent-OS-Protocol")
        if supplied is None:
            raise SurfaceProtocolError(
                "X-Agent-OS-Protocol header is required for state changes"
            )
        if supplied != SURFACE_PROTOCOL_VERSION:
            raise SurfaceProtocolError(
                f"unsupported X-Agent-OS-Protocol {supplied}"
            )
