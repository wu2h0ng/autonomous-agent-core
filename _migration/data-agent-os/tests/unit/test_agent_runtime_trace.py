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

    def test_trace_writer_redacts_sensitive_keys_in_explicit_events(self) -> None:
        trace_writer = AgentTraceWriter(sensitive_keys=frozenset({"api_key", "password"}))
        trace_writer.write(
            "custom",
            {
                "api_key": "sk",
                "nested": {"password": "p", "safe": "ok"},
            },
        )

        self.assertNotIn("sk", repr(trace_writer.events))
        self.assertNotIn("'p'", repr(trace_writer.events))
        self.assertIn("[REDACTED]", repr(trace_writer.events))

    def test_trace_writer_redacts_sensitive_keys_case_insensitively(self) -> None:
        trace_writer = AgentTraceWriter()
        trace_writer.write(
            "custom",
            {
                "Authorization": "Bearer sk-live",
                "nested": {"Secret_Token": "secret-value"},
                "items": [{"API_KEY": "api-value"}],
            },
        )

        trace_blob = repr(trace_writer.events)
        self.assertNotIn("Bearer sk-live", trace_blob)
        self.assertNotIn("secret-value", trace_blob)
        self.assertNotIn("api-value", trace_blob)
        self.assertIn("[REDACTED]", trace_blob)

    def test_runtime_trace_does_not_record_raw_args_or_outputs_by_default(self) -> None:
        trace_writer = AgentTraceWriter()
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(name="safe.echo", description="Echo.", required_keys=("secret_token",)),
            lambda *, secret_token, business_payload, context: {
                "result": "ok",
                "secret_token": "sk-output",
                "business_payload": business_payload,
            },
        )
        runtime = AgentRuntime(
            tools=registry,
            policy_gate=RuntimePolicyGate(),
            trace_writer=trace_writer,
        )

        result = runtime.invoke_tool(
            AgentToolCall(
                call_id="call-secret",
                tool_name="safe.echo",
                args={
                    "secret_token": "sk-input",
                    "business_payload": {"customer": "private-customer"},
                },
            ),
            _context(),
        )

        self.assertEqual(result.status, "ok")
        self.assertTrue(trace_writer.events)
        trace_blob = repr(trace_writer.events)
        self.assertNotIn("sk-input", trace_blob)
        self.assertNotIn("sk-output", trace_blob)
        self.assertNotIn("private-customer", trace_blob)
        for event in trace_writer.events:
            self.assertNotIn("args", event["payload"])
            self.assertNotIn("output", event["payload"])


if __name__ == "__main__":
    unittest.main()
