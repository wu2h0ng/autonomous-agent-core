"""Private runtime descriptor schema and loading for the local daemon.

The descriptor is the CLI's only route into daemon-owned state: it carries the
loopback URL, process identity, and the local bearer token. Provider keys are
never stored here — they remain environment-resolved by the daemon process.
"""

from __future__ import annotations

import json
import os
import secrets
import uuid
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from agent_os_contracts import (
    ContractModel,
    NonEmptyStr,
    SurfaceProtocolVersion,
    UtcDateTime,
    canonical_json,
)


class RuntimeDescriptorError(ValueError):
    """The runtime descriptor is missing, malformed, or unsafe."""


class RuntimeDescriptor(ContractModel):
    protocol_version: SurfaceProtocolVersion
    pid: int = Field(gt=0)
    boot_id: NonEmptyStr
    host: Literal["127.0.0.1"]
    port: int = Field(ge=1, le=65535)
    bearer_token: NonEmptyStr
    database_path: NonEmptyStr
    workspace_path: NonEmptyStr
    created_at: UtcDateTime

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def generate_runtime_token() -> str:
    """One random 256-bit local bearer token (url-safe base64)."""

    return secrets.token_urlsafe(32)


def generate_boot_id() -> str:
    """One unique daemon boot identity."""

    return f"boot:{uuid.uuid4()}"


def load_runtime_descriptor(path: Path) -> RuntimeDescriptor:
    """Parse and validate one private runtime descriptor file."""

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeDescriptorError(
            f"cannot read runtime descriptor {path}"
        ) from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeDescriptorError(
            f"runtime descriptor {path} is not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise RuntimeDescriptorError("runtime descriptor must be a JSON object")
    try:
        return RuntimeDescriptor.model_validate(value)
    except ValidationError as exc:
        raise RuntimeDescriptorError(
            f"runtime descriptor {path} has an invalid schema"
        ) from exc


def write_descriptor(path: Path, descriptor: RuntimeDescriptor) -> None:
    """Atomically persist one private descriptor at mode 0600."""

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise RuntimeDescriptorError("runtime descriptor cannot be a symlink")
    temporary = path.with_name(path.name + f".{descriptor.boot_id}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(temporary, flags, 0o600)
    try:
        os.write(fd, canonical_json(descriptor).encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)
