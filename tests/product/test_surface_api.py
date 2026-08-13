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
    SurfaceClientRef,
    SurfaceCorrectionCommand,
    SurfaceOpenSessionCommand,
    SurfaceTurnCommand,
)
from agent_os_core import DeterministicProvider

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler
from apps.api_server.surface_routes import SurfaceRoutes


def _client(app: AgentOSApplication) -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="client:api:1",
        client_type="TEST",
        principal_id=app.principal.principal_id,
        tenant_id=app.principal.tenant_id,
        workspace_id=app.principal.workspace_id,
        device_id="device:api:1",
    )


def _open_command(app: AgentOSApplication) -> dict:
    return SurfaceOpenSessionCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=_client(app),
        statement="inspect the workspace",
        idempotency_key="idem:api:open:1",
        requested_at=datetime.now(timezone.utc),
    ).model_dump(mode="json")


def _turn_command(
    app: AgentOSApplication,
    session_id: str,
    sequence: int,
    *,
    idempotency_key: str = "idem:api:turn:1",
) -> dict:
    return SurfaceTurnCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=_client(app),
        session_id=session_id,
        text="inspect the fixture",
        expected_event_sequence=sequence,
        idempotency_key=idempotency_key,
        requested_at=datetime.now(timezone.utc),
    ).model_dump(mode="json")


def _correction_command(
    app: AgentOSApplication,
    session_id: str,
    sequence: int,
    *,
    idempotency_key: str,
    reason: str,
) -> dict:
    return SurfaceCorrectionCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=_client(app),
        session_id=session_id,
        reason=reason,
        expected_event_sequence=sequence,
        idempotency_key=idempotency_key,
        requested_at=datetime.now(timezone.utc),
    ).model_dump(mode="json")


class SurfaceTestServer:
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
        authenticated: bool = True,
    ) -> urllib.request.Request:
        request = urllib.request.Request(
            self.base + path,
            data=(
                body
                if isinstance(body, bytes)
                else (
                    json.dumps(body).encode()
                    if body is not None
                    else None
                )
            ),
            method=method,
            headers={
                "Content-Type": "application/json",
                "Authorization": (
                    f"Bearer {self.token}" if authenticated else "Bearer wrong"
                ),
                "X-Agent-OS-Protocol": SURFACE_PROTOCOL_VERSION,
                **dict(headers or {}),
            },
        )
        return request

    def open(
        self,
        request: urllib.request.Request,
    ) -> Any:
        return urllib.request.urlopen(request)

    def json(self, path: str, **kwargs) -> tuple[int, dict]:
        request = self.request(path, **kwargs)
        try:
            with urllib.request.urlopen(request) as response:
                status = response.status
                value = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            status = exc.code
            value = json.loads(exc.read())
        assert isinstance(value, dict)
        return status, value

    def seed_three_events(self) -> tuple[str, int]:
        status, opened = self.json(
            "/v1/surface/sessions",
            method="POST",
            body=_open_command(self.app),
        )
        assert status == 200
        snapshot = opened["snapshot"] if "snapshot" in opened else opened
        session_id = snapshot["session"]["session_id"]
        task_id = snapshot["session"]["task_id"]
        status, _ = self.json(
            f"/v1/surface/sessions/{session_id}/turns",
            method="POST",
            body=_turn_command(
                self.app,
                session_id,
                snapshot["event_sequence"],
                idempotency_key="idem:api:seed:1",
            ),
        )
        assert status == 200
        request = self.request(
            f"/v1/surface/tasks/{task_id}/events?wait_ms=0",
            method="GET",
        )
        body = self.open(request).read().decode()
        sequences = [
            int(line.removeprefix("id: "))
            for line in body.splitlines()
            if line.startswith("id: ")
        ]
        last_sequence = sequences[-1]
        return task_id, last_sequence


@pytest.fixture
def surface_server(tmp_path: Path) -> Generator[SurfaceTestServer, None, None]:
    app = AgentOSApplication(
        database=tmp_path / "surface-api.sqlite3",
        workspace=tmp_path,
    )
    app.provider = DeterministicProvider(
        scripted=(("surface api reply", ()),),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    token = "test-local-token"
    handler = type(
        "TestSurfaceHandler",
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
        yield SurfaceTestServer(app, base, token, server)
    finally:
        server.shutdown()
        server.server_close()


def test_daemon_mode_rejects_missing_token_before_body_parse(
    surface_server: SurfaceTestServer,
) -> None:
    request = urllib.request.Request(
        surface_server.base + "/v1/surface/sessions",
        data=b"not-json",
        method="POST",
        headers={"X-Agent-OS-Protocol": SURFACE_PROTOCOL_VERSION},
    )
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request)
    assert error.value.code == 401


def test_events_resume_after_last_event_id(
    surface_server: SurfaceTestServer,
) -> None:
    task_id, last_sequence = surface_server.seed_three_events()
    request = surface_server.request(
        f"/v1/surface/tasks/{task_id}/events?wait_ms=0",
        headers={"Last-Event-ID": str(last_sequence - 1)},
    )
    body = surface_server.open(request).read().decode()
    assert f"id: {last_sequence}\n" in body
    assert f"id: {last_sequence - 1}\n" not in body


def test_wrong_token_rejected_before_body_parse(
    surface_server: SurfaceTestServer,
) -> None:
    request = surface_server.request(
        "/v1/surface/sessions",
        method="POST",
        body=b"not-json",
        authenticated=False,
    )
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request)
    assert error.value.code == 401


def test_wrong_protocol_version_rejected(
    surface_server: SurfaceTestServer,
) -> None:
    command = _open_command(surface_server.app)
    command["protocol_version"] = "2.0"
    status, body = surface_server.json(
        "/v1/surface/sessions",
        method="POST",
        body=command,
    )
    assert status == 422


def test_validation_error_returns_422(
    surface_server: SurfaceTestServer,
) -> None:
    status, body = surface_server.json(
        "/v1/surface/sessions",
        method="POST",
        body={"protocol_version": "1.0", "not_a_field": True},
    )
    assert status == 422


def test_open_and_turn_roundtrip(
    surface_server: SurfaceTestServer,
) -> None:
    status, opened = surface_server.json(
        "/v1/surface/sessions",
        method="POST",
        body=_open_command(surface_server.app),
    )
    assert status == 200
    snapshot = opened["snapshot"] if "snapshot" in opened else opened
    assert snapshot["status"] == "ACTIVE"
    session_id = snapshot["session"]["session_id"]

    status, response = surface_server.json(
        f"/v1/surface/sessions/{session_id}/turns",
        method="POST",
        body=_turn_command(
            surface_server.app,
            session_id,
            snapshot["event_sequence"],
        ),
    )
    assert status == 200
    turn = response["turn"] if "turn" in response else response
    assert turn["stop_reason"] == "completed"
    assert turn["text"] == "surface api reply"


def test_get_session_route(
    surface_server: SurfaceTestServer,
) -> None:
    status, opened = surface_server.json(
        "/v1/surface/sessions",
        method="POST",
        body=_open_command(surface_server.app),
    )
    snapshot = opened["snapshot"] if "snapshot" in opened else opened
    session_id = snapshot["session"]["session_id"]

    status, fetched = surface_server.json(
        f"/v1/surface/sessions/{session_id}",
        method="GET",
    )
    assert status == 200
    assert fetched["session"]["session_id"] == session_id


def test_stale_sequence_conflict_returns_409(
    surface_server: SurfaceTestServer,
) -> None:
    status, opened = surface_server.json(
        "/v1/surface/sessions",
        method="POST",
        body=_open_command(surface_server.app),
    )
    snapshot = opened["snapshot"] if "snapshot" in opened else opened
    session_id = snapshot["session"]["session_id"]
    stale = _turn_command(
        surface_server.app,
        session_id,
        snapshot["event_sequence"],
        idempotency_key="idem:api:stale:1",
    )
    surface_server.json(
        f"/v1/surface/sessions/{session_id}/turns",
        method="POST",
        body=_turn_command(
            surface_server.app,
            session_id,
            snapshot["event_sequence"],
            idempotency_key="idem:api:first:1",
        ),
    )
    status, body = surface_server.json(
        f"/v1/surface/sessions/{session_id}/turns",
        method="POST",
        body=stale,
    )
    assert status == 409


def test_idempotency_conflict_returns_409(
    surface_server: SurfaceTestServer,
) -> None:
    status, opened = surface_server.json(
        "/v1/surface/sessions",
        method="POST",
        body=_open_command(surface_server.app),
    )
    snapshot = opened["snapshot"] if "snapshot" in opened else opened
    session_id = snapshot["session"]["session_id"]
    first = _turn_command(
        surface_server.app,
        session_id,
        snapshot["event_sequence"],
        idempotency_key="idem:api:dup:1",
    )
    surface_server.json(
        f"/v1/surface/sessions/{session_id}/turns",
        method="POST",
        body=first,
    )
    mutated = dict(first)
    mutated["text"] = "a different request"
    status, body = surface_server.json(
        f"/v1/surface/sessions/{session_id}/turns",
        method="POST",
        body=mutated,
    )
    assert status == 409


def test_correction_route_halts_session(
    surface_server: SurfaceTestServer,
) -> None:
    status, opened = surface_server.json(
        "/v1/surface/sessions",
        method="POST",
        body=_open_command(surface_server.app),
    )
    snapshot = opened["snapshot"] if "snapshot" in opened else opened
    session_id = snapshot["session"]["session_id"]
    sequence = snapshot["event_sequence"]

    status, halted = surface_server.json(
        f"/v1/surface/sessions/{session_id}/correction",
        method="POST",
        body=_correction_command(
            surface_server.app,
            session_id,
            sequence,
            idempotency_key="idem:api:correct:1",
            reason="operator correction via protocol",
        ),
    )
    assert status == 200
    result = halted["snapshot"] if "snapshot" in halted else halted
    assert result["status"] == "CORRECTION_HALTED"


def test_wait_ms_bounds_returns_422(
    surface_server: SurfaceTestServer,
) -> None:
    task_id, _ = surface_server.seed_three_events()
    status, body = surface_server.json(
        f"/v1/surface/tasks/{task_id}/events?wait_ms=99999",
        method="GET",
    )
    assert status == 422


def test_daemon_auth_protects_legacy_task_routes(
    surface_server: SurfaceTestServer,
) -> None:
    request = urllib.request.Request(
        surface_server.base + "/v1/tasks",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request)
    assert error.value.code == 401


def test_event_batch_route_returns_strictly_increasing_sequences(
    surface_server: SurfaceTestServer,
) -> None:
    task_id, last_sequence = surface_server.seed_three_events()
    request = surface_server.request(
        f"/v1/surface/tasks/{task_id}/events?wait_ms=0",
        method="GET",
    )
    body = surface_server.open(request).read().decode()
    sequences = [
        int(line.removeprefix("id: "))
        for line in body.splitlines()
        if line.startswith("id: ")
    ]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)
    assert sequences[-1] == last_sequence
    assert "event: cursor" in body


def test_failed_auth_never_poisons_idempotency_store(
    surface_server: SurfaceTestServer,
) -> None:
    task_payload = {
        "goal_id": "goal:api:poison",
        "tenant_id": "tenant:local",
        "workspace_id": "workspace:local",
        "created_by": "user:local",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "statement": "inspect repository",
    }
    unauthenticated = urllib.request.Request(
        surface_server.base + "/v1/tasks",
        data=json.dumps(task_payload).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": "idem:api:poison:1",
        },
    )
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(unauthenticated)
    assert error.value.code == 401
    assert (
        surface_server.app.store.get_idempotency(
            "/v1/tasks", "idem:api:poison:1"
        )
        is None
    )

    request = surface_server.request(
        "/v1/tasks",
        method="POST",
        body=task_payload,
        headers={"Idempotency-Key": "idem:api:poison:1"},
    )
    with urllib.request.urlopen(request) as response:
        assert response.status == 201
        body = json.loads(response.read())
    assert body.get("task_id") is not None


def test_files_route_returns_bounded_listing(
    surface_server: SurfaceTestServer,
) -> None:
    root = surface_server.app.sandbox.root
    (root / "fixture.txt").write_text("content\n", encoding="utf-8")
    (root / "sub").mkdir(exist_ok=True)
    (root / "sub" / "nested.txt").write_text("nested\n", encoding="utf-8")
    status, opened = surface_server.json(
        "/v1/surface/sessions",
        method="POST",
        body=_open_command(surface_server.app),
    )
    snapshot = opened["snapshot"] if "snapshot" in opened else opened
    task_id = snapshot["session"]["task_id"]

    status, body = surface_server.json(
        f"/v1/surface/tasks/{task_id}/files",
        method="GET",
    )
    assert status == 200
    entries = body["files"]
    names = {entry["path"] for entry in entries}
    assert "fixture.txt" in names
    assert "sub/nested.txt" in names
    for entry in entries:
        assert set(entry) == {"path", "size", "mtime"}
        assert entry["size"] >= 0


def test_cors_allows_only_tauri_webview_origins(
    surface_server: SurfaceTestServer,
) -> None:
    request = surface_server.request(
        "/v1/health",
        headers={"Origin": "tauri://localhost"},
    )
    with urllib.request.urlopen(request) as response:
        assert (
            response.headers.get("Access-Control-Allow-Origin")
            == "tauri://localhost"
        )
        assert (
            "Authorization" in response.headers.get(
                "Access-Control-Allow-Headers", ""
            )
        )

    foreign = surface_server.request(
        "/v1/health",
        headers={"Origin": "https://evil.example"},
    )
    with urllib.request.urlopen(foreign) as response:
        assert response.headers.get("Access-Control-Allow-Origin") is None


def test_overview_route_returns_closed_task_projection(
    surface_server: SurfaceTestServer,
) -> None:
    status, opened = surface_server.json(
        "/v1/surface/sessions",
        method="POST",
        body=_open_command(surface_server.app),
    )
    snapshot = opened["snapshot"] if "snapshot" in opened else opened
    task_id = snapshot["session"]["task_id"]

    status, body = surface_server.json(
        f"/v1/surface/tasks/{task_id}/overview",
        method="GET",
    )
    assert status == 200
    overview = body["overview"]
    assert set(overview) == {
        "task_id",
        "task_status",
        "run_status",
        "expected_outcome_id",
        "receipt_count",
        "session_id",
    }
    assert overview["task_id"] == task_id
    assert overview["run_status"] in {"QUEUED", "RUNNING", "WAITING_APPROVAL", "PAUSED", "SUCCEEDED", "FAILED", "CANCELLED"}
