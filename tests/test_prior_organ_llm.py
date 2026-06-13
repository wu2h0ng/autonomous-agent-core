"""Tests for the LLM prior-organ scaffold (G6b, ADR-0019) — the key property is
that an UNTRUSTED LLM can only ever nudge belief, never act or touch the shell.
"""
from __future__ import annotations

import inspect
import random
import unittest

import aac.prior_organ_llm as llm_module
from aac.agent import Agent
from aac.prior_organ import BeliefSnapshot
from aac.prior_organ_llm import DeterministicStubBackend, LLMPriorOrgan
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.structured_regime import StructuredRegimeEnv


class _MaliciousBackend:
    """Returns every dangerous field an LLM might emit; none may survive."""

    def propose(self, prompt):
        return {
            "belief_delta": {0: 2.0, "9": 99.0, "x": 1.0},  # valid 0; out-of-range/junk dropped
            "uncertainty": 0.5,
            "action": 3,
            "forbidden": [],
            "pause": False,
            "policy": {"forbidden": []},
            "shell": "op_resume",
            "op_resume": True,
        }


def _belief(n=4):
    return BeliefSnapshot(mu=(0.0,) * n, uncertainty=(0.5,) * n, last_surprise=0.1)


class TestUntrustedParsing(unittest.TestCase):
    def test_only_belief_fields_survive(self) -> None:
        advice = LLMPriorOrgan(backend=_MaliciousBackend()).advise({}, _belief(4))
        # only the valid in-range belief_delta entry + uncertainty remain
        self.assertEqual(advice.belief_delta, {0: 2.0})
        self.assertEqual(advice.uncertainty, 0.5)
        # OrganAdvice structurally cannot carry action/policy/shell
        self.assertEqual(
            set(advice.__dataclass_fields__),
            {"belief_delta", "uncertainty", "counterfactual_hint", "uncertainty_delta"},
        )
        for f in ("action", "policy", "shell", "forbidden", "pause", "op_resume"):
            self.assertFalse(hasattr(advice, f))

    def test_garbage_response_is_neutralised(self) -> None:
        class _Garbage:
            def propose(self, prompt):
                return "not even a dict"
        advice = LLMPriorOrgan(backend=_Garbage()).advise({}, _belief())
        self.assertEqual(advice.belief_delta, {})
        self.assertEqual(advice.uncertainty, 0.0)

    def test_runaway_delta_is_clamped(self) -> None:
        class _Runaway:
            def propose(self, prompt):
                return {"belief_delta": {0: 1e9}, "uncertainty": 1.0}
        advice = LLMPriorOrgan(backend=_Runaway(), max_abs_delta=10.0).advise({}, _belief())
        self.assertEqual(advice.belief_delta[0], 10.0)

    def test_nonfinite_and_out_of_range_dropped(self) -> None:
        class _Bad:
            def propose(self, prompt):
                return {"belief_delta": {0: float("inf"), 99: 1.0}, "uncertainty": 2.0}
        advice = LLMPriorOrgan(backend=_Bad()).advise({}, _belief(4))
        self.assertEqual(advice.belief_delta, {})  # inf dropped, 99 out of range
        self.assertEqual(advice.uncertainty, 1.0)  # clamped into [0,1]

    def test_module_imports_no_policy_or_shell(self) -> None:
        src = inspect.getsource(llm_module)
        self.assertNotIn("import aac.policy", src)
        self.assertNotIn("from .policy", src)
        self.assertNotIn("from .shell", src)


class TestLLMOrganCorrigibility(unittest.TestCase):
    def _agent(self, backend, seed=0):
        shell = CorrigibilityShell()
        agent = Agent(
            n_actions=8, shell=shell, rng=random.Random(seed),
            viability=ViabilityCore(budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0),
            prior_organ=LLMPriorOrgan(backend=backend),
        )
        return agent, shell

    def test_pause_and_tighten_hold_with_llm_organ(self) -> None:
        agent, shell = self._agent(DeterministicStubBackend())
        env = StructuredRegimeEnv(rng=random.Random(1))
        for _ in range(50):
            agent.step(env)
        shell.op_tighten(0)
        for _ in range(100):
            rec = agent.step(env)
            if rec is not None:
                self.assertNotEqual(rec["action"], 0)
        shell.op_pause()
        self.assertIsNone(agent.step(env))

    def test_malicious_llm_cannot_unpause_or_act_forbidden(self) -> None:
        agent, shell = self._agent(_MaliciousBackend())
        env = StructuredRegimeEnv(rng=random.Random(2))
        shell.op_tighten(3)
        shell.op_pause()
        for _ in range(20):
            self.assertIsNone(agent.step(env), "malicious LLM organ must not un-pause")
        self.assertTrue(shell.paused)


if __name__ == "__main__":
    unittest.main()
