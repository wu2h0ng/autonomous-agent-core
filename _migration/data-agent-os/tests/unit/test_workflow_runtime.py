"""Test-first unit tests for the Full BPM Approval Workflow engine (workstream D).

These tests define the multi-step governed approval workflow runtime before the
implementation exists: registration, instance start, approve/advance, reject,
delegation, manual escalation, timeout-driven escalation, terminal-state
guarding, event audit trail, and feature-flag gating.

Default flag is off; when off the engine refuses to start instances so
proposals remain on the single-step ``ApprovalLiteRuntime`` path.
"""

from __future__ import annotations

import unittest

from agent_os_contracts import (
    ApprovalWorkflow,
    RuntimeFeatureFlags,
    WorkflowStep,
)
from agent_os_core.workflow import (
    InvalidWorkflowState,
    WorkflowDisabled,
    WorkflowInstanceNotFound,
    WorkflowNotFound,
    WorkflowRuntime,
)

_T0 = "2026-07-07T00:00:00+00:00"
_T1 = "2026-07-07T01:00:00+00:00"  # +1h


def _two_step_workflow() -> ApprovalWorkflow:
    step2 = WorkflowStep(
        step_id="step-2",
        step_type="approval",
        approver_role="director",
        next_step_id=None,
    )
    step1 = WorkflowStep(
        step_id="step-1",
        step_type="approval",
        approver_role="manager",
        timeout_seconds=3600,
        next_step_id="step-2",
        fallback_step_id="step-2",
    )
    return ApprovalWorkflow(
        workflow_id="wf-1",
        name="Budget Approval",
        action_type="adjust_budget",
        risk_levels=("R3",),
        steps=(step1, step2),
        state="active",
    )


def _single_step_no_fallback() -> ApprovalWorkflow:
    return ApprovalWorkflow(
        workflow_id="wf-single",
        name="Single",
        action_type="notify",
        risk_levels=("R1",),
        steps=(
            WorkflowStep(
                step_id="only",
                step_type="approval",
                approver_role="manager",
                timeout_seconds=60,
                next_step_id=None,
                fallback_step_id=None,
            ),
        ),
        state="active",
    )


class WorkflowRuntimeFlagTest(unittest.TestCase):
    def test_flag_off_start_instance_disabled(self) -> None:
        rt = WorkflowRuntime(RuntimeFeatureFlags(), now=lambda: _T0)
        rt.register_workflow(_two_step_workflow())
        with self.assertRaises(WorkflowDisabled):
            rt.start_instance("wf-1", "proposal-1")

    def test_flag_on_starts_instance(self) -> None:
        rt = WorkflowRuntime(RuntimeFeatureFlags(full_bpm_workflow=True), now=lambda: _T0)
        rt.register_workflow(_two_step_workflow())
        inst = rt.start_instance("wf-1", "proposal-1")
        self.assertEqual(inst.state, "pending")
        self.assertEqual(inst.current_step_id, "step-1")
        self.assertEqual(rt.assigned_role(inst.instance_id), "manager")


class WorkflowRuntimeLifecycleTest(unittest.TestCase):
    def _rt(self) -> WorkflowRuntime:
        rt = WorkflowRuntime(RuntimeFeatureFlags(full_bpm_workflow=True), now=lambda: _T0)
        rt.register_workflow(_two_step_workflow())
        return rt

    def test_start_unknown_workflow_raises(self) -> None:
        rt = self._rt()
        with self.assertRaises(WorkflowNotFound):
            rt.start_instance("nope", "proposal-1")

    def test_start_requires_active_workflow(self) -> None:
        wf = _two_step_workflow()
        wf = ApprovalWorkflow(
            workflow_id=wf.workflow_id,
            name=wf.name,
            action_type=wf.action_type,
            risk_levels=wf.risk_levels,
            steps=wf.steps,
            state="draft",
        )
        rt = WorkflowRuntime(RuntimeFeatureFlags(full_bpm_workflow=True), now=lambda: _T0)
        rt.register_workflow(wf)
        with self.assertRaises(InvalidWorkflowState):
            rt.start_instance("wf-1", "proposal-1")

    def test_approve_advances_then_completes(self) -> None:
        rt = self._rt()
        inst = rt.start_instance("wf-1", "proposal-1")
        iid = inst.instance_id
        inst = rt.approve_step(iid, "manager-1")
        self.assertEqual(inst.current_step_id, "step-2")
        self.assertEqual(inst.state, "pending")
        self.assertEqual(rt.assigned_role(iid), "director")
        inst = rt.approve_step(iid, "director-1")
        self.assertEqual(inst.state, "approved")

    def test_reject_terminates_and_blocks_further(self) -> None:
        rt = self._rt()
        inst = rt.start_instance("wf-1", "proposal-1")
        iid = inst.instance_id
        inst = rt.reject_step(iid, "manager-1", reason="too risky")
        self.assertEqual(inst.state, "rejected")
        with self.assertRaises(InvalidWorkflowState):
            rt.approve_step(iid, "manager-1")

    def test_delegate_reassigns_approver(self) -> None:
        rt = self._rt()
        inst = rt.start_instance("wf-1", "proposal-1")
        iid = inst.instance_id
        inst = rt.delegate_step(iid, "manager-1", "vp-finance")
        self.assertEqual(rt.assigned_role(iid), "vp-finance")
        self.assertTrue(any(e.event_type == "delegated" for e in inst.events))

    def test_escalate_moves_to_fallback(self) -> None:
        rt = self._rt()
        inst = rt.start_instance("wf-1", "proposal-1")
        iid = inst.instance_id
        inst = rt.escalate_step(iid, "manager-1")
        self.assertEqual(inst.state, "escalated")
        self.assertEqual(inst.current_step_id, "step-2")

    def test_escalate_without_fallback_rejects(self) -> None:
        rt = WorkflowRuntime(RuntimeFeatureFlags(full_bpm_workflow=True), now=lambda: _T0)
        rt.register_workflow(_single_step_no_fallback())
        inst = rt.start_instance("wf-single", "proposal-1")
        iid = inst.instance_id
        inst = rt.escalate_step(iid, "manager-1")
        self.assertEqual(inst.state, "rejected")

    def test_timeout_with_fallback_escalates(self) -> None:
        rt = self._rt()
        inst = rt.start_instance("wf-1", "proposal-1")
        iid = inst.instance_id
        inst = rt.timeout_check(iid, _T1)  # +1h > 3600s
        self.assertEqual(inst.state, "escalated")
        self.assertEqual(inst.current_step_id, "step-2")

    def test_timeout_without_fallback_times_out(self) -> None:
        rt = WorkflowRuntime(RuntimeFeatureFlags(full_bpm_workflow=True), now=lambda: _T0)
        rt.register_workflow(_single_step_no_fallback())
        inst = rt.start_instance("wf-single", "proposal-1")
        iid = inst.instance_id
        inst = rt.timeout_check(iid, _T1)
        self.assertEqual(inst.state, "timeout")
        with self.assertRaises(InvalidWorkflowState):
            rt.approve_step(iid, "manager-1")

    def test_timeout_not_expired_noop(self) -> None:
        rt = self._rt()
        inst = rt.start_instance("wf-1", "proposal-1")
        iid = inst.instance_id
        inst = rt.timeout_check(iid, "2026-07-07T00:30:00+00:00")  # +30min < 3600s
        self.assertEqual(inst.state, "pending")
        self.assertEqual(inst.current_step_id, "step-1")

    def test_unknown_instance_raises(self) -> None:
        rt = self._rt()
        with self.assertRaises(WorkflowInstanceNotFound):
            rt.approve_step("nope", "manager-1")

    def test_tenant_isolation(self) -> None:
        rt = self._rt()
        inst = rt.start_instance("wf-1", "proposal-1", tenant_id="tenant-a")
        iid = inst.instance_id
        with self.assertRaises(WorkflowInstanceNotFound):
            rt.get_instance(iid, tenant_id="tenant-b")

    def test_events_recorded_for_each_operation(self) -> None:
        rt = self._rt()
        inst = rt.start_instance("wf-1", "proposal-1")
        iid = inst.instance_id
        rt.approve_step(iid, "manager-1")
        inst = rt.get_instance(iid)
        types = [e.event_type for e in inst.events]
        self.assertIn("started", types)
        self.assertIn("approved", types)


if __name__ == "__main__":
    unittest.main()
