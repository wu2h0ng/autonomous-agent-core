"""Runtime selection point (workstream enablement / AR-20260707).

The ApprovalRouter is the entry point that makes C/D/E reachable from a real
runtime path (AGENTS.md boundary #8). Given a proposal + operation, it decides:

- policy_pre_approved: PolicyEngine pre-approves (flag on + policy + guardrails)
- workflow: a registered multi-step workflow applies (flag on + matching workflow)
- lite: default human single-step approval (ApprovalLiteRuntime)

Default behavior when all flags off: ``lite`` (current MVP behavior unchanged).
"""

from __future__ import annotations

import unittest

from agent_os_contracts import (
    ActionProposal,
    AutoExecutionPolicy,
    AutoExecutionRule,
    OperationContract,
    RiskLevel,
    RuntimeFeatureFlags,
)
from agent_os_core.approval_router import (
    ApprovalRouter,
)
from agent_os_core.policy_engine import GuardrailInput, PolicyEngine
from agent_os_core.workflow import WorkflowRuntime

_T0 = "2026-07-07T00:00:00+00:00"


def _rule():
    return AutoExecutionRule(
        rule_id="rule-1",
        action_type="adjust_budget",
        risk_levels=("R4",),
        mode="policy_pre_approved",
        guard_conditions={
            "dry_run_success": True,
            "evidence_complete": True,
            "confidence_min": 0.9,
        },
        compensating_action="rollback_budget",
    )


def _policy():
    return AutoExecutionPolicy(version="v1", tenant_id="tenant-1", owner="o", rules=(_rule(),))


def _operation(risk_level="R4"):
    return OperationContract(
        operation_id="op-1",
        name="Adjust Budget",
        target_connector="action_record",
        risk_level=risk_level,
        approval_required=True,
        rollback_supported=True,
        compensating_action="rollback_budget",
        connector_name="action_record",
        action_type="adjust_budget",
        auto_executable=True,
    )


def _proposal():
    return ActionProposal(
        proposal_id="proposal-1",
        evidence_chain_id="ev-1",
        target_object="c-1",
        recommended_action="adjust_budget",
        reason="roi",
        risk_level=RiskLevel.R4,
        expected_impact="lower spend",
        approval_required=True,
        approver_role="finance",
        connector_name="action_record",
        action_type="adjust_budget",
    )


def _guards():
    return GuardrailInput(dry_run_success=True, evidence_complete=True, confidence=0.95)


class ApprovalRouterDefaultTest(unittest.TestCase):
    def test_all_flags_off_routes_to_lite(self) -> None:
        router = ApprovalRouter(RuntimeFeatureFlags())
        decision = router.route(
            _proposal(), _operation(), _guards(), tenant_id="tenant-1", trace_id="trace-1"
        )
        self.assertEqual(decision.mode, "lite")
        self.assertIsNone(decision.policy_approval_id)
        self.assertIsNone(decision.workflow_instance_id)


class ApprovalRouterPolicyPreApprovalTest(unittest.TestCase):
    def _router(self) -> ApprovalRouter:
        pe = PolicyEngine(RuntimeFeatureFlags(r4_r5_auto_execution=True), now=lambda: _T0)
        pe.register_policy(_policy())
        return ApprovalRouter(RuntimeFeatureFlags(r4_r5_auto_execution=True), policy_engine=pe)

    def test_policy_pre_approved_route(self) -> None:
        router = self._router()
        decision = router.route(
            _proposal(), _operation(), _guards(), tenant_id="tenant-1", trace_id="trace-1"
        )
        self.assertEqual(decision.mode, "policy_pre_approved")
        self.assertIsNotNone(decision.policy_approval_id)

    def test_policy_denied_falls_back_to_lite(self) -> None:
        router = self._router()
        # guardrail fails -> policy denies -> fall back to lite human approval
        decision = router.route(
            _proposal(),
            _operation(),
            GuardrailInput(dry_run_success=False),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        self.assertEqual(decision.mode, "lite")
        self.assertIsNone(decision.policy_approval_id)

    def test_proposal_marked_pre_approved(self) -> None:
        router = self._router()
        proposal = _proposal()
        decision = router.route(
            proposal, _operation(), _guards(), tenant_id="tenant-1", trace_id="trace-1"
        )
        self.assertEqual(decision.proposal.execution_mode, "policy_pre_approved")


class ApprovalRouterWorkflowTest(unittest.TestCase):
    def _router(self) -> ApprovalRouter:
        from agent_os_contracts import ApprovalWorkflow, WorkflowStep

        wf = ApprovalWorkflow(
            workflow_id="wf-1",
            name="Budget",
            action_type="adjust_budget",
            risk_levels=("R3",),
            steps=(
                WorkflowStep(
                    step_id="s1",
                    step_type="approval",
                    approver_role="manager",
                    next_step_id=None,
                    fallback_step_id=None,
                ),
            ),
            state="active",
        )
        wr = WorkflowRuntime(RuntimeFeatureFlags(full_bpm_workflow=True), now=lambda: _T0)
        wr.register_workflow(wf)
        return ApprovalRouter(RuntimeFeatureFlags(full_bpm_workflow=True), workflow_runtime=wr)

    def test_workflow_route_starts_instance(self) -> None:
        router = self._router()
        proposal = ActionProposal(
            proposal_id="p-wf",
            evidence_chain_id="ev-1",
            target_object="c-1",
            recommended_action="adjust_budget",
            reason="roi",
            risk_level=RiskLevel.R3,
            expected_impact="x",
            approval_required=True,
            approver_role="manager",
            connector_name="action_record",
            action_type="adjust_budget",
        )
        op = _operation(risk_level="R3")
        decision = router.route(proposal, op, _guards(), tenant_id="tenant-1", trace_id="trace-1")
        self.assertEqual(decision.mode, "workflow")
        self.assertIsNotNone(decision.workflow_instance_id)
        self.assertEqual(decision.workflow_state, "pending")

    def test_no_matching_workflow_falls_back_to_lite(self) -> None:
        router = self._router()
        # R4 risk but workflow only covers R3 -> no match -> lite
        decision = router.route(
            _proposal(), _operation(), _guards(), tenant_id="tenant-1", trace_id="trace-1"
        )
        self.assertEqual(decision.mode, "lite")


class ApprovalRouterPriorityTest(unittest.TestCase):
    """Policy pre-approval takes priority over workflow when both configured."""

    def test_policy_wins_over_workflow(self) -> None:
        pe = PolicyEngine(RuntimeFeatureFlags(r4_r5_auto_execution=True), now=lambda: _T0)
        pe.register_policy(_policy())
        from agent_os_contracts import ApprovalWorkflow, WorkflowStep

        wf = ApprovalWorkflow(
            workflow_id="wf-1",
            name="B",
            action_type="adjust_budget",
            risk_levels=("R4",),
            steps=(WorkflowStep(step_id="s1", step_type="approval", approver_role="manager"),),
            state="active",
        )
        wr = WorkflowRuntime(RuntimeFeatureFlags(full_bpm_workflow=True), now=lambda: _T0)
        wr.register_workflow(wf)
        router = ApprovalRouter(
            RuntimeFeatureFlags(r4_r5_auto_execution=True, full_bpm_workflow=True),
            policy_engine=pe,
            workflow_runtime=wr,
        )
        decision = router.route(
            _proposal(), _operation(), _guards(), tenant_id="tenant-1", trace_id="trace-1"
        )
        self.assertEqual(decision.mode, "policy_pre_approved")


if __name__ == "__main__":
    unittest.main()
