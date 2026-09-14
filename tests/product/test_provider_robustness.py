"""Provider robustness: pricing (cost honesty), bounded retry, max_tokens config."""

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
)
from agent_os_core import EnvCredentialBroker, OpenAICompatibleProvider
from agent_os_core.provider import ProviderResponse

_SECRET = "sk-robustness"
_STATE: dict[str, Any] = {"calls": 0, "statuses": []}


class _StubHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: ANN002
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        _STATE["calls"] += 1
        statuses = _STATE["statuses"]
        # statuses is checked with the 1-based call index
        status = statuses[_STATE["calls"] - 1] if _STATE["calls"] - 1 < len(statuses) else 200
        if status != 200:
            body = json.dumps({"error": "rate limited"}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        payload = {
            "id": "stub",
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "total_tokens": 1500,
            },
        }
        encoded = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _stub() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    import atexit

    atexit.register(server.shutdown)
    atexit.register(server.server_close)
    _STATE["calls"] = 0
    _STATE["statuses"] = []
    return f"http://127.0.0.1:{server.server_address[1]}"


def _credential() -> CredentialRef:
    return CredentialRef(
        credential_ref_id="credential:test",
        owner_principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        provider_id="openai-compatible",
        resolver_key="ROBUSTNESS_TEST_KEY",
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
        messages=(ProviderMessage(role=ProviderMessageRole.USER, content="hi"),),
        timeout_seconds=30,
        created_at=datetime.now(timezone.utc),
    )


def _provider(monkeypatch, base: str, **kwargs: object):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ROBUSTNESS_TEST_KEY", _SECRET)
    return OpenAICompatibleProvider(
        base_url=base,
        model="stub-model",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
        **kwargs,  # type: ignore[arg-type]
    )


def test_pricing_table_makes_cost_known(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    pricing = tmp_path / "pricing.json"
    pricing.write_text(
        json.dumps(
            {
                "models": {
                    "stub-model": {
                        "input_per_1k_usd": 1.0,
                        "output_per_1k_usd": 2.0,
                        "source": "test-table",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_OS_PRICING_FILE", str(pricing))
    result = _provider(monkeypatch, _stub()).complete(_request())
    assert isinstance(result, ProviderResponse), result
    assert result.usage.total_tokens == 1500
    assert result.usage.cost_status == "KNOWN"
    assert result.usage.pricing_source_ref == "test-table"
    # 1000/1000*1.0 + 500/1000*2.0 = 2.0
    assert str(result.usage.estimated_cost_usd) == "2.0"


def test_without_pricing_cost_stays_unknown(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AGENT_OS_PRICING_FILE", str(tmp_path / "absent.json"))
    result = _provider(monkeypatch, _stub()).complete(_request())
    assert isinstance(result, ProviderResponse)
    assert result.usage.cost_status == "UNKNOWN"
    assert result.usage.estimated_cost_usd is None


def test_retryable_failure_is_retried_then_succeeds(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    base = _stub()
    provider = _provider(
        monkeypatch, base, max_retries=2, retry_base_seconds=0.0, timeout_seconds=5
    )
    _STATE["statuses"] = [429, 200]
    result = provider.complete(_request())
    assert isinstance(result, ProviderResponse), result
    assert _STATE["calls"] == 2


def test_retries_are_bounded_and_failure_returned(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    provider = _provider(
        monkeypatch, _stub(), max_retries=2, retry_base_seconds=0.0, timeout_seconds=5
    )
    _STATE["statuses"] = [429, 429, 429, 429]
    result = provider.complete(_request())
    assert not isinstance(result, ProviderResponse)
    assert result.retryable is True
    assert _STATE["calls"] == 3  # 1 + 2 retries


def test_non_retryable_failure_is_not_retried(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    provider = _provider(
        monkeypatch, _stub(), max_retries=3, retry_base_seconds=0.0, timeout_seconds=5
    )
    _STATE["statuses"] = [400, 200]
    result = provider.complete(_request())
    assert not isinstance(result, ProviderResponse)
    assert _STATE["calls"] == 1


def test_max_tokens_is_sent_in_the_openai_body(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    seen: dict[str, Any] = {}

    class _CaptureHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: ANN002
            return

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            seen["body"] = json.loads(self.rfile.read(length).decode())
            payload = {
                "id": "s",
                "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
            encoded = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _CaptureHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        provider = _provider(monkeypatch, base, max_tokens=321)
        provider.complete(_request())
        assert seen["body"]["max_tokens"] == 321
    finally:
        server.shutdown()
        server.server_close()
