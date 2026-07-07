"""Test-first unit tests for the R4/R5 auto-execution PolicyEngine (workstream E / ADR-0012).

Covers every negative path required by ADR-0012 section 3.6:

- default proposal-only when no policy / flag off
- policy deny
- paused shell blocks auto-exec (C7 supremacy)
- incomplete evidence blocks
- failed dry-run blocks
- guardrail floors (confidence, delta) block
- not-auto-executable operation blocks
- R4 without rollback blocks
- R5 without compensating action blocks
- revoked / consumed / stale-version approval records are invalid

Default flag is off; when off every evaluation returns ``proposal_only``.
"""

from __future__ import annotations

import unittest

from agent_os_contracts import (
    ActionProposal,
    AutoExecutionPolicy,
    AutoExecutionRule,
    OperationContract,
    PolicyApprovalRecord,
    RiskLevel,
    RuntimeFeatureFlags,
)
from agent_os_core import CorrigibilityShell
from agent_os_core.policy_engine import (
    GuardrailInput,
    PolicyEngine,
    PolicyApprovalRecordStore,
)

_T0 = "2026-07-07T00:00:00+00:00"


def _rule(
    rule_id: str = "rule-1",
    action_type: str = "adjust_budget",
    risk_levels: tuple[str, ...] = ("R4",),
    mode: str = "policy_pre_approved",
    guard: dict | None = None,
    compensating: str | None = "rollback_budget",
) -> AutoExecutionRule:
    return AutoExecutionRule(
        rule_id=rule_id,
        action_type=action_type,
        risk_levels=risk_levels,
        mode=mode,
        guard_conditions=guard
        or {
            "dry_run_success": True,
            "evidence_complete": True,
            "confidence_min": 0.9,
            "max_delta_pct": 10.0,
        },
        compensating_action=compensating,
    )


def _policy(rules=(_rule(),), version: str = "v1") -> AutoExecutionPolicy:
    return AutoExecutionPolicy(
        version=version,
        tenant_id="tenant-1",
        owner="policy-owner",
        rules=tuple(rules),
        default_mode="proposal_only",
    )


def _operation(
    risk_level: str = "R4",
    *,
    auto_executable: bool = True,
    rollback_supported: bool = True,
    compensating_action: str | None = "rollback_budget",
    action_type: str = "adjust_budget",
) -> OperationContract:
    return OperationContract(
        operation_id="op-1",
        name="Adjust Budget",
        target_connector="action_record",
        risk_level=risk_level,
        approval_required=True,
        dry_run_required=True,
        rollback_supported=rollback_supported,
        compensating_action=compensating_action,
        connector_name="action_record",
        action_type=action_type,
        auto_executable=auto_executable,
    )


def _proposal(
    risk_level: RiskLevel = RiskLevel.R4,
    action_type: str = "adjust_budget",
) -> ActionProposal:
    return ActionProposal(
        proposal_id="proposal-1",
        evidence_chain_id="ev-1",
        target_object="campaign-1",
        recommended_action="adjust_budget",
        reason="roi optimization",
        risk_level=risk_level,
        expected_impact="lower spend",
        approval_required=True,
        approver_role="finance",
        connector_name="action_record",
        action_type=action_type,
    )


def _guards(
    *,
    dry_run_success: bool = True,
    evidence_complete: bool = True,
    confidence: float = 0.95,
    metric_delta_pct: float = 3.0,
) -> GuardrailInput:
    return GuardrailInput(
        dry_run_success=dry_run_success,
        evidence_complete=evidence_complete,
        confidence=confidence,
        metric_delta_pct=metric_delta_pct,
    )


class PolicyEngineFlagDefaultTest(unittest.TestCase):
    def test_flag_off_returns_proposal_only(self) -> None:
        engine = PolicyEngine(RuntimeFeatureFlags())  # r4_r5_auto_execution=False
        engine.register_policy(_policy())
        result = engine.evaluate(
            _proposal(),
            _operation(),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        self.assertEqual(result.decision, "proposal_only")
        self.assertEqual(result.reason, "feature_disabled")

    def test_no_policy_returns_proposal_only(self) -> None:
        engine = PolicyEngine(RuntimeFeatureFlags(r4_r5_auto_execution=True))
        # no policy registered for tenant-2
        result = engine.evaluate(
            _proposal(),
            _operation(),
            _guards(),
            tenant_id="tenant-2",
            trace_id="trace-1",
        )
        self.assertEqual(result.decision, "proposal_only")


class PolicyEnginePreApprovalTest(unittest.TestCase):
    def _engine(self) -> PolicyEngine:
        engine = PolicyEngine(RuntimeFeatureFlags(r4_r5_auto_execution=True), now=lambda: _T0)
        engine.register_policy(_policy())
        return engine

    def test_all_guardrails_pass_pre_approves(self) -> None:
        engine = self._engine()
        result = engine.evaluate(
            _proposal(),
            _operation(),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        self.assertEqual(result.decision, "policy_pre_approved")
        self.assertIsNotNone(result.policy_approval_id)
        self.assertEqual(result.rule_id, "rule-1")

    def test_proposal_only_rule_returns_proposal_only(self) -> None:
        engine = PolicyEngine(RuntimeFeatureFlags(r4_r5_auto_execution=True))
        engine.register_policy(_policy(rules=(_rule(mode="proposal_only"),)))
        result = engine.evaluate(
            _proposal(),
            _operation(),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        self.assertEqual(result.decision, "proposal_only")


class PolicyEngineNegativePathsTest(unittest.TestCase):
    def _engine(self) -> PolicyEngine:
        engine = PolicyEngine(RuntimeFeatureFlags(r4_r5_auto_execution=True), now=lambda: _T0)
        engine.register_policy(_policy())
        return engine

    def test_no_matching_rule_denies(self) -> None:
        engine = self._engine()
        result = engine.evaluate(
            _proposal(action_type="unknown_action"),
            _operation(action_type="unknown_action"),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        self.assertEqual(result.decision, "proposal_only")

    def test_paused_blocks(self) -> None:
        engine = self._engine()
        shell = CorrigibilityShell()
        shell.op_pause()
        engine = PolicyEngine(
            RuntimeFeatureFlags(r4_r5_auto_execution=True), shell=shell, now=lambda: _T0
        )
        engine.register_policy(_policy())
        result = engine.evaluate(
            _proposal(),
            _operation(),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        self.assertEqual(result.decision, "denied")
        self.assertEqual(result.reason, "paused")

    def test_incomplete_evidence_blocks(self) -> None:
        engine = self._engine()
        result = engine.evaluate(
            _proposal(),
            _operation(),
            _guards(evidence_complete=False),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        self.assertEqual(result.decision, "denied")
        self.assertEqual(result.reason, "evidence_incomplete")

    def test_dry_run_failure_blocks(self) -> None:
        engine = self._engine()
        result = engine.evaluate(
            _proposal(),
            _operation(),
            _guards(dry_run_success=False),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        self.assertEqual(result.decision, "denied")
        self.assertEqual(result.reason, "dry_run_failed")

    def test_confidence_below_floor_blocks(self) -> None:
        engine = self._engine()
        result = engine.evaluate(
            _proposal(),
            _operation(),
            _guards(confidence=0.5),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        self.assertEqual(result.decision, "denied")
        self.assertIn("guardrail_failed", result.reason)

    def test_delta_exceeds_max_blocks(self) -> None:
        engine = self._engine()
        result = engine.evaluate(
            _proposal(),
            _operation(),
            _guards(metric_delta_pct=20.0),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        self.assertEqual(result.decision, "denied")
        self.assertIn("guardrail_failed", result.reason)

    def test_not_auto_executable_blocks(self) -> None:
        engine = self._engine()
        result = engine.evaluate(
            _proposal(),
            _operation(auto_executable=False),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        self.assertEqual(result.decision, "denied")
        self.assertEqual(result.reason, "not_auto_executable")

    def test_r4_without_rollback_blocks(self) -> None:
        engine = self._engine()
        result = engine.evaluate(
            _proposal(),
            _operation(risk_level="R4", rollback_supported=False, compensating_action=None),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        self.assertEqual(result.decision, "denied")
        self.assertEqual(result.reason, "missing_rollback_compensation")

    def test_r5_without_compensating_action_blocks(self) -> None:
        engine = PolicyEngine(RuntimeFeatureFlags(r4_r5_auto_execution=True), now=lambda: _T0)
        engine.register_policy(
            _policy(rules=(_rule(risk_levels=("R5",), compensating="escalate_human"),))
        )
        result = engine.evaluate(
            _proposal(risk_level=RiskLevel.R5),
            _operation(risk_level="R5", rollback_supported=False, compensating_action=None),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        self.assertEqual(result.decision, "denied")
        self.assertEqual(result.reason, "missing_rollback_compensation")


class PolicyApprovalRecordStoreTest(unittest.TestCase):
    def _record(self, **kw) -> PolicyApprovalRecord:
        base = dict(
            record_id="par-1",
            trace_id="trace-1",
            proposal_id="proposal-1",
            rule_id="rule-1",
            policy_version="v1",
            tenant_id="tenant-1",
            created_at=_T0,
        )
        base.update(kw)
        return PolicyApprovalRecord(**base)

    def test_active_then_revoke(self) -> None:
        store = PolicyApprovalRecordStore()
        store.save(self._record())
        self.assertTrue(store.is_active("par-1", policy_version="v1"))
        store.revoke("par-1", revoked_at=_T0)
        self.assertFalse(store.is_active("par-1", policy_version="v1"))

    def test_consume_makes_inactive(self) -> None:
        store = PolicyApprovalRecordStore()
        store.save(self._record())
        store.consume("par-1")
        self.assertFalse(store.is_active("par-1", policy_version="v1"))

    def test_stale_policy_version_invalid(self) -> None:
        store = PolicyApprovalRecordStore()
        store.save(self._record(policy_version="v1"))
        self.assertFalse(store.is_active("par-1", policy_version="v2"))

    def test_missing_record_invalid(self) -> None:
        store = PolicyApprovalRecordStore()
        self.assertFalse(store.is_active("nope", policy_version="v1"))


class PolicyEngineApplyDecisionTest(unittest.TestCase):
    def test_apply_decision_sets_execution_mode(self) -> None:
        engine = PolicyEngine(RuntimeFeatureFlags(r4_r5_auto_execution=True), now=lambda: _T0)
        engine.register_policy(_policy())
        proposal = _proposal()
        result = engine.evaluate(
            proposal,
            _operation(),
            _guards(),
            tenant_id="tenant-1",
            trace_id="trace-1",
        )
        updated = engine.apply_decision(proposal, result)
        self.assertEqual(updated.execution_mode, "policy_pre_approved")


if __name__ == "__main__":
    unittest.main()
