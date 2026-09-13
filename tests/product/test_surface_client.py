from __future__ import annotations

import json
import socket
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Generator
from pathlib import Path

import pytest

from agent_os_contracts import (
    ApprovalDisposition,
    SurfaceSessionStatus,
)

from apps.cli.surface_client import (
    SurfaceClient,
    SurfaceClientAuthenticationError,
    SurfaceClientConnectionError,
    SurfaceHttpError,
    SurfaceProtocolMismatch,
)
from apps.runtime_daemon.descriptor import RuntimeDescriptor


def _descriptor(port: int, tmp_path: Path) -> RuntimeDescriptor:
    return RuntimeDescriptor(
        protocol_version="1.1",
        pid=1234,
        boot_id="boot:test:1",
        host="127.0.0.1",
        port=port,
        bearer_token="test-token",
        database_path=str(tmp_path / "agent-os.sqlite3"),
        workspace_path=str(tmp_path / "workspace"),
        created_at=datetime.now(timezone.utc),
    )


class FakeHttpServer:
    def __init__(self, tmp_path: Path) -> None:
        self._responses: list[tuple[int, bytes, str]] = []

        class Handler(BaseHTTPRequestHandler):
            pending_responses: list[tuple[int, bytes, str]] = self._responses

            def _serve(self) -> None:
                status, data, content_type = self.pending_responses.pop(0)
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                self._serve()

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                self._serve()

            def log_message(self, format: str, *args: object) -> None:
                return

        self.handler_class = Handler
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()
        self.descriptor = _descriptor(self.server.server_address[1], tmp_path)

    def respond_json(self, status: int, payload: dict) -> None:
        self._responses.append(
            (status, json.dumps(payload).encode(), "application/json")
        )

    def respond_sse(self, body: str) -> None:
        self._responses.append(
            (200, body.encode(), "text/event-stream")
        )

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake_http_server(tmp_path: Path) -> Generator[FakeHttpServer, None, None]:
    server = FakeHttpServer(tmp_path)
    yield server
    server.close()


def _snapshot_payload(session_id: str = "session:1", sequence: int = 1) -> dict:
    return {
        "protocol_version": "1.1",
        "session": {
            "schema_version": "1.0",
            "session_id": session_id,
            "task_id": "task:1",
            "run_id": "run:1",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
        },
        "envelope_id": "envelope:1",
        "expected_outcome_id": "expected:1",
        "status": SurfaceSessionStatus.ACTIVE.value,
        "event_sequence": sequence,
        "message_count": 2,
        "pending_approval": None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _turn_payload(session_id: str = "session:1", sequence: int = 5) -> dict:
    return {
        "protocol_version": "1.1",
        "snapshot": _snapshot_payload(session_id, sequence),
        "turn_id": "turn:1",
        "text": "completed reply",
        "steps": [],
        "stop_reason": "completed",
        "total_tokens": 12,
    }


def test_client_rejects_response_protocol_mismatch(
    fake_http_server: FakeHttpServer,
) -> None:
    fake_http_server.respond_json(
        200, {"protocol_version": "2.0", "session": {}}
    )
    with pytest.raises(SurfaceProtocolMismatch):
        SurfaceClient(fake_http_server.descriptor).get_session("session:1")


def test_client_open_session_parses_snapshot(
    fake_http_server: FakeHttpServer,
) -> None:
    fake_http_server.respond_json(200, {"snapshot": _snapshot_payload()})
    client = SurfaceClient(fake_http_server.descriptor)

    snapshot = client.open_session("inspect the workspace")

    assert snapshot.session.session_id == "session:1"
    assert snapshot.status is SurfaceSessionStatus.ACTIVE


def test_client_run_turn_uses_tracked_sequence(
    fake_http_server: FakeHttpServer,
) -> None:
    fake_http_server.respond_json(200, {"snapshot": _snapshot_payload()})
    fake_http_server.respond_json(200, {"turn": _turn_payload()})
    client = SurfaceClient(fake_http_server.descriptor)

    snapshot = client.open_session("inspect")
    response = client.run_turn(snapshot.session.session_id, "inspect more")

    assert response.text == "completed reply"
    assert response.stop_reason == "completed"


def test_client_decide_approval_parses_resumed_turn(
    fake_http_server: FakeHttpServer,
) -> None:
    fake_http_server.respond_json(200, {"snapshot": _snapshot_payload()})
    fake_http_server.respond_json(200, {"turn": _turn_payload()})
    client = SurfaceClient(fake_http_server.descriptor)

    snapshot = client.open_session("edit")
    resumed = client.decide_approval(
        snapshot.session.session_id,
        action_digest="a" * 64,
        disposition=ApprovalDisposition.APPROVE,
        reason="reviewed exact edit",
    )

    assert resumed.stop_reason == "completed"


def test_client_http_error_maps_to_closed_exception(
    fake_http_server: FakeHttpServer,
) -> None:
    fake_http_server.respond_json(
        401, {"error": "local_authentication_failed"}
    )
    client = SurfaceClient(fake_http_server.descriptor)

    with pytest.raises(SurfaceClientAuthenticationError) as excinfo:
        client.get_session("session:1")
    assert "test-token" not in str(excinfo.value)
    assert "Bearer" not in str(excinfo.value)


def test_client_sequence_conflict_maps_to_http_error(
    fake_http_server: FakeHttpServer,
) -> None:
    fake_http_server.respond_json(
        409,
        {"error": "SurfaceSequenceConflict", "message": "stale sequence"},
    )
    client = SurfaceClient(fake_http_server.descriptor)

    with pytest.raises(SurfaceHttpError) as excinfo:
        client.get_session("session:1")
    assert excinfo.value.status_code == 409


def test_client_connection_error_is_closed(
    tmp_path: Path,
) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    descriptor = _descriptor(port, tmp_path)
    client = SurfaceClient(descriptor)

    with pytest.raises(SurfaceClientConnectionError) as excinfo:
        client.get_session("session:1")
    assert "test-token" not in str(excinfo.value)


def test_client_events_parses_resumable_sse(
    fake_http_server: FakeHttpServer,
) -> None:
    event_one = json.dumps(
        {
            "schema_version": "1.0",
            "event_id": "event:1",
            "task_id": "task:1",
            "sequence": 3,
            "event_type": "SESSION_MESSAGE_RECORDED",
            "correlation_id": "run:1",
            "payload_json": "{}",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    body = (
        "id: 3\n"
        f"event: SESSION_MESSAGE_RECORDED\n"
        f"data: {event_one}\n\n"
        "event: cursor\n"
        'data: {"next_sequence": 3}\n\n'
    )
    fake_http_server.respond_sse(body)
    client = SurfaceClient(fake_http_server.descriptor)

    batch = client.events("task:1", after_sequence=2, wait_ms=0)

    assert batch.task_id == "task:1"
    assert batch.next_sequence == 3
    assert len(batch.events) == 1
    assert batch.events[0].sequence == 3


def test_descriptor_rejects_invalid_port(tmp_path: Path) -> None:
    with pytest.raises(Exception):
        _descriptor(0, tmp_path)
    with pytest.raises(Exception):
        _descriptor(65536, tmp_path)


def test_client_scope_error_is_closed_exception(
    fake_http_server: FakeHttpServer,
) -> None:
    fake_http_server.respond_json(403, {"error": "SurfaceScopeError"})
    client = SurfaceClient(fake_http_server.descriptor)

    with pytest.raises(SurfaceHttpError) as excinfo:
        client.get_session("session:1")
    assert excinfo.value.status_code == 403
