from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent_os_contracts import CredentialRef, CredentialStatus, ProviderMessage, ProviderMessageRole, ProviderRequest, ProviderResponse
from agent_os_core import EnvCredentialBroker, OpenAICompatibleProvider


class _ProviderHandler(BaseHTTPRequestHandler):
    seen: dict[str, object] = {}

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        _ProviderHandler.seen = {
            "body": json.loads(body),
            "authorization": self.headers.get("Authorization"),
        }
        result = {
            "id": "response:http",
            "choices": [{"message": {"content": "HTTP provider response", "tool_calls": [{"id": "call-1", "function": {"name": "workspace__read", "arguments": '{"path":"fixture.txt"}'}}]}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        }
        data = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        return


def test_openai_compatible_http_adapter_keeps_secret_out_of_payload() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    key_name = "AGENT_OS_TEST_SECRET"
    old = os.environ.get(key_name)
    os.environ[key_name] = "secret-value-that-must-not-leak"
    try:
        now = datetime.now(timezone.utc)
        credential = CredentialRef(
            credential_ref_id="credential:http", owner_principal_id="user-1",
            tenant_id="tenant-1", workspace_id="workspace-1", provider_id="openai-compatible",
            resolver_key=key_name, scopes=("chat",), status=CredentialStatus.ACTIVE,
            created_at=now, expires_at=now + timedelta(minutes=5),
        )
        provider = OpenAICompatibleProvider(
            base_url=f"http://127.0.0.1:{server.server_address[1]}", model="test-model",
            credential=credential, credentials=EnvCredentialBroker(), timeout_seconds=5,
        )
        response = provider.complete(ProviderRequest(
            request_id="request:http", task_id="task:http", run_id="run:http",
            provider_profile_id="profile:http",
            messages=(ProviderMessage(role=ProviderMessageRole.USER, content="hello"),),
            allowed_capability_ids=("workspace.read",), timeout_seconds=5, created_at=now,
        ))
        assert isinstance(response, ProviderResponse)
        assert response.text == "HTTP provider response"
        assert response.tool_proposals[0].capability_id == "workspace.read"
        assert _ProviderHandler.seen["authorization"] == "Bearer secret-value-that-must-not-leak"
        assert "secret-value-that-must-not-leak" not in json.dumps(_ProviderHandler.seen["body"])
    finally:
        if old is None:
            os.environ.pop(key_name, None)
        else:
            os.environ[key_name] = old
        server.shutdown()
        server.server_close()
