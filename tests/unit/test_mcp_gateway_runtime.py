"""Test-first unit tests for the MCP Gateway runtime (workstream C).

These tests define the contract of the OS Core MCP Gateway before the
implementation exists. They exercise server lifecycle, tool risk-ceiling
validation, feature-flag gating, tenant/scope/pause enforcement on
invocation, and the audit trail. Concrete MCP transports live outside OS
Core and are injected as handler callables.
"""

from __future__ import annotations

import unittest

from agent_os_contracts import (
    McpServerRegistration,
    McpToolContract,
    RuntimeFeatureFlags,
)
from agent_os_core import CorrigibilityShell
from agent_os_core.agent_runtime import AgentRunContext, ToolRegistry
from agent_os_core.mcp_gateway import (
    McpGatewayRegistry,
    McpToolDenied,
    McpToolRouter,
)


def _ctx(
    *,
    tenant_id: str = "tenant-1",
    policy_scope: tuple[str, ...] = ("read_metrics",),
    risk_ceiling: str = "R5",
    trace_id: str = "trace-1",
) -> AgentRunContext:
    return AgentRunContext(
        tenant_id=tenant_id,
        workspace_id="ws-1",
        trace_id=trace_id,
        principal_id="principal-1",
        principal_role="operator",
        run_id="run-1",
        policy_scope=frozenset(policy_scope),
        risk_ceiling=risk_ceiling,
    )


def _server(
    server_id: str = "mcp-1",
    *,
    risk_ceiling: str = "R3",
    scopes: tuple[str, ...] = ("read_metrics",),
    state: str = "pending",
    tenant_id: str = "tenant-1",
) -> McpServerRegistration:
    return McpServerRegistration(
        server_id=server_id,
        name="Analytics",
        transport_url="http://localhost:8080/sse",
        owner="platform",
        tenant_id=tenant_id,
        allowed_scopes=scopes,
        risk_ceiling=risk_ceiling,
        state=state,
    )


def _tool(
    tool_id: str = "tool-1",
    *,
    server_id: str = "mcp-1",
    risk_level: str = "R2",
    dry_run_supported: bool = True,
) -> McpToolContract:
    return McpToolContract(
        tool_id=tool_id,
        server_id=server_id,
        name="query_metric",
        description="Query a metric.",
        input_schema={"type": "object"},
        risk_level=risk_level,
        dry_run_supported=dry_run_supported,
    )


class McpGatewayRegistryTest(unittest.TestCase):
    def test_register_server_defaults_pending(self) -> None:
        reg = McpGatewayRegistry()
        reg.register_server(_server())
        self.assertEqual(reg.server_for("mcp-1").state, "pending")

    def test_activate_and_suspend_lifecycle(self) -> None:
        reg = McpGatewayRegistry()
        reg.register_server(_server())
        reg.activate_server("mcp-1")
        self.assertEqual(reg.server_for("mcp-1").state, "active")
        reg.suspend_server("mcp-1")
        self.assertEqual(reg.server_for("mcp-1").state, "suspended")

    def test_register_tool_requires_active_server(self) -> None:
        reg = McpGatewayRegistry()
        reg.register_server(_server())  # pending
        with self.assertRaises(ValueError):
            reg.register_tool(_tool(), handler=lambda **kw: {"ok": True})

    def test_register_tool_rejects_risk_above_server_ceiling(self) -> None:
        reg = McpGatewayRegistry()
        reg.register_server(_server(risk_ceiling="R2"))
        reg.activate_server("mcp-1")
        with self.assertRaises(ValueError):
            reg.register_tool(_tool(risk_level="R4"), handler=lambda **kw: {})

    def test_active_tools_lists_only_active_server_tools(self) -> None:
        reg = McpGatewayRegistry()
        reg.register_server(_server())
        reg.activate_server("mcp-1")
        reg.register_server(_server("mcp-2", scopes=("read_other",)))
        # mcp-2 stays pending; its tool must not be registerable
        with self.assertRaises(ValueError):
            reg.register_tool(_tool("tool-2", server_id="mcp-2"), handler=lambda **kw: {})
        reg.register_tool(_tool(), handler=lambda **kw: {"value": 1})
        ids = {t.tool_id for t in reg.active_tools()}
        self.assertEqual(ids, {"tool-1"})


class McpToolRouterFeatureFlagTest(unittest.TestCase):
    def test_flag_off_attaches_no_tools(self) -> None:
        reg = McpGatewayRegistry()
        reg.register_server(_server())
        reg.activate_server("mcp-1")
        reg.register_tool(_tool(), handler=lambda **kw: {"v": 1})
        router = McpToolRouter(reg, RuntimeFeatureFlags())  # all flags False
        tools = ToolRegistry()
        router.attach(tools)
        with self.assertRaises(KeyError):
            tools.spec_for("tool-1")

    def test_flag_off_invoke_denied(self) -> None:
        reg = McpGatewayRegistry()
        reg.register_server(_server())
        reg.activate_server("mcp-1")
        reg.register_tool(_tool(), handler=lambda **kw: {"v": 1})
        router = McpToolRouter(reg, RuntimeFeatureFlags())
        result = router.invoke("tool-1", _ctx(), metric="gmv")
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "feature_disabled")


class McpToolRouterInvocationTest(unittest.TestCase):
    def _setup(self) -> McpToolRouter:
        reg = McpGatewayRegistry()
        reg.register_server(_server())
        reg.activate_server("mcp-1")
        reg.register_tool(_tool(), handler=lambda **kw: {"value": kw.get("metric")})
        flags = RuntimeFeatureFlags(mcp_gateway=True)
        return McpToolRouter(reg, flags)

    def test_invoke_allowed_returns_output(self) -> None:
        router = self._setup()
        result = router.invoke("tool-1", _ctx(), metric="gmv")
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.output, {"value": "gmv"})

    def test_invoke_denied_suspended_server(self) -> None:
        router = self._setup()
        router.registry.suspend_server("mcp-1")
        result = router.invoke("tool-1", _ctx(), metric="gmv")
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "server_not_active")

    def test_invoke_denied_tenant_mismatch(self) -> None:
        router = self._setup()
        result = router.invoke("tool-1", _ctx(tenant_id="tenant-2"), metric="gmv")
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "tenant_mismatch")

    def test_invoke_denied_scope_mismatch(self) -> None:
        reg = McpGatewayRegistry()
        reg.register_server(_server(scopes=("read_metrics",)))
        reg.activate_server("mcp-1")
        reg.register_tool(_tool(), handler=lambda **kw: {})
        router = McpToolRouter(reg, RuntimeFeatureFlags(mcp_gateway=True))
        result = router.invoke("tool-1", _ctx(policy_scope=("write_things",)), metric="gmv")
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "scope_denied")

    def test_invoke_denied_when_paused(self) -> None:
        router = self._setup()
        shell = CorrigibilityShell()
        shell.op_pause()
        router = McpToolRouter(router.registry, router.feature_flags, shell=shell)
        result = router.invoke("tool-1", _ctx(), metric="gmv")
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "paused")

    def test_invoke_denied_context_risk_ceiling(self) -> None:
        reg = McpGatewayRegistry()
        reg.register_server(_server(risk_ceiling="R5"))
        reg.activate_server("mcp-1")
        reg.register_tool(_tool(risk_level="R4"), handler=lambda **kw: {})
        router = McpToolRouter(reg, RuntimeFeatureFlags(mcp_gateway=True))
        result = router.invoke("tool-1", _ctx(risk_ceiling="R2"), metric="gmv")
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "risk_exceeds_context_ceiling")

    def test_invoke_tool_error_on_handler_exception(self) -> None:
        reg = McpGatewayRegistry()
        reg.register_server(_server())
        reg.activate_server("mcp-1")

        def boom(**kw):  # noqa: ANN003
            raise RuntimeError("transport down")

        reg.register_tool(_tool(), handler=boom)
        router = McpToolRouter(reg, RuntimeFeatureFlags(mcp_gateway=True))
        result = router.invoke("tool-1", _ctx(), metric="gmv")
        self.assertEqual(result.status, "tool_error")


class McpToolRouterAuditTest(unittest.TestCase):
    def test_audit_records_allowed_and_denied(self) -> None:
        reg = McpGatewayRegistry()
        reg.register_server(_server())
        reg.activate_server("mcp-1")
        reg.register_tool(_tool(), handler=lambda **kw: {"v": 1})
        router = McpToolRouter(reg, RuntimeFeatureFlags(mcp_gateway=True))
        router.invoke("tool-1", _ctx(), metric="gmv")
        router.invoke("tool-1", _ctx(tenant_id="tenant-2"), metric="gmv")
        entries = router.audit_entries()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].decision, "allowed")
        self.assertEqual(entries[1].decision, "denied")
        self.assertEqual(entries[1].reason, "tenant_mismatch")


class McpToolRouterAttachTest(unittest.TestCase):
    def test_attach_registers_tool_spec_and_routes_through_runtime(self) -> None:
        reg = McpGatewayRegistry()
        reg.register_server(_server())
        reg.activate_server("mcp-1")
        reg.register_tool(_tool(), handler=lambda **kw: {"value": kw.get("metric")})
        router = McpToolRouter(reg, RuntimeFeatureFlags(mcp_gateway=True))
        tools = ToolRegistry()
        router.attach(tools)
        spec = tools.spec_for("tool-1")
        self.assertEqual(spec.risk_level, "R2")
        # wrapper delegates to handler with context plumbing
        out = tools.call("tool-1", context=_ctx(), metric="gmv")
        self.assertEqual(out, {"value": "gmv"})

    def test_attach_wrapper_denies_on_tenant_mismatch(self) -> None:
        reg = McpGatewayRegistry()
        reg.register_server(_server())
        reg.activate_server("mcp-1")
        reg.register_tool(_tool(), handler=lambda **kw: {"v": 1})
        router = McpToolRouter(reg, RuntimeFeatureFlags(mcp_gateway=True))
        tools = ToolRegistry()
        router.attach(tools)
        with self.assertRaises(McpToolDenied):
            tools.call("tool-1", context=_ctx(tenant_id="tenant-2"), metric="gmv")

    def test_r4_r5_tool_maps_to_proposal_side_effect(self) -> None:
        reg = McpGatewayRegistry()
        reg.register_server(_server(risk_ceiling="R5"))
        reg.activate_server("mcp-1")
        reg.register_tool(_tool(risk_level="R5"), handler=lambda **kw: {})
        router = McpToolRouter(reg, RuntimeFeatureFlags(mcp_gateway=True))
        tools = ToolRegistry()
        router.attach(tools)
        spec = tools.spec_for("tool-1")
        self.assertEqual(spec.side_effect_class, "proposal")
        self.assertFalse(spec.allow_when_paused)


if __name__ == "__main__":
    unittest.main()
