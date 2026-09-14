"""Native Anthropic Messages adapter (Slice 2): hermetic request/response/tool
mapping, endpoint-class selection, streaming fallback, and E3 cost honesty.
"""

from __future__ import annotations

import json
import threading
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
from agent_os_core import AnthropicMessagesProvider, EnvCredentialBroker
from agent_os_core.provider import ProviderResponse

_SECRET = "sk-ant-test-secret"
_RECORDED: list[dict[str, Any]] = []


class _StubAnthropicHandler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # noqa: ANN002
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        _RECORDED.append(
            {
                "path": self.path,
                "x_api_key": self.headers.get("x-api-key"),
                "anthropic_version": self.headers.get("anthropic-version"),
                "authorization": self.headers.get("Authorization"),
                "body": body,
            }
        )
        payload = {
            "id": "msg_stub",
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "text", "text": "hello "},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "workspace__read",
                    "input": {"path": "a.txt"},
                },
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 12, "output_tokens": 5},
        }
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _stub() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubAnthropicHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # Keep the server alive for the test process; register shutdown at exit.
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
        provider_id="anthropic-messages",
        resolver_key="ANTHROPIC_TEST_KEY",
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
                        tool_call_id="toolu_prev",
                        capability_id="workspace.read",
                        arguments_json='{"path": "a.txt"}',
                    ),
                ),
            ),
            ProviderMessage(
                role=ProviderMessageRole.TOOL,
                content="contents",
                tool_call_id="toolu_prev",
            ),
        ),
        timeout_seconds=30,
        created_at=datetime.now(timezone.utc),
    )


def test_anthropic_request_and_response_mapping(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    base = _stub()
    monkeypatch.setenv("ANTHROPIC_TEST_KEY", _SECRET)
    _RECORDED.clear()
    provider = AnthropicMessagesProvider(
        base_url=base,
        model="claude-sonnet-4",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
    )
    result = provider.complete(
        _request().model_copy(update={"allowed_capability_ids": ("workspace.read",)})
    )
    assert isinstance(result, ProviderResponse), result

    # Response mapping
    assert result.text == "hello "
    assert len(result.tool_proposals) == 1
    assert result.tool_proposals[0].capability_id == "workspace.read"
    assert json.loads(result.tool_proposals[0].arguments_json) == {"path": "a.txt"}
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 5
    assert result.usage.total_tokens == 17
    assert result.usage.cost_status == "UNKNOWN"

    # Request shape
    recorded = _RECORDED[-1]
    assert recorded["path"] == "/v1/messages"
    assert recorded["x_api_key"] == _SECRET
    assert recorded["anthropic_version"] == "2023-06-01"
    assert recorded["authorization"] is None  # never Bearer for Anthropic
    body = recorded["body"]
    assert body["model"] == "claude-sonnet-4"
    assert body["max_tokens"] >= 1
    assert body["system"] == "be terse"
    assert all(message["role"] != "system" for message in body["messages"])
    assert body["tools"][0]["input_schema"]["type"] == "object"
    assert body["tools"][0]["name"] == "workspace__read"
    # assistant tool_use echoed back
    assistant = next(m for m in body["messages"] if m["role"] == "assistant")
    assert assistant["content"][0]["type"] == "tool_use"
    # tool result mapped to a user block
    tool_result = next(
        m
        for m in body["messages"]
        if m["role"] == "user" and isinstance(m["content"], list)
    )
    assert tool_result["content"][0]["type"] == "tool_result"
    assert tool_result["content"][0]["tool_use_id"] == "toolu_prev"


def test_anthropic_streaming_falls_back_to_single_delta(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    base = _stub()
    monkeypatch.setenv("ANTHROPIC_TEST_KEY", _SECRET)
    provider = AnthropicMessagesProvider(
        base_url=base,
        model="claude-sonnet-4",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
    )
    deltas: list[str] = []
    result = provider.complete_streaming(
        _request().model_copy(update={"allowed_capability_ids": ()}),
        on_text_delta=deltas.append,
    )
    assert isinstance(result, ProviderResponse)
    assert deltas == [result.text]


def test_anthropic_missing_credential_is_a_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("ANTHROPIC_TEST_KEY", raising=False)
    provider = AnthropicMessagesProvider(
        base_url=_stub(),
        model="claude-sonnet-4",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
    )
    result = provider.complete(_request())
    assert not isinstance(result, ProviderResponse)
    assert result.code.value == "AUTHENTICATION_FAILED"


def test_profile_anthropic_selects_native_adapter(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AGENT_OS_PROVIDER_PROFILE", "anthropic")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", _stub())
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4")
    monkeypatch.setenv("ANTHROPIC_API_KEY", _SECRET)
    from apps.api_server.app import AgentOSApplication

    app = AgentOSApplication(
        database=tmp_path / "agent.sqlite3", workspace=tmp_path
    )
    assert isinstance(app.provider, AnthropicMessagesProvider)
    assert app.provider_profile.endpoint_class == "anthropic-messages"
    assert app.provider_status()["provider_id"] == "anthropic-messages"


def test_surface_configure_selects_anthropic_adapter(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ANTHROPIC_TEST_KEY", _SECRET)
    from agent_os_contracts import (
        SURFACE_PROTOCOL_VERSION,
        SurfaceClientRef,
        SurfaceProviderConfigureCommand,
    )
    from agent_os_core import DeterministicProvider, SurfaceRuntime
    from apps.api_server.app import AgentOSApplication

    app = AgentOSApplication(
        database=tmp_path / "agent.sqlite3", workspace=tmp_path
    )
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
        model="claude-sonnet-4",
        api_key=_SECRET,
        endpoint_class="anthropic-messages",
    )
    status = SurfaceRuntime(app).configure_provider(command)
    assert status.endpoint_class == "anthropic-messages"
    assert isinstance(app.provider, AnthropicMessagesProvider)
    assert app._active_provider_resolver_key is not None
