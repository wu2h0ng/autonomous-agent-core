"""The SSE response bodies are projected too (protocol 1.2, second half).

``_respond`` projects JSON bodies, but the stream and event endpoints build their
own body and write it straight to the socket. A response path that skips the
projection is a leak path for the next additive field, so those two writers
project through ``_sse_data`` as well.

What projecting a frame means, and why it is safe here:

* it is the same operation as for a JSON body — the fields the additive registry
  declares above the negotiated minor are removed from the serialized frame;
* frames and events carry no ``protocol_version`` of their own (the batch
  envelope does, and the envelope is not what goes on the wire), so nothing
  inside a frame is relabelled;
* both writers emit one fully-buffered body with ``Content-Length`` and a single
  ``wfile.write``, so no bytes reach the socket before the whole batch is
  projected. There is no per-chunk hook that could half-apply.

These tests are behavioral rather than syntactic on purpose: a real hermetic turn
is streamed over real HTTP at each declared minor, and the assertion is on which
KEYS are on the wire.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import MappingProxyType
from typing import Any, Generator

import pytest

from agent_os_contracts import (
    SurfaceBeginTurnCommand,
    SurfaceProtocolVersion,
    SurfaceStreamBinding,
)
from agent_os_core import DeterministicProvider

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler
from apps.api_server.surface_routes import SurfaceRoutes

NOW = datetime(2026, 9, 18, tzinfo=timezone.utc)
TOKEN = "test-local-token"


class _Reader:
    """A reader that can only send a raw protocol header, and reads SSE raw."""

    def __init__(self, base: str) -> None:
        self.base = base

    def get(self, path: str, *, protocol: str | None) -> tuple[int, dict]:
        status, raw = self._raw("GET", path, protocol=protocol)
        return status, json.loads(raw)

    def post(self, path: str, body: dict, *, protocol: str | None) -> tuple[int, dict]:
        status, raw = self._raw("POST", path, protocol=protocol, body=body)
        return status, json.loads(raw)

    def sse(self, path: str, *, protocol: str | None) -> tuple[int, str]:
        status, raw = self._raw("GET", path, protocol=protocol)
        return status, raw.decode("utf-8")

    def sse_headers(self, path: str, *, protocol: str | None) -> tuple[int, dict, str]:
        """Status, response headers and body, for the framing the writer declares."""

        headers = {"Authorization": f"Bearer {TOKEN}"}
        if protocol is not None:
            headers["X-Agent-OS-Protocol"] = protocol
        request = urllib.request.Request(self.base + path, method="GET", headers=headers)
        try:
            with urllib.request.urlopen(request) as response:
                body = response.read().decode("utf-8")
                return response.status, dict(response.headers), body
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read().decode("utf-8")

    def _raw(
        self,
        method: str,
        path: str,
        *,
        protocol: str | None,
        body: dict | None = None,
    ) -> tuple[int, bytes]:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if protocol is not None:
            headers["X-Agent-OS-Protocol"] = protocol
        request = urllib.request.Request(
            self.base + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()


@pytest.fixture
def sse_server(tmp_path: Path) -> Generator[tuple[AgentOSApplication, _Reader], None, None]:
    """A real HTTP Surface server that can stream a hermetic turn per session."""

    app = AgentOSApplication(
        database=tmp_path / "surface-protocol-1-2-sse.sqlite3", workspace=tmp_path
    )
    app.provider = DeterministicProvider(
        text="streamed deltas",
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    handler = type(
        "TestSseProtocolHandler",
        (Handler,),
        {
            "application": app,
            "local_token": TOKEN,
            "surface_routes": SurfaceRoutes(app.surface, TOKEN),
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield app, _Reader(f"http://127.0.0.1:{server.server_address[1]}")
    finally:
        server.shutdown()
        server.server_close()


def _additive(monkeypatch: pytest.MonkeyPatch, registry: dict[str, tuple[str, ...]]) -> None:
    """Re-register the additive minors inside one test.

    The production registry is asserted in ``test_surface_protocol_1_2``; what is
    under test here is whether the SSE writers apply the projection AT ALL. A
    real CHUNK key (``delta``) and a real event field (``occurred_at``) registered
    as added 1.2 fields are what make that observable on the real streaming
    fixture, instead of asserting on the syntax of the writers.
    """

    from agent_os_contracts import surface as surface_contract

    monkeypatch.setattr(
        surface_contract,
        "SURFACE_PROTOCOL_ADDITIVE_MINORS",
        MappingProxyType(registry),
    )


def _sse_objects(body: str) -> tuple[list[dict[str, Any]], int]:
    """Every non-cursor ``data:`` object in one SSE body, plus its next cursor.

    Raw dicts on purpose: the question is which KEYS are on the wire, so this
    must not be normalized through a contract model.
    """

    objects: list[dict[str, Any]] = []
    next_sequence = 0
    current_event: str | None = None
    data_lines: list[str] = []
    for line in body.splitlines():
        if line.startswith("event: "):
            current_event = line[7:]
        elif line.startswith("data: "):
            data_lines.append(line[6:])
        elif line == "":
            if current_event == "cursor":
                next_sequence = json.loads("\n".join(data_lines))["next_sequence"]
            elif current_event is not None and data_lines:
                objects.append(json.loads("\n".join(data_lines)))
            current_event = None
            data_lines = []
    return objects, next_sequence


def _stream_one_turn(
    app: AgentOSApplication, reader: _Reader, *, version: SurfaceProtocolVersion, key: str
) -> dict[str, Any]:
    """Drive one real streaming turn at ``version``; return its task and frames."""

    status, opened = reader.post(
        "/v1/surface/sessions", _open_command(app, key, version=version), protocol=version
    )
    assert status == 200, opened
    session_id = opened["snapshot"]["session"]["session_id"]
    sequence = opened["snapshot"]["event_sequence"]

    status, subscribed = reader.post(
        f"/v1/surface/sessions/{session_id}/streams", {}, protocol=version
    )
    assert status == 200, subscribed
    subscription = subscribed["subscription"]

    command = SurfaceBeginTurnCommand(
        protocol_version=version,
        client=_open_command(app, f"{key}:client", version=version)["client"],
        session_id=session_id,
        text="stream this reply",
        stream=SurfaceStreamBinding(
            runtime_boot_id=subscription["runtime_boot_id"],
            stream_id=subscription["stream_id"],
        ),
        expected_event_sequence=sequence,
        idempotency_key=f"{key}:begin",
        requested_at=NOW,
    )
    status, begun = reader.post(
        f"/v1/surface/sessions/{session_id}/begin-turn",
        command.model_dump(mode="json"),
        protocol=version,
    )
    assert status == 200, begun

    frames: list[dict[str, Any]] = []
    cursor = 0
    for _ in range(50):
        status, body = reader.sse(
            f"/v1/surface/sessions/{session_id}/stream"
            f"?stream_id={subscription['stream_id']}&after={cursor}&wait_ms=200",
            protocol=version,
        )
        assert status == 200, body
        batch, cursor = _sse_objects(body)
        frames.extend(batch)
        if any(frame.get("kind") == "STREAM_END" for frame in frames):
            return {
                "session_id": session_id,
                "stream_id": subscription["stream_id"],
                "task_id": opened["snapshot"]["session"]["task_id"],
                "frames": frames,
            }
    raise AssertionError(f"STREAM_END never arrived; frames={frames!r}")


def _open_command(app: AgentOSApplication, key: str, *, version: str) -> dict:
    return {
        "protocol_version": version,
        "client": {
            "client_id": "client:protocol-1-2-sse:1",
            "client_type": "TEST",
            "principal_id": app.principal.principal_id,
            "tenant_id": app.principal.tenant_id,
            "workspace_id": app.principal.workspace_id,
            "device_id": "device:protocol-1-2-sse:1",
        },
        "statement": "sse projection probe",
        "idempotency_key": key,
        "requested_at": "2026-09-18T00:00:00+00:00",
    }


def _chunk_payloads(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payloads = [frame["payload"] for frame in frames if frame.get("kind") == "CHUNK"]
    assert payloads, "no CHUNK frame was streamed"
    return payloads


def test_stream_frames_are_projected_at_the_negotiated_minor(
    sse_server: tuple[AgentOSApplication, _Reader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stream writer bypasses ``_respond``, so it must project on its own."""

    _additive(monkeypatch, {"1.2": ("awaiting_approval", "delta")})
    app, reader = sse_server

    old = _stream_one_turn(app, reader, version="1.1", key="idem:sse-projection:1-1")
    assert all("delta" not in payload for payload in _chunk_payloads(old["frames"]))

    new = _stream_one_turn(app, reader, version="1.2", key="idem:sse-projection:1-2")
    assert all("delta" in payload for payload in _chunk_payloads(new["frames"]))


def test_task_event_frames_are_projected_at_the_negotiated_minor(
    sse_server: tuple[AgentOSApplication, _Reader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The events writer is the other bypassing path, and it projects too."""

    _additive(monkeypatch, {"1.2": ("awaiting_approval", "occurred_at")})
    app, reader = sse_server
    turn = _stream_one_turn(app, reader, version="1.2", key="idem:sse-events:turn")
    task_id = turn["task_id"]

    def events_at(version: str) -> list[dict[str, Any]]:
        status, body = reader.sse(
            f"/v1/surface/tasks/{task_id}/events?wait_ms=0", protocol=version
        )
        assert status == 200, body
        objects, _ = _sse_objects(body)
        return objects

    at_1_1 = events_at("1.1")
    assert at_1_1, "the turn recorded no task events"
    assert all("occurred_at" not in event for event in at_1_1)

    at_1_2 = events_at("1.2")
    assert all("occurred_at" in event for event in at_1_2)


def test_stream_frames_keep_their_real_payload_under_the_1_1_projection(
    sse_server: tuple[AgentOSApplication, _Reader],
) -> None:
    """No over-removal: with the REAL registry a 1.1 reader still streams text.

    The projection removes registered additive fields and nothing else, so the
    production registry must leave every field a 1.1 reader already depended on
    exactly where it was.
    """

    app, reader = sse_server
    turn = _stream_one_turn(app, reader, version="1.1", key="idem:sse-real-registry")

    deltas = "".join(str(payload["delta"]) for payload in _chunk_payloads(turn["frames"]))
    assert deltas == "streamed deltas"


def test_stream_sse_body_is_fully_buffered_before_it_is_written(
    sse_server: tuple[AgentOSApplication, _Reader],
) -> None:
    """Why projecting a whole frame is safe: one buffered body, one write.

    The writer declares the full length up front and flushes the batch in a
    single ``wfile.write``, so no byte of a frame reaches the socket before that
    frame has been projected. If this framing ever became incremental, the
    projection would have to move with it — which is what this pins.
    """

    app, reader = sse_server
    turn = _stream_one_turn(app, reader, version="1.1", key="idem:sse-buffering")

    status, headers, body = reader.sse_headers(
        f"/v1/surface/sessions/{turn['session_id']}/stream"
        f"?stream_id={turn['stream_id']}&after=0&wait_ms=0",
        protocol="1.1",
    )
    assert status == 200, body
    assert headers.get("Content-Type") == "text/event-stream"
    assert int(headers["Content-Length"]) == len(body.encode("utf-8"))


def test_protocol_version_is_never_relabelled_inside_a_frame(
    sse_server: tuple[AgentOSApplication, _Reader], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The frame bodies carry no version to disagree with, and stay that way."""

    _additive(monkeypatch, {"1.2": ("awaiting_approval",)})
    app, reader = sse_server
    turn = _stream_one_turn(app, reader, version="1.1", key="idem:sse-no-version")

    assert all("protocol_version" not in frame for frame in turn["frames"])


def test_unknown_protocol_header_still_fails_typed_on_the_sse_routes(
    sse_server: tuple[AgentOSApplication, _Reader],
) -> None:
    """Negotiation on the SSE routes is not softer than on the JSON routes."""

    _, reader = sse_server
    status, payload = reader.get(
        "/v1/surface/tasks/task:missing/events?wait_ms=0", protocol="1.3"
    )
    assert status == 422
    assert payload["error"] == "SurfaceProtocolError"
