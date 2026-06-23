from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (
    ROOT / "packages" / "contracts" / "src",
    ROOT / "packages" / "os_core" / "src",
):
    sys.path.insert(0, str(_p))

from agent_os_core.agent_runtime import (  # noqa: E402
    AgentRunContext,
    AgentRuntime,
    AgentToolCall,
    AgentTraceWriter,
    RuntimePolicyGate,
    ToolRegistry,
    ToolSpec,
)
from agent_os_core.corrigibility import CorrigibilityShell  # noqa: E402


def _context(**overrides: object) -> AgentRunContext:
    values = {
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "principal_id": "user-1",
        "principal_role": "analyst",
        "run_id": "run-1",
        "trace_id": "trace-1",
        "policy_scope": frozenset({"tool:read"}),
    }
    values.update(overrides)
    return AgentRunContext(**values)


class AgentRuntimePolicyTest(unittest.TestCase):
    def test_missing_principal_is_denied_before_tool_body(self) -> None:
        called: list[str] = []
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                name="safe.echo",
                description="Echo payload.",
                required_keys=("value",),
                required_permissions=("tool:read",),
            ),
            lambda *, value, context: called.append(value) or {"value": value},
        )
        runtime = AgentRuntime(
            tools=registry,
            policy_gate=RuntimePolicyGate(),
            trace_writer=AgentTraceWriter(),
        )

        result = runtime.invoke_tool(
            AgentToolCall(call_id="call-1", tool_name="safe.echo", args={"value": "x"}),
            _context(principal_id=""),
        )

        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "DENY_INVALID_CONTEXT")
        self.assertEqual(called, [])

    def test_missing_permission_is_denied_before_tool_body(self) -> None:
        called: list[str] = []
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                name="safe.echo",
                description="Echo payload.",
                required_keys=("value",),
                required_permissions=("tool:admin",),
            ),
            lambda *, value, context: called.append(value) or {"value": value},
        )
        runtime = AgentRuntime(tools=registry, policy_gate=RuntimePolicyGate())

        result = runtime.invoke_tool(
            AgentToolCall(call_id="call-2", tool_name="safe.echo", args={"value": "x"}),
            _context(policy_scope=frozenset({"tool:read"})),
        )

        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "DENY_MISSING_PERMISSION")
        self.assertEqual(called, [])

    def test_paused_shell_denies_execution_and_audits_refusal(self) -> None:
        called: list[str] = []
        shell = CorrigibilityShell()
        shell.op_pause()
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                name="safe.echo",
                description="Echo payload.",
                required_keys=("value",),
                required_permissions=("tool:read",),
            ),
            lambda *, value, context: called.append(value) or {"value": value},
        )
        runtime = AgentRuntime(
            tools=registry,
            policy_gate=RuntimePolicyGate(shell_view=shell.view()),
        )

        result = runtime.invoke_tool(
            AgentToolCall(call_id="call-3", tool_name="safe.echo", args={"value": "x"}),
            _context(),
        )

        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "DENY_PAUSED")
        self.assertEqual(called, [])
        self.assertTrue(shell.audit.verify())
        self.assertEqual(
            [entry.payload["event"] for entry in shell.audit.entries()],
            ["pause", "agent_runtime_refused_paused"],
        )

    def test_tool_requiring_approval_is_denied_without_approval_id(self) -> None:
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                name="action.write",
                description="Side-effecting action.",
                required_keys=("value",),
                required_permissions=("tool:write",),
                side_effect_class="external_write",
                requires_approval=True,
            ),
            lambda *, value, context: {"value": value},
        )
        runtime = AgentRuntime(tools=registry, policy_gate=RuntimePolicyGate())

        result = runtime.invoke_tool(
            AgentToolCall(call_id="call-4", tool_name="action.write", args={"value": "x"}),
            _context(policy_scope=frozenset({"tool:write"})),
        )

        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "DENY_REQUIRES_APPROVAL")

    def test_r4_tool_is_denied_without_approval_even_without_tool_opt_in(self) -> None:
        called: list[str] = []
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                name="action.r4",
                description="High-risk action.",
                required_keys=("value",),
                risk_level="R4",
                required_permissions=("tool:write",),
            ),
            lambda *, value, context: called.append(value) or {"value": value},
        )
        runtime = AgentRuntime(tools=registry, policy_gate=RuntimePolicyGate())

        result = runtime.invoke_tool(
            AgentToolCall(call_id="call-r4", tool_name="action.r4", args={"value": "x"}),
            _context(policy_scope=frozenset({"tool:write"})),
        )

        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "DENY_REQUIRES_APPROVAL")
        self.assertEqual(called, [])

    def test_side_effecting_tool_is_denied_without_approval_even_at_lower_risk(self) -> None:
        called: list[str] = []
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                name="action.write",
                description="Side-effecting action.",
                required_keys=("value",),
                risk_level="R2",
                side_effect_class="external_write",
                required_permissions=("tool:write",),
            ),
            lambda *, value, context: called.append(value) or {"value": value},
        )
        runtime = AgentRuntime(tools=registry, policy_gate=RuntimePolicyGate())

        result = runtime.invoke_tool(
            AgentToolCall(
                call_id="call-side-effect", tool_name="action.write", args={"value": "x"}
            ),
            _context(policy_scope=frozenset({"tool:write"})),
        )

        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "DENY_REQUIRES_APPROVAL")
        self.assertEqual(called, [])

    def test_r5_side_effecting_tool_can_run_with_approval_id(self) -> None:
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                name="action.r5",
                description="Approved high-risk action.",
                required_keys=("value",),
                risk_level="R5",
                side_effect_class="external_write",
                required_permissions=("tool:write",),
            ),
            lambda *, value, context: {"value": value, "approval_id": context.approval_id},
        )
        runtime = AgentRuntime(tools=registry, policy_gate=RuntimePolicyGate())

        result = runtime.invoke_tool(
            AgentToolCall(call_id="call-r5", tool_name="action.r5", args={"value": "x"}),
            _context(policy_scope=frozenset({"tool:write"}), approval_id="approval-1"),
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.output, {"value": "x", "approval_id": "approval-1"})


if __name__ == "__main__":
    unittest.main()
