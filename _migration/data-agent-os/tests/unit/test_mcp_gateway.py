from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))

from agent_os_contracts import McpServerRegistration, McpToolContract  # noqa: E402


class McpGatewayContractsTest(unittest.TestCase):
    def test_mcp_server_registration(self) -> None:
        server = McpServerRegistration(
            server_id="mcp-1",
            name="Analytics",
            transport_url="http://localhost:8080/sse",
            owner="platform",
            tenant_id="tenant-1",
            allowed_scopes=("read_metrics",),
            risk_ceiling="R2",
            state="active",
        )
        self.assertEqual(server.state, "active")
        self.assertEqual(server.risk_ceiling, "R2")

    def test_mcp_tool_contract(self) -> None:
        tool = McpToolContract(
            tool_id="tool-1",
            server_id="mcp-1",
            name="query",
            description="Query a metric.",
            input_schema={"type": "object"},
            risk_level="R2",
            dry_run_supported=True,
        )
        self.assertEqual(tool.server_id, "mcp-1")
        self.assertTrue(tool.dry_run_supported)


if __name__ == "__main__":
    unittest.main()
