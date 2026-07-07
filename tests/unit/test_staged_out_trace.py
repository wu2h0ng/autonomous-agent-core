"""Staged-out C/D trace bridge tests (ADR-0013 hardening)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api_server" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_api.staged_out_trace import build_staged_out_trace_sink  # noqa: E402
from agent_os_contracts import RunTrace  # noqa: E402
from agent_os_core.trace import InMemoryTraceStore  # noqa: E402


class StagedOutTraceSinkTest(unittest.TestCase):
    def test_appends_event_when_trace_exists(self) -> None:
        store = InMemoryTraceStore()
        store.save(
            RunTrace(trace_id="trace-1", status="ok", events=()),
            tenant_id="default",
        )
        sink = build_staged_out_trace_sink(store)
        sink("workflow.started", {"proposal_id": "trace-1", "instance_id": "wi-1"})
        updated = store.get("trace-1")
        assert updated is not None
        self.assertEqual(len(updated.events), 1)
        self.assertEqual(updated.events[0].step, "workflow.started")

    def test_noop_when_trace_missing(self) -> None:
        store = InMemoryTraceStore()
        sink = build_staged_out_trace_sink(store)
        sink("mcp.invocation_started", {"trace_id": "missing", "tool_id": "t1"})
        self.assertIsNone(store.get("missing"))

    def test_noop_when_store_none(self) -> None:
        sink = build_staged_out_trace_sink(None)
        sink("workflow.approved", {"proposal_id": "x"})


if __name__ == "__main__":
    unittest.main()
