"""E1 transient stream HTTP/SSE routes + SurfaceClient consumer (M2, test-first).

Frozen source: GC §E1 — subscription-before-execution; begin-turn binds the
pre-subscribed {runtime_boot_id, stream_id}; the transient stream endpoint is
a bounded SSE batch with cursor resume; a stale generation or unknown stream
fails typed 410 (SurfaceStreamGone), never silent holes. CHUNK/STREAM_END
frames are transient display truth; durable truth stays the Task event stream.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Generator

import pytest

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    SurfaceBeginTurnCommand,
    SurfaceClientRef,
    SurfaceOpenSessionCommand,
    SurfaceStreamFrame,
    SurfaceStreamFrameKind,
)
from agent_os_core import DeterministicProvider

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler
from apps.api_server.surface_routes import SurfaceRoutes
from apps.cli.surface_client import (
    SurfaceClient,
    SurfaceStreamStaleError,
)
from apps.runtime_daemon.descriptor import RuntimeDescriptor


def _client(app: AgentOSApplication) -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="client:stream-http:1",
        client_type="TEST",
        principal_id=app.principal.principal_id,
        tenant_id=app.principal.tenant_id,
        workspace_id=app.principal.workspace_id,
        device_id="device:stream-http:1",
    )


class StreamTestServer:
    def __init__(
        self,
        app: AgentOSApplication,
        base: str,
        token: str,
        server: ThreadingHTTPServer,
    ) -> None:
        self.app = app
        self.base = base
        self.token = token
        self.server = server

    def request(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        method: str = "GET",
        body: bytes | dict | None = None,
    ) -> urllib.request.Request:
        return urllib.request.Request(
            self.base + path,
            data=(
                body
                if isinstance(body, bytes)
                else (json.dumps(body).encode() if body is not None else None)
            ),
            method=method,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
                "X-Agent-OS-Protocol": SURFACE_PROTOCOL_VERSION,
                **dict(headers or {}),
            },
        )

    def json(self, path: str, **kwargs) -> tuple[int, dict]:
        request = self.request(path, **kwargs)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def sse(self, path: str, **kwargs) -> tuple[int, str]:
        request = self.request(path, **kwargs)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    def open_session(self) -> tuple[str, int]:
        command = SurfaceOpenSessionCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_client(self.app),
            statement="stream http session",
            idempotency_key="idem:stream-http:open:1",
            requested_at=datetime.now(timezone.utc),
        )
        status, payload = self.json(
            "/v1/surface/sessions", method="POST", body=command.model_dump(mode="json")
        )
        assert status == 200, payload
        snapshot = payload["snapshot"]
        return snapshot["session"]["session_id"], snapshot["event_sequence"]

    def subscribe(self, session_id: str) -> tuple[str, str]:
        status, payload = self.json(
            f"/v1/surface/sessions/{session_id}/streams", method="POST", body={}
        )
        assert status == 200, payload
        subscription = payload["subscription"]
        return subscription["runtime_boot_id"], subscription["stream_id"]

    def begin_turn(
        self,
        session_id: str,
        sequence: int,
        runtime_boot_id: str,
        stream_id: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict]:
        command = SurfaceBeginTurnCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_client(self.app),
            session_id=session_id,
            text="stream this reply",
            stream={"runtime_boot_id": runtime_boot_id, "stream_id": stream_id},
            expected_event_sequence=sequence,
            idempotency_key=f"idem:stream-http:begin:{stream_id}",
            requested_at=datetime.now(timezone.utc),
        )
        return self.json(
            f"/v1/surface/sessions/{session_id}/begin-turn",
            method="POST",
            body=command.model_dump(mode="json"),
            headers=headers,
        )


@pytest.fixture
def stream_server(tmp_path: Path) -> Generator[StreamTestServer, None, None]:
    app = AgentOSApplication(
        database=tmp_path / "surface-stream-http.sqlite3",
        workspace=tmp_path,
    )
    app.provider = DeterministicProvider(
        scripted=(("streamed over http", ()),),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    token = "test-local-token"
    handler = type(
        "TestStreamHandler",
        (Handler,),
        {
            "application": app,
            "local_token": token,
            "surface_routes": SurfaceRoutes(app.surface, token),
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield StreamTestServer(app, base, token, server)
    finally:
        server.shutdown()
        server.server_close()


def _descriptor(port: int, token: str, tmp_path: Path) -> RuntimeDescriptor:
    return RuntimeDescriptor(
        protocol_version="1.1",
        pid=1234,
        boot_id="boot:stream-http:1",
        host="127.0.0.1",
        port=port,
        bearer_token=token,
        database_path=str(tmp_path / "agent-os.sqlite3"),
        workspace_path=str(tmp_path / "workspace"),
        created_at=datetime.now(timezone.utc),
    )


def _wait_stream_end(
    server: StreamTestServer,
    session_id: str,
    stream_id: str,
    after: int = 0,
    attempts: int = 50,
) -> list[SurfaceStreamFrame]:
    frames: list[SurfaceStreamFrame] = []
    cursor = after
    for _ in range(attempts):
        status, body = server.sse(
            f"/v1/surface/sessions/{session_id}/stream"
            f"?stream_id={stream_id}&after={cursor}&wait_ms=200"
        )
        assert status == 200, body
        batch_frames, next_sequence = _decode_frame_sse(body)
        frames.extend(batch_frames)
        cursor = next_sequence
        if any(frame.kind is SurfaceStreamFrameKind.STREAM_END for frame in frames):
            return frames
    raise AssertionError(f"STREAM_END never arrived; frames={frames!r}")


def _decode_frame_sse(body: str) -> tuple[list[SurfaceStreamFrame], int]:
    frames: list[SurfaceStreamFrame] = []
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
                frames.append(
                    SurfaceStreamFrame.model_validate(json.loads("\n".join(data_lines)))
                )
            current_event = None
            data_lines = []
    return frames, next_sequence


def test_subscribe_returns_boot_bound_stream_identity(
    stream_server: StreamTestServer,
) -> None:
    session_id, _ = stream_server.open_session()
    boot_id, stream_id = stream_server.subscribe(session_id)
    assert boot_id == stream_server.app.runtime_boot_id
    assert stream_id


def test_begin_turn_requires_protocol_header(
    stream_server: StreamTestServer,
) -> None:
    session_id, sequence = stream_server.open_session()
    boot_id, stream_id = stream_server.subscribe(session_id)
    status, payload = stream_server.begin_turn(
        session_id,
        sequence,
        boot_id,
        stream_id,
        headers={"X-Agent-OS-Protocol": ""},
    )
    assert status == 422
    assert "error" in payload


def test_stream_sse_delivers_chunk_frames_and_stream_end(
    stream_server: StreamTestServer,
) -> None:
    session_id, sequence = stream_server.open_session()
    boot_id, stream_id = stream_server.subscribe(session_id)
    status, payload = stream_server.begin_turn(session_id, sequence, boot_id, stream_id)
    assert status == 200, payload
    turn_id = payload["begin_turn"]["turn_id"]
    assert payload["begin_turn"]["stream_id"] == stream_id

    frames = _wait_stream_end(stream_server, session_id, stream_id)
    kinds = [frame.kind for frame in frames]
    assert SurfaceStreamFrameKind.CHUNK in kinds
    assert kinds[-1] is SurfaceStreamFrameKind.STREAM_END
    deltas = "".join(
        str(frame.payload.get("delta", ""))
        for frame in frames
        if frame.kind is SurfaceStreamFrameKind.CHUNK
    )
    assert deltas == "streamed over http"
    for frame in frames:
        assert frame.runtime_boot_id == boot_id
        assert frame.stream_id == stream_id
        if frame.kind is not SurfaceStreamFrameKind.GAP:
            assert frame.turn_id == turn_id
    sequences = [frame.frame_sequence for frame in frames]
    assert sequences == sorted(sequences)


def test_stream_resume_via_last_event_id_yields_no_duplicates(
    stream_server: StreamTestServer,
) -> None:
    session_id, sequence = stream_server.open_session()
    boot_id, stream_id = stream_server.subscribe(session_id)
    stream_server.begin_turn(session_id, sequence, boot_id, stream_id)

    first_status, first_body = stream_server.sse(
        f"/v1/surface/sessions/{session_id}/stream"
        f"?stream_id={stream_id}&after=0&wait_ms=200"
    )
    assert first_status == 200
    first_frames, next_sequence = _decode_frame_sse(first_body)
    assert first_frames

    resumed_status, resumed_body = stream_server.sse(
        f"/v1/surface/sessions/{session_id}/stream?stream_id={stream_id}&wait_ms=0",
        headers={"Last-Event-ID": str(next_sequence)},
    )
    assert resumed_status == 200
    resumed_frames, _ = _decode_frame_sse(resumed_body)
    resumed_ids = {frame.frame_sequence for frame in resumed_frames}
    assert all(frame.frame_sequence not in resumed_ids for frame in first_frames)


def test_stream_unknown_stream_fails_typed_410(
    stream_server: StreamTestServer,
) -> None:
    session_id, _ = stream_server.open_session()
    status, payload = stream_server.json(
        f"/v1/surface/sessions/{session_id}/stream"
        "?stream_id=not-a-live-stream&wait_ms=0"
    )
    assert status == 410
    assert payload["error"] == "SurfaceStreamGone"


def test_surface_client_consumes_stream_end_to_end(
    stream_server: StreamTestServer, tmp_path: Path
) -> None:
    session_id, sequence = stream_server.open_session()
    descriptor = _descriptor(
        stream_server.server.server_address[1], stream_server.token, tmp_path
    )
    client = SurfaceClient(descriptor)

    subscription = client.subscribe_stream(session_id)
    assert subscription.runtime_boot_id == stream_server.app.runtime_boot_id

    begin_response = client.begin_turn(
        SurfaceBeginTurnCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=SurfaceClientRef(
                client_id="client:stream-http:1",
                client_type="TEST",
                principal_id=stream_server.app.principal.principal_id,
                tenant_id=stream_server.app.principal.tenant_id,
                workspace_id=stream_server.app.principal.workspace_id,
                device_id="device:stream-http:1",
            ),
            session_id=session_id,
            text="stream this reply",
            stream={
                "runtime_boot_id": subscription.runtime_boot_id,
                "stream_id": subscription.stream_id,
            },
            expected_event_sequence=sequence,
            idempotency_key=f"idem:stream-http:begin:{subscription.stream_id}",
            requested_at=datetime.now(timezone.utc),
        )
    )
    assert begin_response.stream_id == subscription.stream_id

    frames: list[Any] = []
    cursor = 0
    for _ in range(50):
        batch = client.stream_frames(
            session_id,
            stream_id=subscription.stream_id,
            runtime_boot_id=subscription.runtime_boot_id,
            after_sequence=cursor,
            wait_ms=200,
        )
        frames.extend(batch.frames)
        cursor = batch.next_sequence
        if any(frame.kind is SurfaceStreamFrameKind.STREAM_END for frame in frames):
            break
    else:
        raise AssertionError("STREAM_END never arrived via client")
    deltas = "".join(
        str(frame.payload.get("delta", ""))
        for frame in frames
        if frame.kind is SurfaceStreamFrameKind.CHUNK
    )
    assert deltas == "streamed over http"


def test_surface_client_maps_410_to_typed_stale_error(
    stream_server: StreamTestServer, tmp_path: Path
) -> None:
    session_id, _ = stream_server.open_session()
    descriptor = _descriptor(
        stream_server.server.server_address[1], stream_server.token, tmp_path
    )
    client = SurfaceClient(descriptor)
    with pytest.raises(SurfaceStreamStaleError):
        client.stream_frames(
            session_id,
            stream_id="dead-stream",
            runtime_boot_id=stream_server.app.runtime_boot_id,
        )
