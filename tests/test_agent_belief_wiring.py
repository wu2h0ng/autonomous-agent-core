"""Agent-level wiring of BeliefLedger + attribution + stratified assembly (step (b)).

The subject entry point (governed_step) must: cite goal-scoped claims on candidates,
consume stratified evidence, record fresh VI claims on verified success, and demote
exactly the cited claim on failure — the full Stage-1/2 chain closed on the Agent.
"""
from __future__ import annotations

import random
import unittest

from aac.agent import Agent
from aac.belief_ledger import BeliefLedger, FACT
from aac.governed_gate import GovernedDecisionGate
from aac.governed_loop import VerifyResult, TaskSpec
from aac.self_model import AgentSelfModel
from aac.shell import CorrigibilityShell


class LeverEnv:
    def __init__(self, c): self.c = c
    def act(self, a): return 1.0 if a == self.c else 0.0
    def probe(self, a): return a == self.c


class ProbeVerifier:
    def __init__(self, env): self.env = env
    def verify(self, cand):
        eff = self.env.probe(cand.target)
        return VerifyResult(eff, 0.9 if eff else 0.0, 3 if eff else 0, 1)


class LyingVerifier:
    """Passes action 0 (wrong) — models a noisy false-positive so the act FAILS."""
    def verify(self, cand):
        eff = cand.target == 0
        return VerifyResult(eff, 0.9 if eff else 0.0, 3 if eff else 0, 1)


def _sm():
    return AgentSelfModel(allowed_tools=frozenset(), denied_tools=frozenset(),
                          risk_ceiling=5, approval_required_at_or_above=4,
                          evidence_requirements={1: 1, 4: 1},
                          confidence_thresholds={1: 0.2, 4: 0.6})


def _agent(env, ledger, verifier=None):
    a = Agent(n_actions=4, shell=CorrigibilityShell(), rng=random.Random(0),
              governed_gate=GovernedDecisionGate(_sm()),
              verifier=verifier or ProbeVerifier(env), belief_ledger=ledger)
    for i in range(4):
        a.model.mu[i] = 0.1
    a.model.mu[env.c] = 1.0
    return a


class AgentBeliefWiring(unittest.TestCase):
    def test_success_records_fresh_vi_claim(self):
        env = LeverEnv(c=2)
        led = BeliefLedger()
        res = _agent(env, led).governed_step(env, TaskSpec("t", risk_tier=1))
        self.assertEqual(res.status, "acted")
        e = led.get("causal:t:2")
        self.assertIsNotNone(e)
        self.assertEqual(e.kind, FACT)
        self.assertFalse(e.stale)

    def test_failure_demotes_exactly_the_cited_claim(self):
        env = LeverEnv(c=2)
        led = BeliefLedger()
        led.record_verified("causal:t:0", evidence=3)      # stale belief: 0 was causal once
        led.record_verified("causal:t:2", evidence=3)      # unrelated claim must be untouched
        a = _agent(env, led, verifier=LyingVerifier())     # verifier false-passes 0 -> act fails
        a.model.mu[0] = 5.0                                # belief ranks the stale action first
        res = a.governed_step(env, TaskSpec("t", risk_tier=1))
        self.assertEqual(res.status, "acted")
        self.assertEqual(res.outcome, 0.0)
        self.assertTrue(led.get("causal:t:0").stale)       # demoted (I2 precise)
        self.assertFalse(led.get("causal:t:2").stale)      # neighbor untouched

    def test_candidates_cite_ledger_claims(self):
        env = LeverEnv(c=2)
        led = BeliefLedger()
        led.record_verified("causal:t:2", evidence=3)
        res = _agent(env, led).governed_step(env, TaskSpec("t", risk_tier=1))
        acted = [s for s in res.steps if s.verdict == "ALLOW"][-1]
        self.assertIn("causal:t:2", acted.cited_claim_ids)

    def test_stratified_assembly_consumed(self):
        # cited fresh VI evidence tops up a thin verifier: tier-4 evidence bar 1 is met by
        # citation only when the ledger is wired (evidence_count would be 0 otherwise).
        env = LeverEnv(c=2)
        led = BeliefLedger()
        led.record_verified("causal:t:2", evidence=2)

        class ThinVerifier:
            def verify(self, cand):
                eff = cand.target == 2
                return VerifyResult(eff, 0.9 if eff else 0.0, 0, 1)   # zero bound evidence

        res = _agent(env, led, verifier=ThinVerifier()).governed_step(
            env, TaskSpec("t", risk_tier=4, approved=True))
        self.assertEqual(res.status, "acted")               # only passes via cited VI top-up


if __name__ == "__main__":
    unittest.main()
