"""Unit tests for API-layer MCP transport adapters."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api_server" / "src"))

from agent_os_api.mcp_transport import McpTransportRegistry, McpTransportRejected  # noqa: E402


class McpTransportRegistryTest(unittest.TestCase):
    def test_default_transport_is_noop_handler(self) -> None:
        transport = McpTransportRegistry().handler_for(
            tool_id="tool-1",
            body={},
        )

        self.assertEqual(transport.transport, "noop")
        self.assertEqual(
            transport.handler(metric="gmv"),
            {
                "status": "noop",
                "transport": "noop",
                "tool_id": "tool-1",
                "input": {"metric": "gmv"},
            },
        )

    def test_unknown_transport_rejected(self) -> None:
        with self.assertRaises(McpTransportRejected) as cm:
            McpTransportRegistry().handler_for(
                tool_id="tool-1",
                body={"transport": "sse"},
            )
        self.assertEqual(cm.exception.code, "UNKNOWN_TRANSPORT")

    def test_stdio_disabled_by_default(self) -> None:
        with self.assertRaises(McpTransportRejected) as cm:
            McpTransportRegistry().handler_for(
                tool_id="tool-1",
                body={"transport": "stdio", "stdio": {"command": "python"}},
            )
        self.assertEqual(cm.exception.code, "STDIO_TRANSPORT_DISABLED")

    def test_stdio_allowlist_returns_non_executing_placeholder(self) -> None:
        transport = McpTransportRegistry(
            stdio_enabled=True,
            allowed_stdio_commands=("agent-os-mcp-safe",),
        ).handler_for(
            tool_id="tool-1",
            body={"transport": "stdio", "stdio": {"command": "agent-os-mcp-safe"}},
        )

        self.assertEqual(transport.transport, "stdio")
        self.assertEqual(
            transport.handler(metric="gmv"),
            {
                "status": "not_executed",
                "transport": "stdio",
                "tool_id": "tool-1",
                "command": "agent-os-mcp-safe",
                "input": {"metric": "gmv"},
            },
        )


if __name__ == "__main__":
    unittest.main()
