"""Agent.governed_step — the vertical slice wired into the formal Agent (REF-ARCH #1).

Asserts the governed decision path reuses the Agent's belief/shell and enforces verify-before-decide:
the loop skips a belief-ranked decoy the verifier rejects, acts on the verified true cause, escalates
high-stakes, respects the paused shell, and step() is unaffected (existing 518 tests cover that).
"""

from __future__ import annotations

import random
import unittest

from aac.agent import Agent
from aac.governed_gate import GovernedDecisionGate
from aac.governed_loop import VerifyResult, TaskSpec
from aac.self_model import AgentSelfModel
from aac.shell import CorrigibilityShell


class LeverEnv:
    def __init__(self, c: int) -> None:
        self.c = c

    def act(self, a: int) -> float:
        return 1.0 if a == self.c else 0.0

    def probe(self, a: int) -> bool:        # read-only interventional check
        return a == self.c


class ProbeVerifier:
    def __init__(self, env: LeverEnv) -> None:
        self.env = env

    def verify(self, cand) -> VerifyResult:
        eff = self.env.probe(cand.target)
        return VerifyResult(eff, 0.9 if eff else 0.0, 3 if eff else 0, 1)


def _sm() -> AgentSelfModel:
    return AgentSelfModel(
        allowed_tools=frozenset(), denied_tools=frozenset(),
        risk_ceiling=5, approval_required_at_or_above=4,
        evidence_requirements={1: 1, 4: 1}, confidence_thresholds={1: 0.2, 4: 0.6},
    )


def _agent(env, **kw):
    a = Agent(n_actions=4, shell=CorrigibilityShell(), rng=random.Random(0),
              governed_gate=GovernedDecisionGate(_sm()), verifier=ProbeVerifier(env), **kw)
    # make the belief rank a DECOY (action 0) first; the true cause (env.c) is ranked lower
    for i in range(4):
        a.model.mu[i] = 0.1
    a.model.mu[0] = 5.0          # decoy ranked first by belief
    a.model.mu[env.c] = 1.0      # true cause ranked below the decoy
    return a


class AgentGovernedStep(unittest.TestCase):
    def test_skips_belief_ranked_decoy_acts_on_verified_cause(self):
        env = LeverEnv(c=2)
        res = _agent(env).governed_step(env, TaskSpec("t", risk_tier=1))
        self.assertEqual(res.status, "acted")
        self.assertEqual(res.applied_target, 2)   # NOT the belief-ranked decoy (0)
        self.assertEqual(res.outcome, 1.0)

    def test_high_stakes_unapproved_escalates(self):
        env = LeverEnv(c=2)
        res = _agent(env).governed_step(env, TaskSpec("t", risk_tier=4, approved=False))
        self.assertEqual(res.status, "escalated")

    def test_high_stakes_approved_acts(self):
        env = LeverEnv(c=2)
        res = _agent(env).governed_step(env, TaskSpec("t", risk_tier=4, approved=True))
        self.assertEqual(res.status, "acted")
        self.assertEqual(res.applied_target, 2)

    def test_paused_shell_is_noop(self):
        env = LeverEnv(c=2)
        shell = CorrigibilityShell(); shell.op_pause()
        a = Agent(n_actions=4, shell=shell, rng=random.Random(0),
                  governed_gate=GovernedDecisionGate(_sm()), verifier=ProbeVerifier(env))
        self.assertIsNone(a.governed_step(env, TaskSpec("t", risk_tier=1)))

    def test_requires_gate_and_verifier(self):
        env = LeverEnv(c=2)
        a = Agent(n_actions=4, shell=CorrigibilityShell(), rng=random.Random(0))
        with self.assertRaises(ValueError):
            a.governed_step(env, TaskSpec("t", risk_tier=1))

    def test_plain_step_still_works_without_governed_config(self):
        env = LeverEnv(c=2)
        a = Agent(n_actions=4, shell=CorrigibilityShell(), rng=random.Random(0))
        rec = a.step(env)
        self.assertIsNotNone(rec)
        self.assertIn("action", rec)


if __name__ == "__main__":
    unittest.main()
