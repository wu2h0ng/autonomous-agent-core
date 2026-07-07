"""C/D/E integration: factory.build() and agent-runtime wiring (ADR-0013).

Proves staged-out engines are reachable from the real HTTP composition path:
- E/D: ``factory.build()`` injects ``approval_router`` when flags are on.
- C: ``build_mcp_gateway()`` + ``build_agent_runtime_adapter()`` attach MCP tools.
Default flags off → MVP behavior unchanged.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api_server" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))

from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig  # noqa: E402
from agent_os_contracts import McpServerRegistration, McpToolContract  # noqa: E402
from agent_os_core.mcp_gateway import McpGatewayRegistry  # noqa: E402

DOMAIN_PACK = ROOT / "domain_packs" / "content_commerce"


class RuntimeFactoryCDEIntegrationTest(unittest.TestCase):
    def _factory(self, env: dict[str, str] | None = None) -> ContentCommerceRuntimeFactory:
        cfg = RuntimeFactoryConfig.from_env(env or {})
        cfg = RuntimeFactoryConfig(
            domain_pack_path=DOMAIN_PACK,
            r4_r5_auto_execution=cfg.r4_r5_auto_execution,
            full_bpm_workflow=cfg.full_bpm_workflow,
            mcp_gateway=cfg.mcp_gateway,
        )
        return ContentCommerceRuntimeFactory(cfg)

    def test_build_has_no_approval_router_when_flags_off(self) -> None:
        runtime = self._factory({}).build()
        self.assertIsNone(runtime.approval_router)

    def test_build_injects_approval_router_when_r4_r5_flag_on(self) -> None:
        runtime = self._factory({"AGENT_OS_R4_R5_AUTO_EXECUTION": "true"}).build()
        self.assertIsNotNone(runtime.approval_router)
        self.assertIsNotNone(runtime.approval_router._policy_engine)

    def test_build_injects_approval_router_when_bpm_flag_on(self) -> None:
        runtime = self._factory({"AGENT_OS_FULL_BPM_WORKFLOW": "true"}).build()
        self.assertIsNotNone(runtime.approval_router)
        self.assertIsNotNone(runtime.approval_router._workflow_runtime)

    def test_build_mcp_gateway_none_when_flag_off(self) -> None:
        self.assertIsNone(self._factory({}).build_mcp_gateway())

    def test_build_mcp_gateway_returns_router_when_flag_on(self) -> None:
        router = self._factory({"AGENT_OS_MCP_GATEWAY": "true"}).build_mcp_gateway()
        self.assertIsNotNone(router)
        self.assertTrue(router.feature_flags.mcp_gateway)

    def test_agent_runtime_adapter_attaches_mcp_tools_when_flag_on(self) -> None:
        factory = self._factory({"AGENT_OS_MCP_GATEWAY": "true"})
        runtime = factory.build()
        mcp_router = factory.build_mcp_gateway()
        assert mcp_router is not None
        reg: McpGatewayRegistry = mcp_router.registry
        reg.register_server(
            McpServerRegistration(
                server_id="srv-1",
                name="Demo",
                transport_url="http://localhost/sse",
                owner="platform",
                tenant_id="default",
                allowed_scopes=("read_metrics",),
                risk_ceiling="R3",
                state="pending",
            )
        )
        reg.activate_server("srv-1")
        reg.register_tool(
            McpToolContract(
                tool_id="demo_tool",
                server_id="srv-1",
                name="Demo Tool",
                description="demo",
                input_schema={"type": "object"},
                risk_level="R1",
                dry_run_supported=True,
            ),
            handler=lambda **kw: {"ok": True},
        )
        adapter = factory.build_agent_runtime_adapter(runtime, mcp_router=mcp_router)
        self.assertIsNotNone(adapter.runtime.tools.spec_for("demo_tool"))

    def test_mcp_flag_alone_does_not_inject_approval_router(self) -> None:
        runtime = self._factory({"AGENT_OS_MCP_GATEWAY": "true"}).build()
        self.assertIsNone(runtime.approval_router)


if __name__ == "__main__":
    unittest.main()
