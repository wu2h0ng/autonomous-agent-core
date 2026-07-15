"""Read-only external C7 stop-capability adapter.

The actor never receives this adapter or its capability token.  A distinct C7
owner atomically creates the stop file.  This module only validates and reads
that signal; it cannot mint authority or write the stop file.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from experiments.r_state_credit_1.contracts import canonical_json


_SCHEMA_VERSION = "r-state-credit-1-c7-stop-v1"
_FIELDS = {
    "abort_requested",
    "capability_token_sha256",
    "epoch",
    "owner_id",
    "reason_code",
    "schema_version",
}


class C7SignalViolation(RuntimeError):
    """Raised when an existing C7 signal cannot be trusted."""


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise C7SignalViolation(f"{name} must be non-empty text")
    return value


def _require_sha256(name: str, value: object) -> str:
    text = _require_text(name, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise C7SignalViolation(f"{name} must be a lowercase SHA-256 digest")
    return text


def _read_stable_regular_file(path: Path) -> bytes:
    if path.is_symlink():
        raise C7SignalViolation("C7 stop file must not be a symlink")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise C7SignalViolation("C7 stop file cannot be opened safely") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise C7SignalViolation("C7 stop file must be a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if identity_before != identity_after:
            raise C7SignalViolation("C7 stop file changed while being read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


class AtomicStopFileC7:
    """Validate an owner/epoch/token-bound atomic stop signal."""

    __slots__ = (
        "owner_id",
        "epoch",
        "stop_path",
        "capability_token_sha256",
        "_capability_token",
    )

    def __init__(
        self,
        *,
        owner_id: str,
        epoch: str,
        stop_path: Path,
        capability_token: str,
    ) -> None:
        self.owner_id = _require_text("owner_id", owner_id)
        self.epoch = _require_text("epoch", epoch)
        if not isinstance(stop_path, Path):
            raise C7SignalViolation("stop_path must be Path")
        token = _require_text("capability_token", capability_token)
        self.stop_path = stop_path
        self._capability_token = token
        self.capability_token_sha256 = hashlib.sha256(token.encode("utf-8")).hexdigest()

    def __repr__(self) -> str:
        return (
            "AtomicStopFileC7("
            f"owner_id={self.owner_id!r}, epoch={self.epoch!r}, "
            f"stop_path={self.stop_path!r}, "
            f"capability_token_sha256={self.capability_token_sha256!r})"
        )

    def abort_requested(self) -> bool:
        try:
            raw = _read_stable_regular_file(self.stop_path)
        except FileNotFoundError:
            return False
        try:
            payload: Any = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise C7SignalViolation("C7 stop file is not valid JSON") from exc
        if not isinstance(payload, dict) or set(payload) != _FIELDS:
            raise C7SignalViolation("C7 stop file schema drift")
        if raw != (canonical_json(payload) + "\n").encode("utf-8"):
            raise C7SignalViolation("C7 stop file is not canonical atomic content")
        if payload["schema_version"] != _SCHEMA_VERSION:
            raise C7SignalViolation("C7 stop file schema version drift")
        if payload["owner_id"] != self.owner_id:
            raise C7SignalViolation("C7 owner identity drift")
        if payload["epoch"] != self.epoch:
            raise C7SignalViolation("C7 epoch drift")
        token_digest = _require_sha256(
            "capability_token_sha256", payload["capability_token_sha256"]
        )
        if token_digest != self.capability_token_sha256:
            raise C7SignalViolation("C7 capability token drift")
        _require_text("reason_code", payload["reason_code"])
        if payload["abort_requested"] is not True:
            raise C7SignalViolation("existing C7 stop file must request abort")
        return True
