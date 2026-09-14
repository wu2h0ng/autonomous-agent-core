"""Local provider configuration + credential store for the terminal runtime.

Non-secret configuration (base_url, model, endpoint_class, key env var name) is
persisted to ``~/.agent-os/provider.json`` (0600, outside the repository). The
API key is NEVER written here: it is stored in the OS keychain when available
(macOS ``security``) with an environment-variable fallback, and only ever
resolved into process memory.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".agent-os" / "provider.json"
KEYCHAIN_SERVICE = "agent-os:provider"
_ALLOWED_FIELDS = ("base_url", "model", "endpoint_class", "credential_env")
DEFAULT_CREDENTIAL_ENV = "AGENT_OS_PROVIDER_KEY"


def config_path() -> Path:
    override = os.environ.get("AGENT_OS_PROVIDER_CONFIG")
    return Path(override) if override else DEFAULT_CONFIG_PATH


def load_provider_config() -> dict[str, str] | None:
    """Load the persisted non-secret provider config, or None if absent/invalid."""

    try:
        raw = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    config = {
        field: str(raw[field])
        for field in _ALLOWED_FIELDS
        if isinstance(raw.get(field), str) and str(raw.get(field))
    }
    if not config.get("base_url") or not config.get("model"):
        return None
    return config


def save_provider_config(config: dict[str, str]) -> None:
    """Atomically persist the non-secret provider config (0600).

    Any credential value passed in ``config`` is dropped: only allowlisted,
    non-secret fields are written.
    """

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        field: str(config[field])
        for field in _ALLOWED_FIELDS
        if config.get(field)
    }
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    handle, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".provider-", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(encoded)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


class KeychainCredentialStore:
    """OS keychain secret store (macOS ``security``) with an env fallback.

    NOTE: ``security add-generic-password -w`` passes the secret as an argv,
    briefly visible to same-user processes. Callers that require zero argv
    exposure should rely on the environment-variable fallback until a
    keyring-backed store replaces this.
    """

    def __init__(self, service: str = KEYCHAIN_SERVICE) -> None:
        self.service = service

    def available(self) -> bool:
        return (
            sys.platform == "darwin" and shutil.which("security") is not None
        )

    def store(self, account: str, secret: str) -> bool:
        if not self.available() or not account or not secret:
            return False
        result = subprocess.run(
            [
                "security",
                "add-generic-password",
                "-a",
                account,
                "-s",
                self.service,
                "-w",
                secret,
                "-U",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0

    def load(self, account: str) -> str | None:
        if not self.available() or not account:
            return None
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a",
                account,
                "-s",
                self.service,
                "-w",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def delete(self, account: str) -> None:
        if not self.available() or not account:
            return
        subprocess.run(
            [
                "security",
                "delete-generic-password",
                "-a",
                account,
                "-s",
                self.service,
            ],
            capture_output=True,
            text=True,
            check=False,
        )


def resolve_provider_key(
    credential_env: str,
    *,
    account: str = DEFAULT_CREDENTIAL_ENV,
    keychain: KeychainCredentialStore | None = None,
) -> tuple[str | None, str]:
    """Resolve the API key from the keychain first, then the environment.

    Returns (key, source) where source is one of "keychain", "env", "none".
    """

    store = keychain or KeychainCredentialStore()
    from_keychain = store.load(account)
    if from_keychain:
        return from_keychain, "keychain"
    from_env = os.environ.get(credential_env) or os.environ.get(
        DEFAULT_CREDENTIAL_ENV
    )
    if from_env:
        return from_env, "env"
    return None, "none"
