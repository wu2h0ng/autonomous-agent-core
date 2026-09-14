"""Native Google Gemini adapter (Slice 2b): hermetic mapping, selection, and
keyring credential backend (no-argv) with a security-CLI fallback.
"""

from __future__ import annotations

import json
import sys
import threading
import types
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from agent_os_contracts import (
    CredentialRef,
    CredentialStatus,
    ProviderMessage,
    ProviderMessageRole,
    ProviderRequest,
    ProviderToolCall,
)
from agent_os_core import EnvCredentialBroker, GeminiGenerativeProvider
from agent_os_core.provider import ProviderResponse

_SECRET = "gm-test-secret"
_RECORDED: list[dict[str, Any]] = []


class _StubGeminiHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: ANN002
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        _RECORDED.append(
            {
                "path": self.path,
                "api_key": self.headers.get("x-goog-api-key"),
                "authorization": self.headers.get("Authorization"),
                "body": body,
            }
        )
        if ":streamGenerateContent" in self.path:
            chunks = (
                'data: {"responseId":"resp_1","candidates":[{"content":'
                '{"role":"model","parts":[{"text":"he"}]}}]}\n\n'
                'data: {"responseId":"resp_1","candidates":[{"content":'
                '{"role":"model","parts":[{"text":"llo"}]},'
                '"finishReason":"STOP"}],"usageMetadata":'
                '{"promptTokenCount":7,"candidatesTokenCount":3,'
                '"totalTokenCount":10}}\n\n'
            )
            encoded = chunks.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return
        payload = {
            "responseId": "resp_stub",
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {"text": "hi "},
                            {
                                "functionCall": {
                                    "name": "workspace__read",
                                    "args": {"path": "a.txt"},
                                }
                            },
                        ],
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 7,
                "candidatesTokenCount": 3,
                "totalTokenCount": 10,
            },
        }
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _stub() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubGeminiHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    import atexit

    atexit.register(server.shutdown)
    atexit.register(server.server_close)
    return f"http://127.0.0.1:{server.server_address[1]}"


def _credential() -> CredentialRef:
    return CredentialRef(
        credential_ref_id="credential:test",
        owner_principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        provider_id="google-generative",
        resolver_key="GEMINI_TEST_KEY",
        scopes=("chat",),
        status=CredentialStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )


def _request() -> ProviderRequest:
    return ProviderRequest(
        request_id="req:1",
        task_id="task:1",
        run_id="run:1",
        provider_profile_id="provider-profile:default",
        messages=(
            ProviderMessage(role=ProviderMessageRole.SYSTEM, content="be terse"),
            ProviderMessage(role=ProviderMessageRole.USER, content="hi"),
            ProviderMessage(
                role=ProviderMessageRole.ASSISTANT,
                content="",
                tool_calls=(
                    ProviderToolCall(
                        tool_call_id="call_1",
                        capability_id="workspace.read",
                        arguments_json='{"path": "a.txt"}',
                    ),
                ),
            ),
            ProviderMessage(
                role=ProviderMessageRole.TOOL,
                content="contents",
                tool_call_id="call_1",
            ),
        ),
        timeout_seconds=30,
        created_at=datetime.now(timezone.utc),
    )


def test_gemini_request_and_response_mapping(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    base = _stub()
    monkeypatch.setenv("GEMINI_TEST_KEY", _SECRET)
    _RECORDED.clear()
    provider = GeminiGenerativeProvider(
        base_url=base,
        model="gemini-1.5-pro",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
    )
    result = provider.complete(
        _request().model_copy(update={"allowed_capability_ids": ("workspace.read",)})
    )
    assert isinstance(result, ProviderResponse), result
    assert result.text == "hi "
    assert result.tool_proposals[0].capability_id == "workspace.read"
    assert json.loads(result.tool_proposals[0].arguments_json) == {"path": "a.txt"}
    assert result.usage.total_tokens == 10
    assert result.usage.cost_status == "UNKNOWN"

    recorded = _RECORDED[-1]
    assert recorded["path"] == "/v1beta/models/gemini-1.5-pro:generateContent"
    assert recorded["api_key"] == _SECRET
    assert recorded["authorization"] is None
    body = recorded["body"]
    assert body["systemInstruction"]["parts"][0]["text"] == "be terse"
    assert body["contents"][0] == {"role": "user", "parts": [{"text": "hi"}]}
    assert body["contents"][1]["role"] == "model"
    assert body["contents"][1]["parts"][0]["functionCall"]["name"] == "workspace__read"
    assert body["contents"][2]["parts"][0]["functionResponse"]["name"] == "workspace__read"
    assert body["tools"][0]["functionDeclarations"][0]["name"] == "workspace__read"
    parameters = body["tools"][0]["functionDeclarations"][0]["parameters"]
    assert parameters["properties"], "property names must survive projection"
    assert "additionalProperties" not in parameters
    assert "required" not in parameters or parameters["required"]


def test_gemini_missing_credential_is_a_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("GEMINI_TEST_KEY", raising=False)
    provider = GeminiGenerativeProvider(
        base_url=_stub(),
        model="gemini-1.5-pro",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
    )
    result = provider.complete(_request())
    assert not isinstance(result, ProviderResponse)
    assert result.code.value == "AUTHENTICATION_FAILED"


def test_surface_configure_selects_gemini_adapter(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GEMINI_TEST_KEY", _SECRET)
    _RECORDED.clear()
    from agent_os_contracts import (
        SURFACE_PROTOCOL_VERSION,
        SurfaceClientRef,
        SurfaceProviderConfigureCommand,
    )
    from agent_os_core import DeterministicProvider, SurfaceRuntime
    from apps.api_server.app import AgentOSApplication

    app = AgentOSApplication(database=tmp_path / "a.sqlite3", workspace=tmp_path)
    app.provider = DeterministicProvider(
        scripted=(("hi", ()),),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = False
    principal = app.principal
    command = SurfaceProviderConfigureCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=SurfaceClientRef(
            client_id="cli:test",
            client_type="TEST",
            principal_id=principal.principal_id,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            device_id="device:test",
        ),
        base_url=_stub(),
        model="gemini-1.5-pro",
        api_key=_SECRET,
        endpoint_class="google-generative",
    )
    status = SurfaceRuntime(app).configure_provider(command)
    assert status.endpoint_class == "google-generative"
    assert isinstance(app.provider, GeminiGenerativeProvider)
    # The configured runtime (which carries a provider_profile) must still hit
    # the model-scoped path -- this is the F1 regression guard.
    assert _RECORDED[-1]["path"] == "/v1beta/models/gemini-1.5-pro:generateContent"


def test_default_store_prefers_keyring(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from apps.api_server import provider_settings

    monkeypatch.delenv("AGENT_OS_DISABLE_KEYCHAIN", raising=False)
    fake = types.ModuleType("keyring")

    class _Backend:
        pass

    class _FailKeyring:
        pass

    _fail = types.ModuleType("keyring.backends.fail")
    _fail.Keyring = _FailKeyring  # type: ignore[attr-defined]
    store: dict[tuple[str, str], str] = {}

    def _get_keyring() -> object:
        return _Backend()

    def _set_password(service: str, account: str, secret: str) -> None:
        store[(service, account)] = secret

    def _get_password(service: str, account: str) -> str | None:
        return store.get((service, account))

    def _delete_password(service: str, account: str) -> None:
        store.pop((service, account), None)

    fake.get_keyring = _get_keyring  # type: ignore[attr-defined]
    fake.set_password = _set_password  # type: ignore[attr-defined]
    fake.get_password = _get_password  # type: ignore[attr-defined]
    fake.delete_password = _delete_password  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "keyring", fake)
    monkeypatch.setitem(sys.modules, "keyring.backends", types.ModuleType("keyring.backends"))
    monkeypatch.setitem(sys.modules, "keyring.backends.fail", _fail)

    assert provider_settings.KeyringCredentialStore().available() is True
    store_obj = provider_settings.default_credential_store()
    assert isinstance(store_obj, provider_settings.KeyringCredentialStore)
    assert store_obj.store("account", _SECRET) is True
    assert store_obj.load("account") == _SECRET
    store_obj.delete("account")
    assert store_obj.load("account") is None


def test_gemini_unmatched_tool_result_fails_closed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GEMINI_TEST_KEY", _SECRET)
    provider = GeminiGenerativeProvider(
        base_url=_stub(),
        model="gemini-1.5-pro",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
    )
    request = ProviderRequest(
        request_id="req:orphan",
        task_id="task:1",
        run_id="run:1",
        provider_profile_id="provider-profile:default",
        messages=(
            ProviderMessage(role=ProviderMessageRole.USER, content="hi"),
            ProviderMessage(
                role=ProviderMessageRole.TOOL,
                content="orphan",
                tool_call_id="call_missing",
            ),
        ),
        timeout_seconds=30,
        created_at=datetime.now(timezone.utc),
    )
    result = provider.complete(request)
    assert not isinstance(result, ProviderResponse)
    assert result.code.value == "MALFORMED"


def test_gemini_streaming_emits_text_deltas(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GEMINI_TEST_KEY", _SECRET)
    _RECORDED.clear()
    provider = GeminiGenerativeProvider(
        base_url=_stub(),
        model="gemini-1.5-pro",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
    )
    deltas: list[str] = []
    result = provider.complete_streaming(
        _request().model_copy(update={"allowed_capability_ids": ()}),
        on_text_delta=deltas.append,
    )
    assert isinstance(result, ProviderResponse), result
    assert result.text == "hello"
    assert deltas == ["he", "llo"]
    assert result.usage.total_tokens == 10
    assert result.finish_reason == "stop"
    assert _RECORDED[-1]["path"].endswith(":streamGenerateContent?alt=sse")


def test_gemini_max_output_tokens_is_configurable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GEMINI_TEST_KEY", _SECRET)
    _RECORDED.clear()
    provider = GeminiGenerativeProvider(
        base_url=_stub(),
        model="gemini-1.5-pro",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
        max_tokens=555,
    )
    provider.complete(_request())
    assert _RECORDED[-1]["body"]["generationConfig"]["maxOutputTokens"] == 555
