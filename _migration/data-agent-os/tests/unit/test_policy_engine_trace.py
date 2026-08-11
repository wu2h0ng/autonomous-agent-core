"""F4 (AR-20260707): PolicyEngine OperationTrace wiring (ADR-0012 §3.4).

A successful R4/R5 pre-approval must produce an OperationTrace whose events
record the proposed -> policy_evaluated -> policy_pre_approved progression,
and the trace must be retrievable by proposal id. Denied evaluations must
record the proposed -> policy_evaluated -> rejected (or proposed -> rejected)
progression.
"""

from __future__ import annotations

import unittest

from agent_os_contracts import (
    ActionProposal,
    AutoExecutionPolicy,
    AutoExecutionRule,
    OperationContract,
    OperationState,
    RiskLevel,
    RuntimeFeatureFlags,
)
from agent_os_core.policy_engine import GuardrailInput, PolicyEngine

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


def _operation():
    return OperationContract(
        operation_id="op-1",
        name="Adjust Budget",
        target_connector="action_record",
        risk_level="R4",
        approval_required=True,
        dry_run_required=True,
        rollback_supported=True,
        compensating_action="rollback_budget",
        connector_name="action_record",
        action_type="adjust_budget",
        auto_executable=True,
    )


def _proposal(pid="proposal-1"):
    return ActionProposal(
        proposal_id=pid,
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


class PolicyEngineTraceTest(unittest.TestCase):
    def _engine(self) -> PolicyEngine:
        e = PolicyEngine(RuntimeFeatureFlags(r4_r5_auto_execution=True), now=lambda: _T0)
        e.register_policy(_policy())
        return e

    def test_pre_approval_produces_trace_events(self) -> None:
        e = self._engine()
        result = e.evaluate(
            _proposal(),
            _operation(),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        trace = e.trace_for(result.proposal_id)
        self.assertIsNotNone(trace)
        steps = [ev.get("step") for ev in trace.events]
        self.assertIn("proposed", steps)
        self.assertIn("policy_evaluated", steps)
        self.assertIn("policy_pre_approved", steps)
        self.assertEqual(trace.state, OperationState.POLICY_PRE_APPROVED)

    def test_denied_records_rejected_trace(self) -> None:
        e = self._engine()
        result = e.evaluate(
            _proposal(),
            _operation(),
            GuardrailInput(dry_run_success=False),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        trace = e.trace_for(result.proposal_id)
        self.assertIsNotNone(trace)
        steps = [ev.get("step") for ev in trace.events]
        self.assertIn("policy_evaluated", steps)
        self.assertIn("rejected", steps)
        self.assertEqual(trace.state, OperationState.REJECTED)

    def test_proposal_only_when_flag_off_leaves_no_trace(self) -> None:
        e = PolicyEngine(RuntimeFeatureFlags(), now=lambda: _T0)
        e.register_policy(_policy())
        result = e.evaluate(
            _proposal(),
            _operation(),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        self.assertEqual(result.decision, "proposal_only")
        # no auto-exec trace for a proposal-only outcome
        self.assertIsNone(e.trace_for(result.proposal_id))

    def test_consume_updates_trace_state(self) -> None:
        e = self._engine()
        result = e.evaluate(
            _proposal(),
            _operation(),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        e.consume_approval(result.policy_approval_id, tenant_id="tenant-1")
        trace = e.trace_for(result.proposal_id)
        steps = [ev.get("step") for ev in trace.events]
        self.assertIn("executed", steps)


if __name__ == "__main__":
    unittest.main()
