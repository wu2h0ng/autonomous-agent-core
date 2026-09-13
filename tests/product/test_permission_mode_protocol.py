"""E2 permission-mode protocol substrate (M2, test-first).

Frozen source: GC §E2 — closed-contract `SurfaceSetPermissionModeCommand` +
`PermissionMode` literal + `SESSION_PERMISSION_MODE_SET` durable event +
snapshot mode field; runtime enforces operator-only issuance; the projector
surfaces the mode. Recording semantics (auto-allow chain, matrix) are the next
slice; here the durable substrate they hang off of.
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
    PermissionMode,
    PrincipalIdentity,
    PrincipalRole,
    SurfaceClientRef,
    SurfaceOpenSessionCommand,
    SurfaceSetPermissionModeCommand,
    TaskEventType,
    content_digest,
)
from agent_os_core import (
    DeterministicProvider,
    SessionProjectionError,
    SurfaceScopeError,
)

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler
from apps.api_server.surface_routes import SurfaceRoutes
from apps.cli.surface_client import SurfaceClient
from apps.runtime_daemon.descriptor import RuntimeDescriptor


def _operator_client(app: AgentOSApplication) -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="client:mode:1",
        client_type="CLI",
        principal_id=app.principal.principal_id,
        tenant_id=app.principal.tenant_id,
        workspace_id=app.principal.workspace_id,
        device_id="device:mode:1",
    )


def chat_app(
    root: Path, principal: PrincipalIdentity | None = None
) -> AgentOSApplication:
    app = AgentOSApplication(
        database=root / "agent-os.sqlite3",
        workspace=root,
        principal=principal,
    )
    app.provider = DeterministicProvider(
        scripted=(("mode substrate reply", ()),),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def _open_session(app: AgentOSApplication) -> tuple[str, str]:
    from agent_os_core import DeferredApprovalGateway

    session, _loop = app.open_chat_session("hi", DeferredApprovalGateway())
    return session.session_id, session.task_id


def _mode_command(
    app: AgentOSApplication,
    session_id: str,
    sequence: int,
    mode: PermissionMode,
    *,
    key: str,
    client: SurfaceClientRef | None = None,
) -> SurfaceSetPermissionModeCommand:
    return SurfaceSetPermissionModeCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=client or _operator_client(app),
        session_id=session_id,
        mode=mode,
        expected_event_sequence=sequence,
        idempotency_key=key,
        requested_at=datetime.now(timezone.utc),
    )


def _mode_events(app: AgentOSApplication, task_id: str) -> list[Any]:
    return [
        event
        for event in app.store.read(task_id)
        if event.event_type is TaskEventType.SESSION_PERMISSION_MODE_SET
    ]


def test_default_mode_is_ask(tmp_path: Path) -> None:
    app = chat_app(tmp_path)
    session_id, _ = _open_session(app)
    snapshot = app.surface.get_session(session_id)
    assert snapshot.permission_mode == "ASK"


def test_set_mode_records_durable_event_with_provenance_chain(tmp_path: Path) -> None:
    app = chat_app(tmp_path)
    session_id, task_id = _open_session(app)
    first = app.surface.set_permission_mode(
        _mode_command(
            app,
            session_id,
            app.surface_current_sequence(task_id),
            "ACCEPT_IN_WORKSPACE",
            key="mode:1",
        )
    )
    assert first.permission_mode == "ACCEPT_IN_WORKSPACE"

    events = _mode_events(app, task_id)
    assert len(events) == 1
    payload = events[0].decoded_payload()
    assert payload["mode"] == "ACCEPT_IN_WORKSPACE"
    assert payload["set_by"] == app.principal.principal_id
    assert payload["session_id"] == session_id
    assert payload["prior_digest"] is None
    first_digest = content_digest(events[0].decoded_payload())

    second = app.surface.set_permission_mode(
        _mode_command(
            app,
            session_id,
            app.surface_current_sequence(task_id),
            "ASK",
            key="mode:2",
        )
    )
    assert second.permission_mode == "ASK"
    events = _mode_events(app, task_id)
    assert len(events) == 2
    assert events[1].decoded_payload()["prior_digest"] == first_digest


def test_set_mode_rejects_non_operator_scope(tmp_path: Path) -> None:
    app = chat_app(tmp_path)
    session_id, task_id = _open_session(app)
    outsider = SurfaceClientRef(
        client_id="client:other",
        client_type="CLI",
        principal_id="user:someone-else",
        tenant_id=app.principal.tenant_id,
        workspace_id=app.principal.workspace_id,
        device_id="device:other",
    )
    with pytest.raises(SurfaceScopeError):
        app.surface.set_permission_mode(
            _mode_command(
                app,
                session_id,
                app.surface_current_sequence(task_id),
                "ACCEPT_IN_WORKSPACE",
                key="mode:x",
                client=outsider,
            )
        )
    assert _mode_events(app, task_id) == []


def test_set_mode_rejects_model_role_principal(tmp_path: Path) -> None:
    app = chat_app(tmp_path)
    session_id, task_id = _open_session(app)
    model_principal = PrincipalIdentity(
        principal_id="user:local",
        role=PrincipalRole.MODEL,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        authenticated_at=datetime.now(timezone.utc),
    )
    # Defense-in-depth: even if a model-role principal reached the app port,
    # the mode change itself requires principal authority.
    original = app.principal
    try:
        app.principal = model_principal
        with pytest.raises(PermissionError):
            app.surface_set_permission_mode(
                _mode_command(
                    app,
                    session_id,
                    app.surface_current_sequence(task_id),
                    "ACCEPT_IN_WORKSPACE",
                    key="mode:m",
                )
            )
    finally:
        app.principal = original
    assert _mode_events(app, task_id) == []


def test_projector_rejects_invalid_mode_payload(tmp_path: Path) -> None:
    app = chat_app(tmp_path)
    session_id, task_id = _open_session(app)
    app.tasks.append_event(
        task_id,
        TaskEventType.SESSION_PERMISSION_MODE_SET,
        {
            "session_id": session_id,
            "mode": "MODE_MODEL_SET",
            "set_by": app.principal.principal_id,
            "prior_digest": None,
        },
    )
    with pytest.raises(SessionProjectionError):
        app.tasks.project_session(task_id, session_id)


def test_mode_survives_reprojection_from_durable_store(tmp_path: Path) -> None:
    app = chat_app(tmp_path)
    session_id, task_id = _open_session(app)
    app.surface.set_permission_mode(
        _mode_command(
            app,
            session_id,
            app.surface_current_sequence(task_id),
            "ACCEPT_READ_ONLY",
            key="mode:r",
        )
    )
    # Fresh projection straight from the durable store (restart-equivalent).
    from agent_os_core import SessionProjector

    projected = SessionProjector(app.store).project(task_id, session_id)
    assert projected.permission_mode == "ACCEPT_READ_ONLY"


# ---------------------------------------------------------------------------
# HTTP route + client
# ---------------------------------------------------------------------------


class ModeTestServer:
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

    def json(self, path: str, **kwargs: Any) -> tuple[int, dict]:
        request = self.request(path, **kwargs)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def open_session(self) -> tuple[str, int]:
        command = SurfaceOpenSessionCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_operator_client(self.app),
            statement="mode http session",
            idempotency_key="idem:mode:open:1",
            requested_at=datetime.now(timezone.utc),
        )
        status, payload = self.json(
            "/v1/surface/sessions",
            method="POST",
            body=command.model_dump(mode="json"),
        )
        assert status == 200, payload
        snapshot = payload["snapshot"]
        return snapshot["session"]["session_id"], snapshot["event_sequence"]


@pytest.fixture
def mode_server(tmp_path: Path) -> Generator[ModeTestServer, None, None]:
    app = chat_app(tmp_path)
    token = "test-local-token"
    handler = type(
        "TestModeHandler",
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
        yield ModeTestServer(app, base, token, server)
    finally:
        server.shutdown()
        server.server_close()


def _descriptor(port: int, token: str, tmp_path: Path) -> RuntimeDescriptor:
    return RuntimeDescriptor(
        protocol_version="1.1",
        pid=1234,
        boot_id="boot:mode:1",
        host="127.0.0.1",
        port=port,
        bearer_token=token,
        database_path=str(tmp_path / "agent-os.sqlite3"),
        workspace_path=str(tmp_path / "workspace"),
        created_at=datetime.now(timezone.utc),
    )


def test_mode_route_sets_mode_and_requires_protocol_header(
    mode_server: ModeTestServer,
) -> None:
    session_id, sequence = mode_server.open_session()
    command = _mode_command(
        mode_server.app,
        session_id,
        sequence,
        "ACCEPT_IN_WORKSPACE",
        key="mode:http:1",
    )
    status, payload = mode_server.json(
        f"/v1/surface/sessions/{session_id}/mode",
        method="POST",
        body=command.model_dump(mode="json"),
    )
    assert status == 200, payload
    assert payload["snapshot"]["permission_mode"] == "ACCEPT_IN_WORKSPACE"

    stale = _mode_command(
        mode_server.app,
        session_id,
        sequence,
        "ASK",
        key="mode:http:2",
    )
    status, payload = mode_server.json(
        f"/v1/surface/sessions/{session_id}/mode",
        method="POST",
        body=stale.model_dump(mode="json"),
        headers={"X-Agent-OS-Protocol": ""},
    )
    assert status == 422
    assert "error" in payload


def test_client_set_permission_mode(
    mode_server: ModeTestServer, tmp_path: Path
) -> None:
    session_id, sequence = mode_server.open_session()
    descriptor = _descriptor(
        mode_server.server.server_address[1], mode_server.token, tmp_path
    )
    client = SurfaceClient(descriptor)
    snapshot = client.set_permission_mode(
        session_id, "ACCEPT_IN_WORKSPACE", expected_event_sequence=sequence
    )
    assert snapshot.permission_mode == "ACCEPT_IN_WORKSPACE"
    again = client.set_permission_mode(session_id, "ASK")
    assert again.permission_mode == "ASK"
