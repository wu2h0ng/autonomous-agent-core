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


def _context(**overrides: object) -> AgentRunContext:
    values = {
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "principal_id": "user-1",
        "principal_role": "analyst",
        "run_id": "budget-run",
        "trace_id": "trace-1",
        "policy_scope": frozenset({"tool:read"}),
    }
    values.update(overrides)
    return AgentRunContext(**values)


class AgentRuntimeBudgetTest(unittest.TestCase):
    def test_tool_call_budget_denies_second_call_before_tool_body(self) -> None:
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
        trace_writer = AgentTraceWriter()
        runtime = AgentRuntime(
            tools=registry,
            policy_gate=RuntimePolicyGate(),
            trace_writer=trace_writer,
        )
        context = _context(max_tool_calls=1)

        first = runtime.invoke_tool(
            AgentToolCall(call_id="call-1", tool_name="safe.echo", args={"value": "a"}),
            context,
        )
        second = runtime.invoke_tool(
            AgentToolCall(call_id="call-2", tool_name="safe.echo", args={"value": "b"}),
            context,
        )

        self.assertEqual(first.status, "ok")
        self.assertEqual(second.status, "denied")
        self.assertEqual(second.error_code, "DENY_TOOL_CALL_BUDGET_EXCEEDED")
        self.assertEqual(called, ["a"])
        self.assertIn(
            {
                "step": "agent_runtime.budget_denied",
                "payload": {
                    "call_id": "call-2",
                    "tool_name": "safe.echo",
                    "trace_id": "trace-1",
                    "run_id": "budget-run",
                    "error_code": "DENY_TOOL_CALL_BUDGET_EXCEEDED",
                },
            },
            trace_writer.events,
        )

    def test_invalid_budget_denies_before_tool_body(self) -> None:
        called: list[str] = []
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(name="safe.echo", description="Echo payload."),
            lambda *, context: called.append("called") or {"ok": True},
        )
        runtime = AgentRuntime(tools=registry, policy_gate=RuntimePolicyGate())

        result = runtime.invoke_tool(
            AgentToolCall(call_id="call-invalid-budget", tool_name="safe.echo"),
            _context(max_tool_calls=0),
        )

        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "DENY_INVALID_BUDGET")
        self.assertEqual(called, [])

    def test_timeout_ceiling_denies_tool_with_larger_declared_timeout(self) -> None:
        called: list[str] = []
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                name="slow.read",
                description="Slow read.",
                required_permissions=("tool:read",),
                timeout_ms=2_000,
            ),
            lambda *, context: called.append("called") or {"ok": True},
        )
        runtime = AgentRuntime(tools=registry, policy_gate=RuntimePolicyGate())

        result = runtime.invoke_tool(
            AgentToolCall(call_id="call-timeout", tool_name="slow.read"),
            _context(tool_timeout_ceiling_ms=1_000),
        )

        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "DENY_TIMEOUT_BUDGET")
        self.assertEqual(called, [])

    def test_timeout_ceiling_requires_declared_tool_timeout(self) -> None:
        called: list[str] = []
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                name="unknown_timeout.read",
                description="Read with unspecified runtime.",
                required_permissions=("tool:read",),
            ),
            lambda *, context: called.append("called") or {"ok": True},
        )
        runtime = AgentRuntime(tools=registry, policy_gate=RuntimePolicyGate())

        result = runtime.invoke_tool(
            AgentToolCall(call_id="call-timeout-required", tool_name="unknown_timeout.read"),
            _context(tool_timeout_ceiling_ms=1_000),
        )

        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "DENY_TIMEOUT_BUDGET")
        self.assertEqual(called, [])

    def test_cost_budget_is_consumed_per_successful_runtime_start(self) -> None:
        called: list[str] = []
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                name="costly.read",
                description="Costly read.",
                required_permissions=("tool:read",),
                estimated_cost_units=3,
            ),
            lambda *, context: called.append(context.run_id) or {"ok": True},
        )
        runtime = AgentRuntime(tools=registry, policy_gate=RuntimePolicyGate())
        context = _context(cost_budget_units=5)

        first = runtime.invoke_tool(
            AgentToolCall(call_id="cost-1", tool_name="costly.read"),
            context,
        )
        second = runtime.invoke_tool(
            AgentToolCall(call_id="cost-2", tool_name="costly.read"),
            context,
        )

        self.assertEqual(first.status, "ok")
        self.assertEqual(second.status, "denied")
        self.assertEqual(second.error_code, "DENY_COST_BUDGET_EXCEEDED")
        self.assertEqual(called, ["budget-run"])


if __name__ == "__main__":
    unittest.main()
