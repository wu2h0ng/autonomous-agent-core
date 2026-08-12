"""Private runtime descriptor schema and loading for the local daemon.

The descriptor is the CLI's only route into daemon-owned state: it carries the
loopback URL, process identity, and the local bearer token. Provider keys are
never stored here — they remain environment-resolved by the daemon process.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from agent_os_contracts import ContractModel, NonEmptyStr, UtcDateTime


class RuntimeDescriptorError(ValueError):
    """The runtime descriptor is missing, malformed, or unsafe."""


class RuntimeDescriptor(ContractModel):
    protocol_version: Literal["1.0"]
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
    return RuntimeDescriptor.model_validate(value)
