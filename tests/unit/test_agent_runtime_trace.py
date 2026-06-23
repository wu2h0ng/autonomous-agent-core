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


class AgentRuntimeTraceTest(unittest.TestCase):
    def test_success_and_failure_emit_required_trace_events(self) -> None:
        trace_writer = AgentTraceWriter()
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(name="safe.echo", description="Echo.", required_keys=("value",)),
            lambda *, value, context: {"value": value},
        )
        registry.register_tool(
            ToolSpec(name="safe.fail", description="Fail."),
            lambda *, context: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        runtime = AgentRuntime(
            tools=registry,
            policy_gate=RuntimePolicyGate(),
            trace_writer=trace_writer,
        )

        ok = runtime.invoke_tool(
            AgentToolCall(call_id="call-ok", tool_name="safe.echo", args={"value": "ok"}),
            _context(),
        )
        failed = runtime.invoke_tool(
            AgentToolCall(call_id="call-fail", tool_name="safe.fail", args={}),
            _context(),
        )

        self.assertEqual(ok.status, "ok")
        self.assertEqual(failed.status, "tool_error")
        steps = [event["step"] for event in trace_writer.events]
        self.assertIn("agent_runtime.invocation_started", steps)
        self.assertIn("agent_runtime.policy_allowed", steps)
        self.assertIn("agent_runtime.tool_started", steps)
        self.assertIn("agent_runtime.tool_succeeded", steps)
        self.assertIn("agent_runtime.tool_failed", steps)
        self.assertIn("agent_runtime.invocation_finished", steps)

    def test_trace_payload_redacts_sensitive_keys(self) -> None:
        trace_writer = AgentTraceWriter(sensitive_keys=frozenset({"api_key", "password"}))
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(name="safe.echo", description="Echo.", required_keys=("api_key",)),
            lambda *, api_key, context: {"api_key": api_key, "nested": {"password": "p"}},
        )
        runtime = AgentRuntime(
            tools=registry,
            policy_gate=RuntimePolicyGate(),
            trace_writer=trace_writer,
        )

        result = runtime.invoke_tool(
            AgentToolCall(call_id="call-secret", tool_name="safe.echo", args={"api_key": "sk"}),
            _context(),
        )

        self.assertEqual(result.status, "ok")
        self.assertTrue(trace_writer.events)
        for event in trace_writer.events:
            self.assertNotIn("sk", repr(event))
            self.assertNotIn("'p'", repr(event))
        self.assertIn("[REDACTED]", repr(trace_writer.events))


if __name__ == "__main__":
    unittest.main()
