"""Provider persistence (Slice 3): non-secret config on disk, key in the OS
keychain or environment, startup auto-load, and the key-is-never-on-disk rule.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from apps.api_server import provider_settings
from apps.api_server.provider_settings import (
    KeychainCredentialStore,
    load_provider_config,
    save_provider_config,
)

_SECRET = "sk-persist-secret"
_CHAT_RESPONSE = {
    "id": "stub",
    "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


class _StubHandler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # noqa: ANN002
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        encoded = json.dumps(_CHAT_RESPONSE).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


@pytest.fixture
def stub_provider() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "provider.json"
    monkeypatch.setenv("AGENT_OS_PROVIDER_CONFIG", str(path))
    return path


@pytest.fixture(autouse=True)
def _no_real_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(KeychainCredentialStore, "available", lambda self: False)
    monkeypatch.setattr(KeychainCredentialStore, "store", lambda self, a, s: False)
    monkeypatch.setattr(KeychainCredentialStore, "load", lambda self, a: None)


def test_config_roundtrip_and_key_never_written(config_file: Path) -> None:
    save_provider_config(
        {
            "base_url": "https://api.anthropic.com",
            "model": "claude-sonnet-4",
            "endpoint_class": "anthropic-messages",
            "credential_env": "ANTHROPIC_API_KEY",
            "api_key": _SECRET,  # must be dropped
        }
    )
    assert (config_file.stat().st_mode & 0o777) == 0o600
    raw = config_file.read_text(encoding="utf-8")
    assert _SECRET not in raw
    config = load_provider_config()
    assert config == {
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4",
        "endpoint_class": "anthropic-messages",
        "credential_env": "ANTHROPIC_API_KEY",
    }


def test_configure_persists_non_secret_config(
    tmp_path: Path, stub_provider: str, config_file: Path
) -> None:
    from apps.api_server.app import AgentOSApplication

    app = AgentOSApplication(database=tmp_path / "a.sqlite3", workspace=tmp_path)
    app.configure_provider(
        {
            "base_url": stub_provider,
            "model": "deepseek-chat",
            "endpoint_class": "openai-compatible",
            "api_key": _SECRET,
        }
    )
    config = load_provider_config()
    assert config is not None
    assert config["base_url"] == stub_provider
    assert config["model"] == "deepseek-chat"
    assert config["credential_env"] == provider_settings.DEFAULT_CREDENTIAL_ENV
    # The credential value is never persisted to the config file.
    assert _SECRET not in config_file.read_text(encoding="utf-8")


def test_startup_autoloads_persisted_provider(
    tmp_path: Path, stub_provider: str, config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_provider_config(
        {
            "base_url": stub_provider,
            "model": "autoloaded-model",
            "endpoint_class": "openai-compatible",
            "credential_env": "AGENT_OS_PROVIDER_KEY",
        }
    )
    monkeypatch.setenv("AGENT_OS_PROVIDER_KEY", _SECRET)
    from apps.api_server.app import AgentOSApplication

    app = AgentOSApplication(database=tmp_path / "a.sqlite3", workspace=tmp_path)
    assert app.provider_configured is True
    assert app.provider_profile.model_id == "autoloaded-model"
    assert app.provider_status()["provider_id"] == "openai-compatible"
    # The key lives in memory only: not in the config file.
    assert _SECRET not in config_file.read_text(encoding="utf-8")


def test_startup_without_key_stays_unconfigured(
    tmp_path: Path, config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_provider_config(
        {
            "base_url": "https://api.example.com/v1",
            "model": "m",
            "endpoint_class": "openai-compatible",
        }
    )
    monkeypatch.delenv("AGENT_OS_PROVIDER_KEY", raising=False)
    from apps.api_server.app import AgentOSApplication

    app = AgentOSApplication(database=tmp_path / "a.sqlite3", workspace=tmp_path)
    assert app.provider_configured is False


def test_startup_autoload_does_not_repersist(
    tmp_path: Path, stub_provider: str, config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_provider_config(
        {
            "base_url": stub_provider,
            "model": "autoloaded-model",
            "endpoint_class": "openai-compatible",
        }
    )
    monkeypatch.setenv("AGENT_OS_PROVIDER_KEY", _SECRET)
    import apps.api_server.app as app_module

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("autoload must not re-persist")

    monkeypatch.setattr(app_module, "save_provider_config", _boom)
    monkeypatch.setattr(
        app_module.KeychainCredentialStore, "store", _boom
    )
    app = app_module.AgentOSApplication(
        database=tmp_path / "a.sqlite3", workspace=tmp_path
    )
    assert app.provider_configured is True
