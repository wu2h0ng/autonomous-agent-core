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
    InMemoryCheckpointStore,
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
        "run_id": "run-1",
        "trace_id": "trace-1",
        "policy_scope": frozenset({"tool:read"}),
    }
    values.update(overrides)
    return AgentRunContext(**values)


class AgentRuntimeReplayBoundaryTest(unittest.TestCase):
    def test_snapshot_records_last_completed_runtime_boundary(self) -> None:
        checkpoints = InMemoryCheckpointStore()
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(name="safe.echo", description="Echo.", required_keys=("value",)),
            lambda *, value, context: {"value": value},
        )
        runtime = AgentRuntime(
            tools=registry,
            policy_gate=RuntimePolicyGate(),
            checkpoint_store=checkpoints,
        )

        result = runtime.invoke_tool(
            AgentToolCall(call_id="call-snapshot", tool_name="safe.echo", args={"value": "ok"}),
            _context(),
        )

        self.assertEqual(result.status, "ok")
        snapshot = checkpoints.get("run-1")
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.last_completed_boundary, "agent_runtime.invoke_tool")
        self.assertEqual(snapshot.pending_tool_call, None)
        self.assertEqual(snapshot.last_result.status, "ok")

    def test_unsupported_nondeterministic_inputs_fail_closed(self) -> None:
        called: list[str] = []
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(name="safe.echo", description="Echo.", required_keys=("value",)),
            lambda *, value, context: called.append(value) or {"value": value},
        )
        runtime = AgentRuntime(tools=registry, policy_gate=RuntimePolicyGate())

        result = runtime.invoke_tool(
            AgentToolCall(call_id="call-unreplayable", tool_name="safe.echo", args={"value": "x"}),
            _context(metadata={"nondeterministic_inputs": ("wall_clock",)}),
        )

        self.assertEqual(result.status, "validation_error")
        self.assertEqual(result.error_code, "UNREPLAYABLE_INPUT")
        self.assertEqual(result.metadata["unreplayable_inputs"], ("wall_clock",))
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
