"""Hardening tests for ADR-0012 review findings F1/F2 (AR-20260707).

F1 — consume-time pause recheck (C7 supremacy / TOCTOU): the approval record
minted at evaluate-time must NOT be consumable after the shell is paused, and a
paused shell must cause consume to fail-closed rather than silently consume.

F2 — idempotent mint: a repeated evaluate for the same proposal must reuse the
existing active record instead of minting a second consumable record.
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
from agent_os_core import CorrigibilityShell
from agent_os_core.policy_engine import (
    GuardrailInput,
    PolicyApprovalConsumed,
    PolicyEngine,
)

_T0 = "2026-07-07T00:00:00+00:00"


def _rule(risk_levels=("R4",), mode="policy_pre_approved") -> AutoExecutionRule:
    return AutoExecutionRule(
        rule_id="rule-1",
        action_type="adjust_budget",
        risk_levels=tuple(risk_levels),
        mode=mode,
        guard_conditions={
            "dry_run_success": True,
            "evidence_complete": True,
            "confidence_min": 0.9,
            "max_delta_pct": 10.0,
        },
        compensating_action="rollback_budget",
    )


def _policy(rules=(_rule(),), version="v1") -> AutoExecutionPolicy:
    return AutoExecutionPolicy(
        version=version,
        tenant_id="tenant-1",
        owner="policy-owner",
        rules=tuple(rules),
        default_mode="proposal_only",
    )


def _operation(risk_level="R4") -> OperationContract:
    return OperationContract(
        operation_id="op-1",
        name="Adjust Budget",
        target_connector="action_record",
        risk_level=risk_level,
        approval_required=True,
        dry_run_required=True,
        rollback_supported=True,
        compensating_action="rollback_budget",
        connector_name="action_record",
        action_type="adjust_budget",
        auto_executable=True,
    )


def _proposal(proposal_id="proposal-1") -> ActionProposal:
    return ActionProposal(
        proposal_id=proposal_id,
        evidence_chain_id="ev-1",
        target_object="campaign-1",
        recommended_action="adjust_budget",
        reason="roi optimization",
        risk_level=RiskLevel.R4,
        expected_impact="lower spend",
        approval_required=True,
        approver_role="finance",
        connector_name="action_record",
        action_type="adjust_budget",
    )


def _guards() -> GuardrailInput:
    return GuardrailInput(
        dry_run_success=True,
        evidence_complete=True,
        confidence=0.95,
        metric_delta_pct=3.0,
    )


class ConsumeTimePauseRecheckTest(unittest.TestCase):
    """F1: consume must fail-closed when the shell is paused (C7 supremacy)."""

    def _engine(self, shell=None) -> PolicyEngine:
        engine = PolicyEngine(
            RuntimeFeatureFlags(r4_r5_auto_execution=True),
            shell=shell,
            now=lambda: _T0,
        )
        engine.register_policy(_policy())
        return engine

    def test_consume_after_pause_raises(self) -> None:
        shell = CorrigibilityShell()
        engine = self._engine(shell)
        result = engine.evaluate(
            _proposal(),
            _operation(),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        self.assertEqual(result.decision, "policy_pre_approved")
        # pause AFTER mint (mint-time check passed, shell was clear then)
        shell.op_pause()
        with self.assertRaises(PolicyApprovalConsumed):
            engine.consume_approval(result.policy_approval_id)

    def test_consume_after_pause_does_not_mark_consumed(self) -> None:
        shell = CorrigibilityShell()
        engine = self._engine(shell)
        result = engine.evaluate(
            _proposal(),
            _operation(),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        rid = result.policy_approval_id
        shell.op_pause()
        try:
            engine.consume_approval(rid)
        except PolicyApprovalConsumed:
            pass
        # the record must NOT have been consumed by the failed call
        self.assertTrue(engine.is_approval_valid(rid, tenant_id="tenant-1"))

    def test_consume_when_clear_marks_consumed(self) -> None:
        shell = CorrigibilityShell()
        engine = self._engine(shell)
        result = engine.evaluate(
            _proposal(),
            _operation(),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        rid = result.policy_approval_id
        engine.consume_approval(rid)
        self.assertFalse(engine.is_approval_valid(rid, tenant_id="tenant-1"))

    def test_consume_revoked_record_raises(self) -> None:
        shell = CorrigibilityShell()
        engine = self._engine(shell)
        result = engine.evaluate(
            _proposal(),
            _operation(),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        rid = result.policy_approval_id
        engine.revoke_approval(rid)
        with self.assertRaises(PolicyApprovalConsumed):
            engine.consume_approval(rid)

    def test_double_consume_second_raises(self) -> None:
        shell = CorrigibilityShell()
        engine = self._engine(shell)
        result = engine.evaluate(
            _proposal(),
            _operation(),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        rid = result.policy_approval_id
        engine.consume_approval(rid)
        with self.assertRaises(PolicyApprovalConsumed):
            engine.consume_approval(rid)


class IdempotentMintTest(unittest.TestCase):
    """F2: repeated evaluate reuses the existing active record."""

    def test_repeated_evaluate_returns_same_record_id(self) -> None:
        engine = PolicyEngine(RuntimeFeatureFlags(r4_r5_auto_execution=True), now=lambda: _T0)
        engine.register_policy(_policy())
        r1 = engine.evaluate(
            _proposal(),
            _operation(),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        r2 = engine.evaluate(
            _proposal(),
            _operation(),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        self.assertEqual(r1.decision, "policy_pre_approved")
        self.assertEqual(r2.decision, "policy_pre_approved")
        self.assertEqual(r1.policy_approval_id, r2.policy_approval_id)

    def test_consume_invalidates_reused_record(self) -> None:
        engine = PolicyEngine(RuntimeFeatureFlags(r4_r5_auto_execution=True), now=lambda: _T0)
        engine.register_policy(_policy())
        r1 = engine.evaluate(
            _proposal(),
            _operation(),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        engine.consume_approval(r1.policy_approval_id)
        # after consume, a fresh evaluate mints a NEW record (old is consumed)
        r2 = engine.evaluate(
            _proposal(),
            _operation(),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        self.assertNotEqual(r1.policy_approval_id, r2.policy_approval_id)

    def test_different_proposals_get_different_records(self) -> None:
        engine = PolicyEngine(RuntimeFeatureFlags(r4_r5_auto_execution=True), now=lambda: _T0)
        engine.register_policy(_policy())
        r1 = engine.evaluate(
            _proposal("p-a"),
            _operation(),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        r2 = engine.evaluate(
            _proposal("p-b"),
            _operation(),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        self.assertNotEqual(r1.policy_approval_id, r2.policy_approval_id)


if __name__ == "__main__":
    unittest.main()
