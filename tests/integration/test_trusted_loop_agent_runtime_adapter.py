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
    AgentTraceWriter,
    TrustedLoopAgentRuntimeAdapter,
)
from agent_os_core.corrigibility import CorrigibilityShell  # noqa: E402


class FakeTrustedLoop:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def evaluate(self, question: str, parameters: dict[str, object]) -> dict[str, object]:
        self.calls.append((question, parameters))
        return {"status": "ok", "question": question, "parameters": parameters}


def _context() -> AgentRunContext:
    return AgentRunContext(
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        principal_id="operator-1",
        principal_role="operator",
        run_id="run-1",
        trace_id="trace-1",
        policy_scope=frozenset({"trusted_loop:evaluate"}),
    )


class TrustedLoopAgentRuntimeAdapterTest(unittest.TestCase):
    def test_safe_trusted_loop_call_goes_through_runtime_envelope(self) -> None:
        loop = FakeTrustedLoop()
        trace_writer = AgentTraceWriter()
        adapter = TrustedLoopAgentRuntimeAdapter(loop, trace_writer=trace_writer)

        result = adapter.evaluate(
            context=_context(),
            question="GMV",
            parameters={"start_date": "2026-05-01", "end_date": "2026-06-01", "limit": 10},
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(len(loop.calls), 1)
        self.assertIn(
            "agent_runtime.policy_allowed",
            [event["step"] for event in trace_writer.events],
        )

    def test_paused_shell_blocks_before_trusted_loop_execution(self) -> None:
        shell = CorrigibilityShell()
        shell.op_pause()
        loop = FakeTrustedLoop()
        adapter = TrustedLoopAgentRuntimeAdapter(loop, shell_view=shell.view())

        result = adapter.evaluate(
            context=_context(),
            question="GMV",
            parameters={"start_date": "2026-05-01", "end_date": "2026-06-01", "limit": 10},
        )

        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "DENY_PAUSED")
        self.assertEqual(loop.calls, [])


if __name__ == "__main__":
    unittest.main()
