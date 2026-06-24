from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (
    ROOT / "packages" / "contracts" / "src",
    ROOT / "packages" / "os_core" / "src",
    ROOT / "packages" / "persistence" / "src",
):
    sys.path.insert(0, str(_p))

_SQLALCHEMY = importlib.util.find_spec("sqlalchemy") is not None


def _context():
    from agent_os_core.agent_runtime import AgentRunContext

    return AgentRunContext(
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        principal_id="user-1",
        principal_role="analyst",
        run_id="run-sql-checkpoint",
        trace_id="trace-sql-checkpoint",
        policy_scope=frozenset({"tool:read"}),
    )


def _registry(called: list[str]):
    from agent_os_core.agent_runtime import ToolRegistry, ToolSpec

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
    return registry


@unittest.skipUnless(_SQLALCHEMY, "sqlalchemy not installed")
class AgentRuntimeSqlCheckpointStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool

        from agent_os_persistence import create_all

        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        create_all(self.engine)

    def test_resume_from_sql_checkpoint_returns_last_result_across_runtime_instances(self) -> None:
        from agent_os_core.agent_runtime import AgentRuntime, AgentToolCall, RuntimePolicyGate
        from agent_os_persistence import SqlAgentCheckpointStore

        called: list[str] = []
        call = AgentToolCall(
            call_id="call-sql-replay",
            tool_name="safe.echo",
            args={"value": "ok"},
        )
        context = _context()
        first_runtime = AgentRuntime(
            tools=_registry(called),
            policy_gate=RuntimePolicyGate(),
            checkpoint_store=SqlAgentCheckpointStore(self.engine),
        )
        first = first_runtime.invoke_tool(call, context)

        second_runtime = AgentRuntime(
            tools=_registry(called),
            policy_gate=RuntimePolicyGate(),
            checkpoint_store=SqlAgentCheckpointStore(self.engine),
        )
        resumed = second_runtime.resume_from_checkpoint(call, context)

        self.assertEqual(first.status, "ok")
        self.assertEqual(resumed, first)
        self.assertEqual(called, ["ok"])

    def test_resume_from_sql_checkpoint_rejects_mismatch_without_tool_execution(self) -> None:
        from agent_os_core.agent_runtime import AgentRuntime, AgentToolCall, RuntimePolicyGate
        from agent_os_persistence import SqlAgentCheckpointStore

        called: list[str] = []
        call = AgentToolCall(
            call_id="call-sql-replay",
            tool_name="safe.echo",
            args={"value": "ok"},
        )
        context = _context()
        first_runtime = AgentRuntime(
            tools=_registry(called),
            policy_gate=RuntimePolicyGate(),
            checkpoint_store=SqlAgentCheckpointStore(self.engine),
        )
        first_runtime.invoke_tool(call, context)

        second_runtime = AgentRuntime(
            tools=_registry(called),
            policy_gate=RuntimePolicyGate(),
            checkpoint_store=SqlAgentCheckpointStore(self.engine),
        )
        resumed = second_runtime.resume_from_checkpoint(
            AgentToolCall(
                call_id="call-sql-replay",
                tool_name="safe.echo",
                args={"value": "changed"},
            ),
            context,
        )

        self.assertEqual(resumed.status, "validation_error")
        self.assertEqual(resumed.error_code, "CHECKPOINT_MISMATCH")
        self.assertEqual(resumed.metadata["mismatched"], ("call_fingerprint",))
        self.assertEqual(called, ["ok"])


if __name__ == "__main__":
    unittest.main()
