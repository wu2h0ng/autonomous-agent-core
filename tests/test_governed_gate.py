"""Contract tests for AgentSelfModel + GovernedDecisionGate (REF-ARCH-03/04, ADR-0048).

These tests encode the governance contract and MUST fail if the gate is bypassed,
returns a constant, or trusts unverified high-stakes output. Written before the
implementation (Hard Boundary #17).
"""

from __future__ import annotations

import unittest

from aac.self_model import AgentSelfModel, ActionRequest
from aac.governed_gate import GovernedDecisionGate, ALLOW, VERIFY_MORE, ESCALATE, DENY
from aac.shell import CorrigibilityShell


def _self_model(**over) -> AgentSelfModel:
    base = dict(
        allowed_tools=frozenset({"read_metric", "propose_lever", "apply_lever"}),
        denied_tools=frozenset({"drop_table"}),
        approval_required_at_or_above=4,        # R4/R5 need approval = high stakes
        evidence_requirements={0: 0, 1: 1, 2: 1, 3: 2, 4: 3, 5: 3},
        confidence_thresholds={0: 0.0, 1: 0.5, 2: 0.6, 3: 0.7, 4: 0.8, 5: 0.9},
        risk_ceiling=5,
    )
    base.update(over)
    return AgentSelfModel(**base)


def _req(**over) -> ActionRequest:
    base = dict(action="apply_lever", risk_tier=1, confidence=0.9, verified=True, evidence_count=3, approved=False)
    base.update(over)
    return ActionRequest(**base)


class HardBoundaries(unittest.TestCase):
    def test_denied_tool_is_denied(self):
        gate = GovernedDecisionGate(_self_model())
        d = gate.decide(_req(action="drop_table"))
        self.assertEqual(d.verdict, DENY)

    def test_unknown_tool_is_denied(self):
        gate = GovernedDecisionGate(_self_model())
        d = gate.decide(_req(action="exfiltrate"))
        self.assertEqual(d.verdict, DENY)

    def test_paused_shell_blocks(self):
        shell = CorrigibilityShell()
        shell.op_pause()
        gate = GovernedDecisionGate(_self_model())
        d = gate.decide(_req(), shell_view=shell.view())
        self.assertIn(d.verdict, (DENY, ESCALATE))
        self.assertNotEqual(d.verdict, ALLOW)


class HighStakesNeverTrustUnverified(unittest.TestCase):
    """ADR-0047/0048: high-stakes must NEVER act on unverified output."""

    def test_high_risk_unverified_escalates_even_if_confident(self):
        gate = GovernedDecisionGate(_self_model())
        d = gate.decide(_req(risk_tier=4, verified=False, confidence=0.99, evidence_count=3))
        self.assertEqual(d.verdict, ESCALATE)  # NOT allow — the load-bearing rule

    def test_high_risk_verified_but_unapproved_escalates(self):
        gate = GovernedDecisionGate(_self_model())
        d = gate.decide(_req(risk_tier=5, verified=True, confidence=0.95, evidence_count=3, approved=False))
        self.assertEqual(d.verdict, ESCALATE)  # R5 needs human approval

    def test_high_risk_verified_and_approved_allows(self):
        gate = GovernedDecisionGate(_self_model())
        d = gate.decide(_req(risk_tier=4, verified=True, confidence=0.9, evidence_count=3, approved=True))
        self.assertEqual(d.verdict, ALLOW)


class LowStakesCalibratedTrust(unittest.TestCase):
    def test_low_risk_verified_confident_allows(self):
        gate = GovernedDecisionGate(_self_model())
        d = gate.decide(_req(risk_tier=1, verified=True, confidence=0.9, evidence_count=2))
        self.assertEqual(d.verdict, ALLOW)

    def test_low_risk_low_confidence_verifies_more(self):
        gate = GovernedDecisionGate(_self_model())
        d = gate.decide(_req(risk_tier=2, verified=False, confidence=0.1, evidence_count=2))
        self.assertEqual(d.verdict, VERIFY_MORE)

    def test_low_risk_unreliable_llm_escalates_when_unverified(self):
        gate = GovernedDecisionGate(_self_model())
        # unverified + low confidence + low LLM reliability -> cannot calibrate-trust -> escalate
        d = gate.decide(_req(risk_tier=2, verified=False, confidence=0.3, evidence_count=1),
                        llm_reliability=0.2)
        self.assertIn(d.verdict, (VERIFY_MORE, ESCALATE))
        self.assertNotEqual(d.verdict, ALLOW)

    def test_insufficient_evidence_does_not_allow(self):
        gate = GovernedDecisionGate(_self_model())
        d = gate.decide(_req(risk_tier=3, verified=True, confidence=0.9, evidence_count=0))
        self.assertNotEqual(d.verdict, ALLOW)


class NotAConstant(unittest.TestCase):
    """Guard against a constant-return implementation: the gate must produce
    different verdicts for different inputs."""

    def test_verdicts_vary(self):
        gate = GovernedDecisionGate(_self_model())
        verdicts = {
            gate.decide(_req(action="drop_table")).verdict,
            gate.decide(_req(risk_tier=4, verified=False)).verdict,
            gate.decide(_req(risk_tier=1, verified=True, confidence=0.9, evidence_count=2)).verdict,
            gate.decide(_req(risk_tier=2, verified=False, confidence=0.1, evidence_count=2)).verdict,
        }
        self.assertGreaterEqual(len(verdicts), 3)


if __name__ == "__main__":
    unittest.main()
