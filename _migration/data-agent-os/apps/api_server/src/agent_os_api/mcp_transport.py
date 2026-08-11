"""Composition-layer MCP transport adapters.

OS Core owns MCP registration, policy checks, and routing. This module owns the
concrete transport boundary for the API composition layer and deliberately keeps
stdio fail-closed unless a caller injects an allowlist-enabled registry.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any


McpHandler = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class McpTransportHandler:
    transport: str
    handler: McpHandler
    descriptor: dict[str, Any]


class McpTransportRejected(Exception):
    """Raised when a requested MCP transport is not allowed in this process."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class McpTransportRegistry:
    """Build per-tool handlers for API-owned MCP transports."""

    _NOOP_ALIASES = frozenset({"noop", "in_process", "in-process", "inprocess"})

    def __init__(
        self,
        *,
        stdio_enabled: bool = False,
        allowed_stdio_commands: Iterable[str] = (),
    ) -> None:
        self._stdio_enabled = stdio_enabled
        self._allowed_stdio_commands = frozenset(allowed_stdio_commands)

    def handler_for(self, *, tool_id: str, body: dict[str, Any]) -> McpTransportHandler:
        transport = self._normalize_transport(body.get("transport"))
        if transport in self._NOOP_ALIASES:
            normalized = "noop" if transport == "noop" else "in_process"
            return McpTransportHandler(
                transport=normalized,
                handler=self._noop_handler(tool_id=tool_id, transport=normalized),
                descriptor={"type": normalized},
            )
        if transport == "stdio":
            return self._stdio_handler(tool_id=tool_id, body=body)
        raise McpTransportRejected(
            "UNKNOWN_TRANSPORT",
            f"Unknown MCP transport {transport!r}.",
        )

    def _normalize_transport(self, value: Any) -> str:
        if value is None or value == "":
            return "noop"
        return str(value).strip().lower().replace(" ", "_")

    def _noop_handler(self, *, tool_id: str, transport: str) -> McpHandler:
        def _handler(**kwargs: Any) -> dict[str, Any]:
            return {
                "status": "noop",
                "transport": transport,
                "tool_id": tool_id,
                "input": dict(kwargs),
            }

        return _handler

    def _stdio_handler(self, *, tool_id: str, body: dict[str, Any]) -> McpTransportHandler:
        descriptor = body.get("stdio")
        if not isinstance(descriptor, dict):
            descriptor = {}
        command = str(descriptor.get("command") or body.get("command") or "").strip()
        if not self._stdio_enabled:
            raise McpTransportRejected(
                "STDIO_TRANSPORT_DISABLED",
                "stdio MCP transport is disabled by default.",
            )
        if not command or command not in self._allowed_stdio_commands:
            raise McpTransportRejected(
                "STDIO_COMMAND_NOT_ALLOWED",
                "stdio MCP command is not in the allowlist.",
            )

        def _handler(**kwargs: Any) -> dict[str, Any]:
            return {
                "status": "not_executed",
                "transport": "stdio",
                "tool_id": tool_id,
                "command": command,
                "input": dict(kwargs),
            }

        return McpTransportHandler(
            transport="stdio",
            handler=_handler,
            descriptor={"type": "stdio", "command": command},
        )


__all__ = [
    "McpHandler",
    "McpTransportHandler",
    "McpTransportRegistry",
    "McpTransportRejected",
]
