from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))

from agent_os_contracts import (  # noqa: E402
    ApprovalWorkflow,
    WorkflowEvent,
    WorkflowInstance,
    WorkflowStep,
)


class WorkflowContractsTest(unittest.TestCase):
    def test_workflow_step_and_approval_workflow(self) -> None:
        step = WorkflowStep(
            step_id="step-1",
            step_type="approval",
            approver_role="manager",
            timeout_seconds=3600,
            next_step_id="step-2",
        )
        workflow = ApprovalWorkflow(
            workflow_id="wf-1",
            name="Budget Approval",
            action_type="adjust_budget",
            risk_levels=("R3",),
            steps=(step,),
            state="active",
        )
        self.assertEqual(workflow.state, "active")
        self.assertEqual(workflow.steps[0].approver_role, "manager")

    def test_workflow_instance_and_event(self) -> None:
        event = WorkflowEvent(
            event_id="evt-1",
            instance_id="wi-1",
            step_id="step-1",
            event_type="approved",
            actor="manager-1",
            timestamp="2026-07-07T00:00:00Z",
            payload={},
        )
        instance = WorkflowInstance(
            instance_id="wi-1",
            workflow_id="wf-1",
            proposal_id="proposal-1",
            current_step_id="step-1",
            state="pending",
            events=(event,),
        )
        self.assertEqual(instance.state, "pending")
        self.assertEqual(instance.events[0].event_type, "approved")


if __name__ == "__main__":
    unittest.main()
