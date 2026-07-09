"""Contract tests for E9 SelfMaintenanceLoop — governed persistence self-production under C7.

Hard Boundary #17: tests must fail if the loop acts without gate approval,
ignores C7 shell state, or claims autonomous persistence.
"""

from __future__ import annotations

import random
import unittest

from aac.governed_gate import ALLOW, DENY, ESCALATE, GovernedDecisionGate
from aac.organ_regulator import OrganRegulator
from aac.self_maintenance import (
    HealthCheck,
    MaintenanceAction,
    MaintenanceLedger,
    SelfMaintenanceLoop,
)
from aac.self_model import ActionRequest, AgentSelfModel
from aac.self_model_updater import AgentSelfModelUpdater
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore


def _self_model(**over) -> AgentSelfModel:
    base = dict(
        allowed_tools=frozenset({
            "self_calibrate_confidence", "rebalance_organs",
            "reset_epistemic_state", "request_operator_attention",
            "viability_critical",
        }),
        denied_tools=frozenset(),
        approval_required_at_or_above=4,
        evidence_requirements={0: 0, 1: 1},
        confidence_thresholds={0: 0.0, 1: 0.5},
        risk_ceiling=5,
    )
    base.update(over)
    return AgentSelfModel(**base)


class HealthCheckEvaluation(unittest.TestCase):
    def test_healthy_system_no_maintenance_needed(self):
        v = ViabilityCore(budget=70.0)
        reg = OrganRegulator()
        reg.register_organ("a", initial_credit=0.8)
        reg.register_organ("b", initial_credit=0.7)
        updater = AgentSelfModelUpdater(n_actions=4)
        gate = GovernedDecisionGate(_self_model())
        loop = SelfMaintenanceLoop(
            viability=v, organ_regulator=reg,
            self_model_updater=updater, gate=gate,
            shell_view=None,
        )
        actions = loop.step({"model": None})
        self.assertEqual(actions, [])

    def test_high_pressure_triggers_maintenance(self):
        v = ViabilityCore(budget=5.0, safe_budget=50.0)
        reg = OrganRegulator()
        reg.register_organ("a", initial_credit=0.5)
        updater = AgentSelfModelUpdater(n_actions=4)
        gate = GovernedDecisionGate(_self_model())
        loop = SelfMaintenanceLoop(
            viability=v, organ_regulator=reg,
            self_model_updater=updater, gate=gate,
            shell_view=None,
            pressure_threshold=0.5,
        )
        actions = loop.step({"model": None})
        self.assertGreater(len(actions), 0)
        self.assertTrue(any("pressure" in a.description for a in actions))


class C7Compliance(unittest.TestCase):
    """All maintenance actions must be blocked when C7 is paused."""

    def test_paused_shell_blocks_maintenance(self):
        shell = CorrigibilityShell()
        shell.op_pause()
        v = ViabilityCore(budget=5.0, safe_budget=50.0)
        reg = OrganRegulator()
        reg.register_organ("a", initial_credit=0.5)
        updater = AgentSelfModelUpdater(n_actions=4)
        gate = GovernedDecisionGate(_self_model())
        loop = SelfMaintenanceLoop(
            viability=v, organ_regulator=reg,
            self_model_updater=updater, gate=gate,
            shell_view=shell.view(),
            pressure_threshold=0.5,
        )
        actions = loop.step({"model": None})
        for action in actions:
            result = loop.execute_maintenance(action, lambda a: 1.0)
            self.assertNotEqual(result, ALLOW)

    def test_forbidden_action_blocked(self):
        shell = CorrigibilityShell()
        sm = _self_model(denied_tools=frozenset({"self_calibrate_confidence"}))
        gate = GovernedDecisionGate(sm)
        v = ViabilityCore(budget=5.0, safe_budget=50.0)
        reg = OrganRegulator()
        reg.register_organ("a", initial_credit=0.5)
        updater = AgentSelfModelUpdater(n_actions=4)
        loop = SelfMaintenanceLoop(
            viability=v, organ_regulator=reg,
            self_model_updater=updater, gate=gate,
            shell_view=shell.view(),
        )
        action = MaintenanceAction(
            action_id="self_calibrate_confidence",
            category="self_calibrate",
            description="test",
        )
        result = loop.execute_maintenance(action, lambda a: 1.0)
        self.assertNotEqual(result, ALLOW)


class MaintenanceLedgerTest(unittest.TestCase):
    def test_records_maintenance_actions(self):
        ledger = MaintenanceLedger()
        ledger.record("a1", "self_calibrate", ALLOW, "ok", outcome=1.0)
        self.assertEqual(len(ledger.entries), 1)
        self.assertEqual(ledger.entries[0]["action"], "a1")

    def test_recent_actions_limited(self):
        ledger = MaintenanceLedger()
        for i in range(20):
            ledger.record(f"a{i}", "cat", ALLOW, "ok")
        self.assertEqual(len(ledger.recent_actions(5)), 5)


class MaintainabilityGate(unittest.TestCase):
    def test_no_bypass_risk_ceiling(self):
        sm = _self_model(risk_ceiling=-1)
        gate = GovernedDecisionGate(sm)
        v = ViabilityCore(budget=5.0, safe_budget=50.0)
        loop = SelfMaintenanceLoop(
            viability=v, organ_regulator=None,
            self_model_updater=None, gate=gate,
            shell_view=None,
        )
        action = MaintenanceAction(
            action_id="self_calibrate_confidence",
            category="self_calibrate",
            description="test",
            risk_tier=0,
        )
        result = loop.execute_maintenance(action, lambda a: 1.0)
        self.assertEqual(result, ESCALATE)

    def test_ledger_counts_maintenance_actions(self):
        v = ViabilityCore(budget=70.0)
        reg = OrganRegulator()
        reg.register_organ("a", initial_credit=0.8)
        updater = AgentSelfModelUpdater(n_actions=4)
        gate = GovernedDecisionGate(_self_model())
        loop = SelfMaintenanceLoop(
            viability=v, organ_regulator=reg,
            self_model_updater=updater, gate=gate,
            shell_view=None,
        )
        action = MaintenanceAction(
            action_id="self_calibrate_confidence",
            category="self_calibrate",
            description="test",
        )
        loop.execute_maintenance(action, lambda a: 1.0)
        self.assertEqual(loop.total_maintenance_actions, 1)
        self.assertGreater(len(loop.ledger.entries), 0)


class NotAConstant(unittest.TestCase):
    def test_severity_scales_with_pressure(self):
        v1 = ViabilityCore(budget=70.0, safe_budget=50.0)
        v2 = ViabilityCore(budget=5.0, safe_budget=50.0)
        reg = OrganRegulator()
        reg.register_organ("a", initial_credit=0.5)
        updater = AgentSelfModelUpdater(n_actions=4)
        gate = GovernedDecisionGate(_self_model())

        loop1 = SelfMaintenanceLoop(
            viability=v1, organ_regulator=reg, self_model_updater=updater,
            gate=gate, shell_view=None,
        )
        loop2 = SelfMaintenanceLoop(
            viability=v2, organ_regulator=reg, self_model_updater=updater,
            gate=gate, shell_view=None,
        )
        h1 = loop1._check_health(0.1)
        h2 = loop2._check_health(0.1)
        self.assertLess(h1.severity, h2.severity)

    def test_dead_system_needs_maintenance(self):
        v = ViabilityCore(budget=0.0, death_threshold=0.0)
        reg = OrganRegulator()
        reg.register_organ("a", initial_credit=0.5)
        updater = AgentSelfModelUpdater(n_actions=4)
        gate = GovernedDecisionGate(_self_model())
        loop = SelfMaintenanceLoop(
            viability=v, organ_regulator=reg,
            self_model_updater=updater, gate=gate,
            shell_view=None,
        )
        health = loop._check_health(0.1)
        self.assertFalse(health.viability_alive)
        self.assertTrue(health.maintenance_needed)


class StateRoundtrip(unittest.TestCase):
    def test_roundtrip(self):
        v = ViabilityCore(budget=70.0)
        gate = GovernedDecisionGate(_self_model())
        loop = SelfMaintenanceLoop(
            viability=v, organ_regulator=None,
            self_model_updater=None, gate=gate,
            shell_view=None,
        )
        loop.steps_since_check = 10
        loop.total_maintenance_actions = 3
        loop._previous_uncertainty = 0.3
        loop.ledger.record("a", "cat", ALLOW, "ok")

        saved = loop.state()
        restored = SelfMaintenanceLoop(
            viability=v, organ_regulator=None,
            self_model_updater=None, gate=gate,
            shell_view=None,
        )
        restored.restore(saved)
        self.assertEqual(restored.steps_since_check, 10)
        self.assertEqual(restored.total_maintenance_actions, 3)
        self.assertEqual(restored._previous_uncertainty, 0.3)
        self.assertEqual(len(restored.ledger.entries), 1)


if __name__ == "__main__":
    unittest.main()
