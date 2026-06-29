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
    InMemoryCheckpointStore,
    RunStateSnapshot,
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
    def test_checkpoint_store_failure_returns_structured_error_after_tool_execution(self) -> None:
        class FailingCheckpointStore:
            def save(self, snapshot: RunStateSnapshot) -> None:
                raise RuntimeError("database unavailable")

            def get(self, run_id: str) -> RunStateSnapshot | None:
                return None

        called: list[str] = []
        trace_writer = AgentTraceWriter()
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(name="safe.echo", description="Echo.", required_keys=("value",)),
            lambda *, value, context: called.append(value) or {"value": value},
        )
        runtime = AgentRuntime(
            tools=registry,
            policy_gate=RuntimePolicyGate(),
            trace_writer=trace_writer,
            checkpoint_store=FailingCheckpointStore(),
        )

        result = runtime.invoke_tool(
            AgentToolCall(
                call_id="call-checkpoint-fail", tool_name="safe.echo", args={"value": "ok"}
            ),
            _context(),
        )

        self.assertEqual(called, ["ok"])
        self.assertEqual(result.status, "checkpoint_error")
        self.assertEqual(result.error_code, "RuntimeError")
        self.assertEqual(result.error_message, "checkpoint save failed")
        self.assertEqual(result.metadata["tool_status"], "ok")
        steps = [event["step"] for event in trace_writer.events]
        self.assertIn("agent_runtime.checkpoint_failed", steps)
        self.assertEqual(trace_writer.events[-1]["step"], "agent_runtime.invocation_finished")
        self.assertEqual(trace_writer.events[-1]["payload"]["status"], "checkpoint_error")

    def test_checkpoint_failure_can_preserve_result_for_irreversible_side_effects(self) -> None:
        class FailingCheckpointStore:
            def save(self, snapshot: RunStateSnapshot) -> None:
                raise RuntimeError("database unavailable")

            def get(self, run_id: str) -> RunStateSnapshot | None:
                return None

        called: list[str] = []
        trace_writer = AgentTraceWriter()
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                name="correction.adopt",
                description="Write completed correction side effect.",
                required_keys=("value",),
                side_effect_class="external_value_attestation",
                required_permissions=("tool:read",),
                preserve_result_on_checkpoint_failure=True,
            ),
            lambda *, value, context: called.append(value) or {"value": value},
        )
        runtime = AgentRuntime(
            tools=registry,
            policy_gate=RuntimePolicyGate(),
            trace_writer=trace_writer,
            checkpoint_store=FailingCheckpointStore(),
        )

        result = runtime.invoke_tool(
            AgentToolCall(
                call_id="call-checkpoint-preserve",
                tool_name="correction.adopt",
                args={"value": "written"},
            ),
            _context(),
        )

        self.assertEqual(called, ["written"])
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.output, {"value": "written"})
        self.assertEqual(result.metadata["checkpoint_status"], "failed")
        steps = [event["step"] for event in trace_writer.events]
        self.assertIn("agent_runtime.checkpoint_failed", steps)
        self.assertEqual(trace_writer.events[-1]["step"], "agent_runtime.invocation_finished")
        self.assertEqual(trace_writer.events[-1]["payload"]["status"], "ok")

    def test_checkpoint_store_failure_does_not_mask_policy_denial(self) -> None:
        class FailingCheckpointStore:
            def save(self, snapshot: RunStateSnapshot) -> None:
                raise RuntimeError("database unavailable")

            def get(self, run_id: str) -> RunStateSnapshot | None:
                return None

        called: list[str] = []
        trace_writer = AgentTraceWriter()
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                name="action.r5",
                description="High-risk action execution.",
                required_keys=("value",),
                risk_level="R5",
                side_effect_class="external_write",
                required_permissions=("tool:write",),
            ),
            lambda *, value, context: called.append(value) or {"value": value},
        )
        runtime = AgentRuntime(
            tools=registry,
            policy_gate=RuntimePolicyGate(),
            trace_writer=trace_writer,
            checkpoint_store=FailingCheckpointStore(),
        )

        result = runtime.invoke_tool(
            AgentToolCall(call_id="call-r5", tool_name="action.r5", args={"value": "x"}),
            _context(policy_scope=frozenset({"tool:write"}), approval_id="approval-1"),
        )

        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "DENY_HIGH_RISK_EXECUTION")
        self.assertEqual(called, [])
        self.assertNotIn(
            "agent_runtime.checkpoint_failed",
            [event["step"] for event in trace_writer.events],
        )

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

    def test_resume_rejects_call_mismatch_without_tool_execution(self) -> None:
        called: list[str] = []
        checkpoints = InMemoryCheckpointStore()
        trace_writer = AgentTraceWriter()
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                name="safe.echo",
                description="Echo.",
                required_keys=("value",),
                required_permissions=("tool:read",),
            ),
            lambda *, value, context: called.append(value) or {"value": value},
        )
        runtime = AgentRuntime(
            tools=registry,
            policy_gate=RuntimePolicyGate(),
            trace_writer=trace_writer,
            checkpoint_store=checkpoints,
        )
        original_call = AgentToolCall(
            call_id="call-replay", tool_name="safe.echo", args={"value": "ok"}
        )
        original_context = _context()

        first = runtime.invoke_tool(original_call, original_context)
        resumed = runtime.resume_from_checkpoint(
            AgentToolCall(
                call_id="call-replay",
                tool_name="safe.echo",
                args={"value": "changed-secret"},
            ),
            original_context,
        )

        self.assertEqual(first.status, "ok")
        self.assertEqual(resumed.status, "validation_error")
        self.assertEqual(resumed.error_code, "CHECKPOINT_MISMATCH")
        self.assertEqual(called, ["ok"])
        self.assertIn(
            "agent_runtime.checkpoint_resume_failed",
            [event["step"] for event in trace_writer.events],
        )
        trace_blob = repr(trace_writer.events)
        self.assertIn("CHECKPOINT_MISMATCH", trace_blob)
        self.assertNotIn("changed-secret", trace_blob)

    def test_resume_returns_last_result_for_matching_checkpoint(self) -> None:
        called: list[str] = []
        checkpoints = InMemoryCheckpointStore()
        trace_writer = AgentTraceWriter()
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                name="safe.echo",
                description="Echo.",
                required_keys=("value",),
                required_permissions=("tool:read",),
            ),
            lambda *, value, context: called.append(value) or {"value": value},
        )
        runtime = AgentRuntime(
            tools=registry,
            policy_gate=RuntimePolicyGate(),
            trace_writer=trace_writer,
            checkpoint_store=checkpoints,
        )
        call = AgentToolCall(call_id="call-replay-ok", tool_name="safe.echo", args={"value": "ok"})
        context = _context()

        first = runtime.invoke_tool(call, context)
        resumed = runtime.resume_from_checkpoint(call, context)

        self.assertEqual(first.status, "ok")
        self.assertEqual(resumed.status, "ok")
        self.assertEqual(resumed.output, {"value": "ok"})
        self.assertEqual(called, ["ok"])
        steps = [event["step"] for event in trace_writer.events]
        self.assertIn("agent_runtime.checkpoint_resume_started", steps)
        self.assertIn("agent_runtime.checkpoint_resume_succeeded", steps)
        resume_success = [
            event
            for event in trace_writer.events
            if event["step"] == "agent_runtime.checkpoint_resume_succeeded"
        ][-1]
        self.assertEqual(resume_success["payload"]["status"], "ok")
        self.assertNotIn("output", resume_success["payload"])

    def test_resume_respects_paused_shell_before_returning_checkpoint(self) -> None:
        from agent_os_core.corrigibility import CorrigibilityShell

        called: list[str] = []
        checkpoints = InMemoryCheckpointStore()
        trace_writer = AgentTraceWriter()
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                name="safe.echo",
                description="Echo.",
                required_keys=("value",),
                required_permissions=("tool:read",),
            ),
            lambda *, value, context: called.append(value) or {"value": value},
        )
        shell = CorrigibilityShell()
        active_runtime = AgentRuntime(
            tools=registry,
            policy_gate=RuntimePolicyGate(shell_view=shell.view()),
            trace_writer=trace_writer,
            checkpoint_store=checkpoints,
        )
        call = AgentToolCall(
            call_id="call-paused-resume",
            tool_name="safe.echo",
            args={"value": "ok"},
        )
        context = _context()
        first = active_runtime.invoke_tool(call, context)
        shell.op_pause()
        paused_runtime = AgentRuntime(
            tools=registry,
            policy_gate=RuntimePolicyGate(shell_view=shell.view()),
            trace_writer=trace_writer,
            checkpoint_store=checkpoints,
        )

        resumed = paused_runtime.resume_from_checkpoint(call, context)

        self.assertEqual(first.status, "ok")
        self.assertEqual(resumed.status, "denied")
        self.assertEqual(resumed.error_code, "DENY_PAUSED")
        self.assertEqual(called, ["ok"])
        steps = [event["step"] for event in trace_writer.events]
        self.assertIn("agent_runtime.policy_denied", steps)
        self.assertIn("agent_runtime.checkpoint_resume_failed", steps)
        self.assertNotIn("agent_runtime.checkpoint_resume_succeeded", steps)

    def test_resume_mismatch_is_not_masked_by_paused_shell(self) -> None:
        from agent_os_core.corrigibility import CorrigibilityShell

        called: list[str] = []
        checkpoints = InMemoryCheckpointStore()
        trace_writer = AgentTraceWriter()
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                name="safe.echo",
                description="Echo.",
                required_keys=("value",),
                required_permissions=("tool:read",),
            ),
            lambda *, value, context: called.append(value) or {"value": value},
        )
        shell = CorrigibilityShell()
        runtime = AgentRuntime(
            tools=registry,
            policy_gate=RuntimePolicyGate(shell_view=shell.view()),
            trace_writer=trace_writer,
            checkpoint_store=checkpoints,
        )
        original_call = AgentToolCall(
            call_id="call-paused-mismatch",
            tool_name="safe.echo",
            args={"value": "ok"},
        )
        context = _context()
        first = runtime.invoke_tool(original_call, context)
        shell.op_pause()

        resumed = runtime.resume_from_checkpoint(
            AgentToolCall(
                call_id="call-paused-mismatch",
                tool_name="safe.echo",
                args={"value": "changed-secret"},
            ),
            context,
        )

        self.assertEqual(first.status, "ok")
        self.assertEqual(resumed.status, "validation_error")
        self.assertEqual(resumed.error_code, "CHECKPOINT_MISMATCH")
        self.assertEqual(called, ["ok"])
        steps = [event["step"] for event in trace_writer.events]
        self.assertIn("agent_runtime.checkpoint_resume_failed", steps)
        self.assertNotIn("agent_runtime.checkpoint_resume_succeeded", steps)
        self.assertNotIn("changed-secret", repr(trace_writer.events))

    def test_resume_rejects_tool_spec_mismatch(self) -> None:
        checkpoints = InMemoryCheckpointStore()
        first_registry = ToolRegistry()
        first_registry.register_tool(
            ToolSpec(
                name="safe.echo",
                description="Echo.",
                required_keys=("value",),
                required_permissions=("tool:read",),
            ),
            lambda *, value, context: {"value": value},
        )
        first_runtime = AgentRuntime(
            tools=first_registry,
            policy_gate=RuntimePolicyGate(),
            checkpoint_store=checkpoints,
        )
        call = AgentToolCall(call_id="call-spec", tool_name="safe.echo", args={"value": "ok"})
        context = _context()
        first_runtime.invoke_tool(call, context)

        second_registry = ToolRegistry()
        second_registry.register_tool(
            ToolSpec(
                name="safe.echo",
                description="Echo with stricter input.",
                required_keys=("value", "reason"),
                required_permissions=("tool:read",),
            ),
            lambda *, value, reason, context: {"value": value, "reason": reason},
        )
        second_runtime = AgentRuntime(
            tools=second_registry,
            policy_gate=RuntimePolicyGate(),
            checkpoint_store=checkpoints,
        )

        resumed = second_runtime.resume_from_checkpoint(call, context)

        self.assertEqual(resumed.status, "validation_error")
        self.assertEqual(resumed.error_code, "CHECKPOINT_MISMATCH")
        self.assertEqual(resumed.metadata["mismatched"], ("tool_spec_fingerprint",))


if __name__ == "__main__":
    unittest.main()
