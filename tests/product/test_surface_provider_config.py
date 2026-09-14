"""Surface provider configuration (terminal "add provider"): redacted status,
transient in-memory credential (never persisted), operator scope, fail-closed
endpoint class. This path does not alter permit/approval or C7.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    SurfaceClientRef,
)
from agent_os_core import DeterministicProvider, SurfaceRuntime
from agent_os_core.surface_runtime import SurfaceScopeError

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler

_SECRET = "sk-test-secret-do-not-persist"
_PROVIDER_READ_ENV_PREFIXES = (
    "AGENT_OS_PROVIDER_",
    "OPENAI_API_URL",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "OPENAI_API_KEY",
)


class _StubChatHandler(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible /chat/completions endpoint for the smoke call."""

    def log_message(self, *args: object) -> None:  # noqa: ANN002
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if self.path != "/chat/completions":
            self.send_response(404)
            self.end_headers()
            return
        payload = {
            "id": "stub-response",
            "choices": [
                {"message": {"content": "OK"}, "finish_reason": "stop"}
            ],
            "usage": {
                "prompt_tokens": 3,
                "completion_tokens": 1,
                "total_tokens": 4,
            },
        }
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


@pytest.fixture
def stub_provider() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubChatHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _clean_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(_PROVIDER_READ_ENV_PREFIXES):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("AGENT_OS_RUNTIME_PROVIDER_KEY", raising=False)
    yield
    for name in [
        key
        for key in os.environ
        if key.startswith("AGENT_OS_RUNTIME_PROVIDER_KEY_")
    ]:
        os.environ.pop(name, None)


def _app(root: Path) -> AgentOSApplication:
    app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
    app.provider = DeterministicProvider(
        scripted=(("hi", ()),),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = False
    return app


def _client(app: AgentOSApplication) -> SurfaceClientRef:
    principal = app.principal
    return SurfaceClientRef(
        client_id="cli:test",
        client_type="TEST",
        principal_id=principal.principal_id,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        device_id="device:test",
    )


def _command(app: AgentOSApplication, base_url: str, **overrides: object):  # type: ignore[no-untyped-def]
    from agent_os_contracts import SurfaceProviderConfigureCommand

    payload: dict[str, object] = {
        "protocol_version": SURFACE_PROTOCOL_VERSION,
        "client": _client(app),
        "base_url": base_url,
        "model": "stub-model",
        "api_key": _SECRET,
    }
    payload.update(overrides)
    return SurfaceProviderConfigureCommand.model_validate(payload)


def test_status_is_redacted_and_unconfigured_by_default(tmp_path: Path) -> None:
    app = _app(tmp_path)
    status = SurfaceRuntime(app).provider_status()
    assert status.configured is False
    assert status.credential_ref_id is None
    assert status.model_id is None


def test_configure_roundtrip_returns_redacted_status(
    tmp_path: Path, stub_provider: str
) -> None:
    app = _app(tmp_path)
    runtime = SurfaceRuntime(app)
    status = runtime.configure_provider(_command(app, stub_provider))

    assert status.configured is True
    assert status.model_id == "stub-model"
    assert status.endpoint_class == "openai-compatible"
    assert status.base_url == stub_provider
    assert status.credential_ref_id
    # The credential value never appears in the serialized status.
    assert _SECRET not in status.model_dump_json()


def test_provider_key_is_not_persisted_anywhere(
    tmp_path: Path, stub_provider: str
) -> None:
    app = _app(tmp_path)
    runtime = SurfaceRuntime(app)
    runtime.configure_provider(_command(app, stub_provider))

    # Not in durable state (sqlite), not in any workspace file/artifact.
    leaked: list[str] = []
    for path in sorted(tmp_path.rglob("*")):
        if path.is_file():
            try:
                if _SECRET.encode() in path.read_bytes():
                    leaked.append(str(path.relative_to(tmp_path)))
            except OSError:
                continue
    assert leaked == [], f"credential persisted to: {leaked}"
    # Not in the status payload either.
    assert _SECRET not in runtime.provider_status().model_dump_json()


def test_unsupported_endpoint_class_fails_closed(
    tmp_path: Path, stub_provider: str
) -> None:
    app = _app(tmp_path)
    runtime = SurfaceRuntime(app)
    with pytest.raises(ValueError, match="unsupported endpoint_class"):
        runtime.configure_provider(
            _command(app, stub_provider, endpoint_class="cohere-command")
        )
    assert runtime.provider_status().configured is False


def test_configure_rejects_foreign_principal(
    tmp_path: Path, stub_provider: str
) -> None:
    app = _app(tmp_path)
    runtime = SurfaceRuntime(app)
    foreign = _command(app, stub_provider)
    foreign = foreign.model_copy(
        update={
            "client": foreign.client.model_copy(
                update={"principal_id": "user:someone-else"}
            )
        }
    )
    with pytest.raises(SurfaceScopeError):
        runtime.configure_provider(foreign)


def test_http_provider_routes(tmp_path: Path, stub_provider: str) -> None:
    app = _app(tmp_path)
    token = "test-local-token"
    handler = type(
        "TestProviderHandler",
        (Handler,),
        {
            "application": app,
            "local_token": token,
            "surface_routes": __import__(
                "apps.api_server.surface_routes", fromlist=["SurfaceRoutes"]
            ).SurfaceRoutes(app.surface, token),
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status_req = urllib.request.Request(
            f"{base}/v1/surface/provider",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(status_req) as response:
            assert response.status == 200
            assert json.loads(response.read())["provider"]["configured"] is False

        body = _command(app, stub_provider).model_dump(mode="json")
        configure_req = urllib.request.Request(
            f"{base}/v1/surface/provider",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Agent-OS-Protocol": SURFACE_PROTOCOL_VERSION,
            },
        )
        with urllib.request.urlopen(configure_req) as response:
            payload = json.loads(response.read())
            assert response.status == 200
            assert payload["provider"]["configured"] is True
            assert _SECRET not in json.dumps(payload)

        unauth = urllib.request.Request(f"{base}/v1/surface/provider")
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(unauth)
        assert excinfo.value.code == 401
    finally:
        server.shutdown()
        server.server_close()


def test_failed_reconfigure_preserves_active_provider(
    tmp_path: Path, stub_provider: str
) -> None:
    app = _app(tmp_path)
    runtime = SurfaceRuntime(app)
    runtime.configure_provider(_command(app, stub_provider))
    active = app.provider
    active_resolver_key = app._active_provider_resolver_key
    assert active_resolver_key and os.environ.get(active_resolver_key) == _SECRET

    # A failed reconfigure must not clobber the live provider's credential.
    with pytest.raises(ConnectionError):
        runtime.configure_provider(_command(app, "http://127.0.0.1:1"))

    assert app.provider is active
    assert runtime.provider_status().configured is True
    assert os.environ.get(active_resolver_key) == _SECRET


def test_endpoint_with_embedded_credentials_is_rejected(tmp_path: Path) -> None:
    app = _app(tmp_path)
    runtime = SurfaceRuntime(app)
    with pytest.raises(ValueError, match="must not embed credentials"):
        runtime.configure_provider(
            _command(app, "https://user:pass@example.com/v1")
        )
    assert runtime.provider_status().configured is False


def test_http_provider_validation_error_never_echoes_credential(
    tmp_path: Path, stub_provider: str
) -> None:
    app = _app(tmp_path)
    token = "test-local-token"
    handler = type(
        "TestProviderEchoHandler",
        (Handler,),
        {
            "application": app,
            "local_token": token,
            "surface_routes": __import__(
                "apps.api_server.surface_routes", fromlist=["SurfaceRoutes"]
            ).SurfaceRoutes(app.surface, token),
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        body = _command(app, stub_provider).model_dump(mode="json")
        body["api_key"] = [_SECRET]  # wrong type triggers a ValidationError
        request = urllib.request.Request(
            f"{base}/v1/surface/provider",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Agent-OS-Protocol": SURFACE_PROTOCOL_VERSION,
            },
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(request)
        error_body = excinfo.value.read().decode("utf-8")
        assert _SECRET not in error_body
        assert "input_value" not in error_body

        unauth_post = urllib.request.Request(
            f"{base}/v1/surface/provider",
            data=json.dumps(
                _command(app, stub_provider).model_dump(mode="json")
            ).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as unauth:
            urllib.request.urlopen(unauth_post)
        assert unauth.value.code == 401
    finally:
        server.shutdown()
        server.server_close()


def test_status_reports_persistence_and_clear_removes_it(
    tmp_path: Path, stub_provider: str
) -> None:
    from agent_os_contracts import SurfaceProviderClearCommand

    app = _app(tmp_path)
    runtime = SurfaceRuntime(app)
    runtime.configure_provider(_command(app, stub_provider))

    status = runtime.provider_status()
    assert status.persisted is True
    # keychain disabled (conftest) and no env key -> no key source
    assert status.key_source in {"none", "env"}
    assert _SECRET not in status.model_dump_json()

    cleared = runtime.clear_provider(
        SurfaceProviderClearCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION, client=_client(app)
        )
    )
    assert cleared.persisted is False
    assert not (tmp_path / "provider.json").exists()
