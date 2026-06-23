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
    RuntimePolicyGate,
    ToolRegistry,
    ToolSpec,
)


def _context() -> AgentRunContext:
    return AgentRunContext(
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        principal_id="user-1",
        principal_role="analyst",
        run_id="run-1",
        trace_id="trace-1",
        policy_scope=frozenset({"tool:read"}),
    )


class AgentRuntimeToolsTest(unittest.TestCase):
    def test_duplicate_tool_registration_fails(self) -> None:
        registry = ToolRegistry()
        spec = ToolSpec(name="safe.echo", description="Echo.", required_keys=("value",))
        registry.register_tool(spec, lambda *, value, context: {"value": value})

        with self.assertRaises(ValueError):
            registry.register_tool(spec, lambda *, value, context: {"value": value})

    def test_unknown_tool_returns_structured_failure(self) -> None:
        runtime = AgentRuntime(tools=ToolRegistry(), policy_gate=RuntimePolicyGate())

        result = runtime.invoke_tool(
            AgentToolCall(call_id="call-unknown", tool_name="missing.tool", args={}),
            _context(),
        )

        self.assertEqual(result.status, "validation_error")
        self.assertEqual(result.error_code, "TOOL_NOT_REGISTERED")

    def test_required_input_validation_blocks_tool_body(self) -> None:
        called: list[str] = []
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(name="safe.echo", description="Echo.", required_keys=("value",)),
            lambda *, value, context: called.append(value) or {"value": value},
        )
        runtime = AgentRuntime(tools=registry, policy_gate=RuntimePolicyGate())

        result = runtime.invoke_tool(
            AgentToolCall(call_id="call-invalid", tool_name="safe.echo", args={}),
            _context(),
        )

        self.assertEqual(result.status, "validation_error")
        self.assertEqual(result.error_code, "INVALID_TOOL_INPUT")
        self.assertEqual(called, [])

    def test_successful_safe_tool_returns_typed_result(self) -> None:
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(name="safe.echo", description="Echo.", required_keys=("value",)),
            lambda *, value, context: {"value": value, "trace": context.trace_id},
        )
        runtime = AgentRuntime(tools=registry, policy_gate=RuntimePolicyGate())

        result = runtime.invoke_tool(
            AgentToolCall(call_id="call-ok", tool_name="safe.echo", args={"value": "ok"}),
            _context(),
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.output, {"value": "ok", "trace": "trace-1"})
        self.assertEqual(result.call_id, "call-ok")
        self.assertEqual(result.tool_name, "safe.echo")


if __name__ == "__main__":
    unittest.main()
