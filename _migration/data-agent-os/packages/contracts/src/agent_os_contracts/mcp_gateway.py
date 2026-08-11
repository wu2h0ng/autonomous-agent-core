from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class McpServerRegistration:
    server_id: str
    name: str
    transport_url: str
    owner: str
    tenant_id: str
    allowed_scopes: tuple[str, ...]
    risk_ceiling: str
    state: str = "pending"  # "pending" | "active" | "suspended"


@dataclass(frozen=True)
class McpToolContract:
    tool_id: str
    server_id: str
    name: str
    description: str
    input_schema: dict[str, Any]
    risk_level: str
    dry_run_supported: bool


__all__ = [
    "McpServerRegistration",
    "McpToolContract",
]
