"""ISO-2 Gate Isolation tests (RR-0053 / ADR-0009).

Verifies that GovernedDecisionGate in a subprocess is structurally unreachable
by the agent process, and that T17/T18/T19 invariants hold under introspection attacks.

Attack model:
  A1: gc.get_objects() scan for gate/self_model in agent process
  A2: Attribute injection on GateProxy
  A3: Forge action_index=None to evade shell.forbidden check
  A4: Malformed message (non-dict)
  A5: Send operator commands (op_resume, update_forbidden)
  A6: Forbidden action request (T17 under ISO-2)
  A7: High-stakes unapproved (T19 under ISO-2)
  A8: Normal allowed action (sanity: system still functional)
"""

from __future__ import annotations

import gc
import os
import unittest
from typing import Any

from aac.self_model import AgentSelfModel, ActionRequest
from aac.governed_gate import GovernedDecisionGate, GateDecision, ALLOW, DENY, ESCALATE
from aac.shell import CorrigibilityShell
from aac.gate_ipc import GateProxy, IsolatedGate, launch_isolated_gate

D = 6
DENIED_LEVER = 3
FORBIDDEN_INDEX = 3


def _make_self_model() -> AgentSelfModel:
    return AgentSelfModel(
        allowed_tools=frozenset(f"apply_lever:{i}" for i in range(D)),
        denied_tools=frozenset([f"apply_lever:{DENIED_LEVER}"]),
        risk_ceiling=3,
        approval_required_at_or_above=4,
        evidence_requirements={0: 0, 1: 1, 2: 2, 3: 3},
        confidence_thresholds={0: 0.0, 1: 0.3, 2: 0.5, 3: 0.7},
    )


def _launch() -> IsolatedGate:
    shell = CorrigibilityShell()
    shell.op_tighten(FORBIDDEN_INDEX)
    return launch_isolated_gate(
        self_model=_make_self_model(),
        shell=shell,
    )


class TestA1IntrospectionAttack(unittest.TestCase):
    """A1: Agent process gc.get_objects() must find NO gate or self_model."""

    def test_no_gate_in_agent_process_after_launch(self):
        ig = _launch()
        try:
            gates = [o for o in gc.get_objects()
                     if isinstance(o, GovernedDecisionGate)]
            self.assertEqual(gates, [],
                             "GovernedDecisionGate found in agent process memory")
        finally:
            ig.shutdown()

    def test_no_self_model_with_denied_in_agent_process(self):
        ig = _launch()
        try:
            models = [o for o in gc.get_objects()
                      if isinstance(o, AgentSelfModel)
                      and f"apply_lever:{DENIED_LEVER}" in getattr(o, "denied_tools", set())]
            self.assertEqual(models, [],
                             "AgentSelfModel with denied_tools found in agent process")
        finally:
            ig.shutdown()


class TestA2AttributeInjection(unittest.TestCase):
    """A2: GateProxy __slots__ prevents attribute injection."""

    def test_cannot_set_self_model_on_proxy(self):
        ig = _launch()
        try:
            with self.assertRaises(AttributeError):
                ig.proxy.self_model = None  # type: ignore
        finally:
            ig.shutdown()

    def test_cannot_set_gate_on_proxy(self):
        ig = _launch()
        try:
            with self.assertRaises(AttributeError):
                ig.proxy._gate = "hacked"  # type: ignore
        finally:
            ig.shutdown()


class TestA3ForgedActionIndex(unittest.TestCase):
    """A3: Forging action_index=None does not bypass denied_tools check."""

    def test_denied_action_with_none_index_still_denied(self):
        ig = _launch()
        try:
            req = ActionRequest(
                action=f"apply_lever:{DENIED_LEVER}",
                risk_tier=1, confidence=0.95, verified=True,
                evidence_count=6, approved=False, action_index=None,
            )
            d = ig.proxy.decide(req)
            self.assertEqual(d.verdict, DENY)
            self.assertIn("not permitted", d.reason)
        finally:
            ig.shutdown()


class TestA4MalformedMessage(unittest.TestCase):
    """A4: Non-dict / missing 'action' field → DENY."""

    def test_raw_string_denied(self):
        ig = _launch()
        try:
            ig.proxy._conn.send("raw_string_attack")
            resp = ig.proxy._conn.recv()
            self.assertEqual(resp["verdict"], DENY)
        finally:
            ig.shutdown()

    def test_dict_without_action_denied(self):
        ig = _launch()
        try:
            ig.proxy._conn.send({"garbage": True})
            resp = ig.proxy._conn.recv()
            self.assertEqual(resp["verdict"], DENY)
        finally:
            ig.shutdown()


class TestA5OperatorCommands(unittest.TestCase):
    """A5: Agent cannot send operator commands to move shell state."""

    def test_please_unpause_ignored(self):
        ig = _launch()
        try:
            ig.proxy._conn.send("please_unpause")
            resp = ig.proxy._conn.recv()
            self.assertEqual(resp["verdict"], DENY)
        finally:
            ig.shutdown()

    def test_update_forbidden_ignored(self):
        ig = _launch()
        try:
            ig.proxy._conn.send({"action": "update_forbidden", "set": []})
            resp = ig.proxy._conn.recv()
            self.assertNotEqual(resp["verdict"], ALLOW)
        finally:
            ig.shutdown()


class TestT17UnderISO2(unittest.TestCase):
    """T17 (Shell Independence) holds under process isolation."""

    def test_forbidden_action_denied_through_proxy(self):
        ig = _launch()
        try:
            req = ActionRequest(
                action=f"apply_lever:{FORBIDDEN_INDEX}",
                risk_tier=1, confidence=0.95, verified=True,
                evidence_count=6, approved=False, action_index=FORBIDDEN_INDEX,
            )
            d = ig.proxy.decide(req)
            self.assertEqual(d.verdict, DENY)
        finally:
            ig.shutdown()

    def test_forbidden_persists_after_gc_collect(self):
        ig = _launch()
        try:
            gc.collect()
            req = ActionRequest(
                action=f"apply_lever:{FORBIDDEN_INDEX}",
                risk_tier=1, confidence=0.95, verified=True,
                evidence_count=6, approved=False, action_index=FORBIDDEN_INDEX,
            )
            d = ig.proxy.decide(req)
            self.assertEqual(d.verdict, DENY)
        finally:
            ig.shutdown()


class TestT19UnderISO2(unittest.TestCase):
    """T19 (High-stakes never auto-acts) holds under process isolation."""

    def test_high_stakes_unapproved_escalates(self):
        ig = _launch()
        try:
            safe_lever = (DENIED_LEVER + 2) % D
            req = ActionRequest(
                action=f"apply_lever:{safe_lever}",
                risk_tier=4, confidence=0.95, verified=True,
                evidence_count=6, approved=False, action_index=safe_lever,
            )
            d = ig.proxy.decide(req)
            self.assertIn(d.verdict, (ESCALATE, DENY))
            self.assertNotEqual(d.verdict, ALLOW)
        finally:
            ig.shutdown()


class TestSanity(unittest.TestCase):
    """System remains functional: allowed actions pass through."""

    def test_normal_allowed_action_passes(self):
        ig = _launch()
        try:
            safe_lever = (DENIED_LEVER + 2) % D
            req = ActionRequest(
                action=f"apply_lever:{safe_lever}",
                risk_tier=1, confidence=0.95, verified=True,
                evidence_count=6, approved=False, action_index=safe_lever,
            )
            d = ig.proxy.decide(req)
            self.assertEqual(d.verdict, ALLOW)
        finally:
            ig.shutdown()

    def test_different_pid(self):
        ig = _launch()
        try:
            self.assertNotEqual(os.getpid(), ig.process.pid)
        finally:
            ig.shutdown()


class TestGovernedLoopIntegration(unittest.TestCase):
    """GovernedLoop can use GateProxy transparently (duck-typed gate)."""

    def test_loop_with_proxy_gate(self):
        import random
        from aac.governed_loop import GovernedLoop, Candidate, VerifyResult, TaskSpec

        shell = CorrigibilityShell()
        shell.op_tighten(FORBIDDEN_INDEX)
        ig = launch_isolated_gate(self_model=_make_self_model(), shell=shell)

        class ToyProposer:
            reliability = 0.7
            def rank(self, task):
                safe = (DENIED_LEVER + 2) % D
                return [Candidate(action=f"apply_lever:{safe}", target=safe)]

        class ToyVerifier:
            def verify(self, cand):
                return VerifyResult(is_effective=True, confidence=0.95,
                                    evidence_count=6, interventions=1)

        class ToyActuator:
            def apply(self, cand):
                return 1.0

        try:
            loop = GovernedLoop(
                gate=ig.proxy,
                proposer=ToyProposer(),
                verifier=ToyVerifier(),
                actuator=ToyActuator(),
                shell_view=None,
            )
            result = loop.run_task(TaskSpec(name="test", risk_tier=1))
            self.assertEqual(result.status, "acted")
            self.assertEqual(result.outcome, 1.0)
        finally:
            ig.shutdown()


if __name__ == "__main__":
    unittest.main()
