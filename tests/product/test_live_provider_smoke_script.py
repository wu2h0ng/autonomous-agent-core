"""Live provider smoke harness: hermetic PASS via a stub, clean SKIP without a key."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scripts.live_provider_smoke import run_live_smoke

_SECRET = "sk-live-smoke-sentinel"


class _StubChatHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: ANN002
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        events = (
            'data: {"id":"c1","choices":[{"delta":{"content":"OK"},'
            '"finish_reason":null}]}\n\n'
            'data: {"id":"c1","choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            'data: {"id":"c1","choices":[],"usage":{"prompt_tokens":3,'
            '"completion_tokens":1,"total_tokens":4}}\n\n'
            "data: [DONE]\n\n"
        )
        encoded = events.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _stub() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubChatHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    import atexit

    atexit.register(server.shutdown)
    atexit.register(server.server_close)
    return f"http://127.0.0.1:{server.server_address[1]}"


def _clear_provider_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    for name in (
        "AGENT_OS_PROVIDER_PROFILE",
        "AGENT_OS_PROVIDER_BASE_URL",
        "AGENT_OS_PROVIDER_MODEL",
        "AGENT_OS_PROVIDER_API_KEY_ENV",
        "AGENT_OS_PROVIDER_ENDPOINT_CLASS",
        "OPENAI_API_URL",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_live_smoke_skips_without_a_key(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _clear_provider_env(monkeypatch)
    evidence = run_live_smoke(out=tmp_path / "skip.json")
    assert evidence["status"] == "SKIP"
    assert (tmp_path / "skip.json").exists()


def test_live_smoke_passes_and_redacts_key(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AGENT_OS_PROVIDER_BASE_URL", _stub())
    monkeypatch.setenv("AGENT_OS_PROVIDER_MODEL", "stub-model")
    monkeypatch.setenv("AGENT_OS_PROVIDER_ENDPOINT_CLASS", "openai-compatible")
    monkeypatch.setenv("OPENAI_API_KEY", _SECRET)

    out = tmp_path / "pass.json"
    evidence = run_live_smoke(out=out)
    assert evidence["status"] == "PASS", evidence
    assert evidence["delta_count"] >= 1
    assert evidence["text_preview"] == "OK"
    assert evidence["usage"]["total_tokens"] == 4
    assert evidence["usage"]["cost_status"] == "UNKNOWN"
    # The credential is never printed or persisted in the evidence.
    assert _SECRET not in json.dumps(evidence)
    assert _SECRET not in out.read_text(encoding="utf-8")
