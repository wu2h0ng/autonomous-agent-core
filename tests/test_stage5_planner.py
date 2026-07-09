"""STAGE-5 planner — proposal-form + no-narrowing contract tests (prereg 30b2c05)."""
from __future__ import annotations

import random
import unittest

from aac.planner import CWMPlanner, PlanProposal, PlanStep
from aac.governed_gate import GovernedDecisionGate
from aac.governed_loop import GovernedLoop, TaskSpec
from aac.shell import CorrigibilityShell
from experiments.governed_loop_slice import (
    CausalLeverEnv, InterventionVerifier, LeverActuator, _self_model, D,
)


class NoNarrowing(unittest.TestCase):
    def test_plan_covers_every_action_exactly_once(self):
        p = CWMPlanner(lambda a: float(a), D)
        cands = p.rank(TaskSpec("t", risk_tier=1))
        self.assertEqual(sorted(c.target for c in cands), list(range(D)))   # permutation, no subset

    def test_narrowing_planner_asserts(self):
        # a planner that proposes a SUBSET (drops an action while n_actions stays D) must trip
        # the no-narrowing assert in rank() — the structural guard against choice-set collapse.
        bad = CWMPlanner(lambda a: float(a), D)
        bad.propose = lambda task: PlanProposal(
            steps=tuple(PlanStep(a, 0.0, ()) for a in range(D - 1)))   # covers only D-1 targets
        with self.assertRaises(AssertionError):
            bad.rank(TaskSpec("t", risk_tier=1))

    def test_disposer_sits_between_planner_and_executor(self):
        # every step is individually verified+gated: a paused shell blocks the plan entirely.
        env = CausalLeverEnv(random.Random(0))
        eff = {env.c: 10.0}
        shell = CorrigibilityShell(); shell.op_pause()
        loop = GovernedLoop(gate=GovernedDecisionGate(_self_model()),
                            proposer=CWMPlanner(lambda a: eff.get(a, 0.0), D),
                            verifier=InterventionVerifier(env, random.Random(13)),
                            actuator=LeverActuator(env), shell_view=shell.view(), verify_budget=D)
        self.assertNotEqual(loop.run_task(TaskSpec("t", risk_tier=1)).status, "acted")

    def test_plan_declares_failure_modes_and_effects(self):
        p = CWMPlanner(lambda a: float(a), D)
        plan = p.propose(TaskSpec("t", risk_tier=1))
        self.assertIsInstance(plan, PlanProposal)
        self.assertEqual(len(plan.steps), D)
        self.assertTrue(plan.declared_failure_modes)
        self.assertEqual(set(plan.predicted_do_effects), set(range(D)))


class FalsifierVerdict(unittest.TestCase):
    def test_no_sd4_shadow_proposal_form_is_inert_on_sovereignty(self):
        from experiments.stage5_planner_sovereignty import run
        # P (planner) and A (plain proposer) consuming the same organ signal are identical
        # on the sovereignty metrics -> no choice-set collapse, no rubber-stamp.
        for cell in ("NOISY-10", "NOISY-25"):
            a = [run(s, cell, "A") for s in range(40)]
            p = [run(s, cell, "P") for s in range(40)]
            sa = sum(1 for r in a if r["single"]); sp = sum(1 for r in p if r["single"])
            self.assertLess(sp - sa, 0.05 * 40)     # S1 does not fire


if __name__ == "__main__":
    unittest.main()
