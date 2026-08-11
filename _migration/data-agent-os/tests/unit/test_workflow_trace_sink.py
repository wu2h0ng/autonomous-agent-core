"""C/D OperationTrace wiring (AR-20260707 / Palantir dynamic-lineage gap).

Workflow transitions (D) and MCP tool invocations (C) must emit to an injectable
unified trace sink so they appear in the run's lineage, not just in their own
local audit/event stores. Default (no sink) is unchanged.
"""

from __future__ import annotations

import unittest

from agent_os_contracts import (
    ApprovalWorkflow,
    RuntimeFeatureFlags,
    WorkflowStep,
)
from agent_os_core.mcp_gateway import McpGatewayRegistry, McpToolRouter
from agent_os_core.workflow import WorkflowRuntime
from agent_os_contracts import McpServerRegistration, McpToolContract

_T0 = "2026-07-07T00:00:00+00:00"


def _two_step() -> ApprovalWorkflow:
    return ApprovalWorkflow(
        workflow_id="wf-1",
        name="Budget",
        action_type="adjust_budget",
        risk_levels=("R3",),
        steps=(
            WorkflowStep(
                step_id="s1",
                step_type="approval",
                approver_role="manager",
                next_step_id="s2",
                fallback_step_id=None,
            ),
            WorkflowStep(
                step_id="s2",
                step_type="approval",
                approver_role="director",
                next_step_id=None,
                fallback_step_id=None,
            ),
        ),
        state="active",
    )


class WorkflowTraceSinkTest(unittest.TestCase):
    def test_transitions_emit_to_sink(self) -> None:
        events: list[tuple] = []
        rt = WorkflowRuntime(
            RuntimeFeatureFlags(full_bpm_workflow=True),
            now=lambda: _T0,
            trace_sink=lambda step, payload: events.append((step, payload)),
        )
        rt.register_workflow(_two_step())
        inst = rt.start_instance("wf-1", "p-1")
        rt.approve_step(inst.instance_id, "manager-1")
        steps = [e[0] for e in events]
        self.assertIn("workflow.started", steps)
        self.assertIn("workflow.approved", steps)
        self.assertIn("workflow.step_advanced", steps)

    def test_no_sink_unchanged(self) -> None:
        rt = WorkflowRuntime(RuntimeFeatureFlags(full_bpm_workflow=True), now=lambda: _T0)
        rt.register_workflow(_two_step())
        inst = rt.start_instance("wf-1", "p-1")
        rt.approve_step(inst.instance_id, "manager-1")  # must not raise

    def test_reject_emits_rejected(self) -> None:
        events: list[tuple] = []
        rt = WorkflowRuntime(
            RuntimeFeatureFlags(full_bpm_workflow=True),
            now=lambda: _T0,
            trace_sink=lambda step, payload: events.append((step, payload)),
        )
        rt.register_workflow(_two_step())
        inst = rt.start_instance("wf-1", "p-1")
        rt.reject_step(inst.instance_id, "manager-1", reason="risky")
        self.assertIn("workflow.rejected", [e[0] for e in events])


class McpToolRouterTraceSinkTest(unittest.TestCase):
    def _server(self) -> McpServerRegistration:
        return McpServerRegistration(
            server_id="mcp-1",
            name="A",
            transport_url="http://x",
            owner="p",
            tenant_id="tenant-1",
            allowed_scopes=("read_metrics",),
            risk_ceiling="R3",
            state="pending",
        )

    def _tool(self) -> McpToolContract:
        return McpToolContract(
            tool_id="t-1",
            server_id="mcp-1",
            name="q",
            description="d",
            input_schema={"type": "object"},
            risk_level="R2",
            dry_run_supported=True,
        )

    def _ctx(self):
        from agent_os_core.agent_runtime import AgentRunContext

        return AgentRunContext(
            tenant_id="tenant-1",
            workspace_id="w",
            trace_id="trace-1",
            principal_id="p",
            run_id="r",
            policy_scope=frozenset({"read_metrics"}),
            risk_ceiling="R5",
        )

    def test_invoke_emits_to_sink(self) -> None:
        events: list[tuple] = []
        reg = McpGatewayRegistry()
        reg.register_server(self._server())
        reg.activate_server("mcp-1")
        reg.register_tool(self._tool(), handler=lambda **kw: {"v": 1})
        router = McpToolRouter(
            reg,
            RuntimeFeatureFlags(mcp_gateway=True),
            trace_sink=lambda step, payload: events.append((step, payload)),
        )
        router.invoke("t-1", self._ctx(), metric="gmv")
        steps = [e[0] for e in events]
        self.assertIn("mcp.invocation_started", steps)
        self.assertIn("mcp.invocation_finished", steps)

    def test_denied_emits_denied(self) -> None:
        events: list[tuple] = []
        reg = McpGatewayRegistry()
        router = McpToolRouter(
            reg,
            RuntimeFeatureFlags(mcp_gateway=True),  # no server registered
            trace_sink=lambda step, payload: events.append((step, payload)),
        )
        router.invoke("t-1", self._ctx(), metric="gmv")
        self.assertIn("mcp.invocation_denied", [e[0] for e in events])


if __name__ == "__main__":
    unittest.main()
