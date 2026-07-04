"""Contract tests for the GovernedLoop vertical slice (REF-ARCH-03 §4).

Load-bearing invariants — these MUST fail if governance is bypassed (Hard Boundary #13/16):
  - the loop never applies a confounded decoy when the verifier is real;
  - replacing the real verifier with a bypass DOES apply the decoy (verification is load-bearing);
  - high-stakes never auto-applies (escalates for approval);
  - a paused C7 shell blocks action;
  - when nothing verifies, the loop escalates (never silently acts).
"""

from __future__ import annotations

import random
import unittest

from aac.governed_loop import (
    GovernedLoop, Candidate, VerifyResult, TaskSpec, ActionMemory, MemoryReranker,
    BoundaryAwareReranker,
)
from aac.governed_gate import GovernedDecisionGate
from aac.self_model import AgentSelfModel
from aac.shell import CorrigibilityShell
from experiments.governed_loop_slice import (
    CausalLeverEnv, SimulatedProposer, InterventionVerifier, BypassVerifier,
    LeverActuator, _self_model, run_one, D, SEEDS,
)


class DecoyNeverApplied(unittest.TestCase):
    def test_real_verifier_never_applies_decoy(self):
        # even with an unreliable proposer (ranks the decoy first), the CWM probe catches it
        for p in (0.7, 0.4, 0.2):
            rows = [run_one(s, p, risk_tier=1, approved=False) for s in SEEDS]
            applied_decoy = sum(1 for r in rows if r["applied_decoy"])
            self.assertEqual(applied_decoy, 0, f"decoy applied at p={p}")

    def test_acts_only_yield_reward(self):
        # whenever the loop ACTS, it applied the true cause -> outcome 1.0
        rows = [run_one(s, 0.7, risk_tier=1, approved=False) for s in SEEDS]
        for r in rows:
            if r["status"] == "acted":
                self.assertTrue(r["applied_true_cause"])
                self.assertEqual(r["outcome"], 1.0)


class VerificationIsLoadBearing(unittest.TestCase):
    def test_bypass_verifier_applies_decoy(self):
        # remove real verification -> the decoy DOES get applied -> proves verification is load-bearing
        real = sum(1 for s in SEEDS if run_one(s, 0.2, risk_tier=1, approved=False, bypass=False)["applied_decoy"])
        byp = sum(1 for s in SEEDS if run_one(s, 0.2, risk_tier=1, approved=False, bypass=True)["applied_decoy"])
        self.assertEqual(real, 0)
        self.assertGreater(byp, 0, "bypass should let the decoy through; if not, the test is hollow")


class HighStakesGovernance(unittest.TestCase):
    def test_high_stakes_unapproved_escalates(self):
        rows = [run_one(s, 1.0, risk_tier=4, approved=False) for s in SEEDS]
        self.assertEqual(sum(1 for r in rows if r["status"] == "acted"), 0)
        self.assertTrue(all(r["status"] == "escalated" for r in rows))

    def test_high_stakes_approved_acts_on_true_cause(self):
        rows = [run_one(s, 1.0, risk_tier=4, approved=True) for s in SEEDS]
        acted = [r for r in rows if r["status"] == "acted"]
        self.assertGreater(len(acted), 0)
        self.assertTrue(all(r["applied_true_cause"] for r in acted))


class ShellAndEscalation(unittest.TestCase):
    def _loop(self, env, shell, p=1.0, seed=0):
        return GovernedLoop(
            gate=GovernedDecisionGate(_self_model()),
            proposer=SimulatedProposer(env, p, random.Random(seed + 7)),
            verifier=InterventionVerifier(env, random.Random(seed + 13)),
            actuator=LeverActuator(env),
            shell_view=shell.view(), verify_budget=D,
        )

    def test_paused_shell_blocks_action(self):
        env = CausalLeverEnv(random.Random(0))
        shell = CorrigibilityShell(); shell.op_pause()
        res = self._loop(env, shell).run_task(TaskSpec("t", risk_tier=1))
        self.assertNotEqual(res.status, "acted")

    def test_audit_records_steps_and_chain_intact(self):
        env = CausalLeverEnv(random.Random(1))
        shell = CorrigibilityShell()
        self._loop(env, shell, seed=1).run_task(TaskSpec("t", risk_tier=1))
        entries = shell.audit.entries()
        events = [e.payload.get("event") for e in entries]
        self.assertIn("task_start", events)        # the loop recorded its steps
        self.assertTrue(any(ev in ("act", "decide", "escalate") for ev in events))
        self.assertTrue(shell.audit.verify())      # hash chain intact (tamper-evident)

    def test_forbidden_action_is_blocked_by_shell(self):
        # C7 op_tighten forbids the TRUE-CAUSE lever index -> the loop must NOT apply it (closes the
        # forbidden-path gap the adversarial review found; exercises the action_index fix)
        env = CausalLeverEnv(random.Random(3))
        shell = CorrigibilityShell()
        shell.op_tighten(env.c)  # forbid the only effective lever
        res = self._loop(env, shell, seed=3).run_task(TaskSpec("t", risk_tier=1))
        self.assertNotEqual(res.status, "acted")
        self.assertNotEqual(res.applied_target, env.c)

    def test_loop_acts_on_whatever_the_verifier_approves(self):
        # Isolates the LOOP from verifier correctness: a verifier that approves ONLY the decoy makes
        # the loop apply the decoy -> proves the loop faithfully gates on the verifier (the "never
        # applies decoy" property is contingent on a correct verifier, not magic).
        env = CausalLeverEnv(random.Random(4))

        class ApprovesOnlyDecoy:
            def verify(self, cand):
                eff = cand.target == env.decoy
                return VerifyResult(eff, 0.99 if eff else 0.0, 3 if eff else 0, 1)

        loop = GovernedLoop(
            gate=GovernedDecisionGate(_self_model()),
            proposer=SimulatedProposer(env, 1.0, random.Random(4 + 7)),
            verifier=ApprovesOnlyDecoy(), actuator=LeverActuator(env),
            shell_view=CorrigibilityShell().view(), verify_budget=D,
        )
        res = loop.run_task(TaskSpec("t", risk_tier=1))
        self.assertEqual(res.status, "acted")
        self.assertEqual(res.applied_target, env.decoy)  # loop follows the (here-wrong) verifier

    def test_feedback_record_fires_on_act(self):
        # the minimal feedback hook records (target, outcome) on act (not yet belief-update)
        env = CausalLeverEnv(random.Random(5))
        recorded = []
        loop = GovernedLoop(
            gate=GovernedDecisionGate(_self_model()),
            proposer=SimulatedProposer(env, 1.0, random.Random(5 + 7)),
            verifier=InterventionVerifier(env, random.Random(5 + 13)),
            actuator=LeverActuator(env), shell_view=CorrigibilityShell().view(),
            verify_budget=D, on_outcome=lambda target, outcome: recorded.append((target, outcome)),
        )
        res = loop.run_task(TaskSpec("t", risk_tier=1))
        self.assertEqual(res.status, "acted")
        self.assertEqual(recorded, [(env.c, 1.0)])

    def test_no_effective_action_escalates(self):
        # a verifier that never confirms anything -> loop must escalate, never act
        env = CausalLeverEnv(random.Random(2))

        class NeverVerifier:
            def verify(self, cand):
                return VerifyResult(False, 0.0, 0, 1)

        loop = GovernedLoop(
            gate=GovernedDecisionGate(_self_model()),
            proposer=SimulatedProposer(env, 1.0, random.Random(9)),
            verifier=NeverVerifier(), actuator=LeverActuator(env),
            shell_view=CorrigibilityShell().view(), verify_budget=D,
        )
        res = loop.run_task(TaskSpec("t", risk_tier=1))
        self.assertEqual(res.status, "escalated")


class BudgetCapAndMemory(unittest.TestCase):
    def test_hard_budget_cap_escalates_early(self):
        # a verifier that never confirms + a low intervention cap -> escalate without exhausting all
        env = CausalLeverEnv(random.Random(6))

        class NeverVerifier:
            def verify(self, cand):
                return VerifyResult(False, 0.0, 0, 1)  # 1 intervention each, never effective

        loop = GovernedLoop(
            gate=GovernedDecisionGate(_self_model()),
            proposer=SimulatedProposer(env, 1.0, random.Random(13)),
            verifier=NeverVerifier(), actuator=LeverActuator(env),
            shell_view=CorrigibilityShell().view(), verify_budget=D, max_interventions=3,
        )
        res = loop.run_task(TaskSpec("t", risk_tier=1))
        self.assertEqual(res.status, "escalated")
        self.assertLessEqual(res.interventions, 4)   # capped (3) + at most the one that crossed

    def test_memory_rerank_reduces_interventions_on_repeat(self):
        # task 1 spends interventions finding the true cause; memory remembers it; task 2 ranks it
        # first -> fewer interventions. Real belief-update: the outcome changes future behavior.
        saved = 0
        for seed in range(20):
            env = CausalLeverEnv(random.Random(seed))
            mem = ActionMemory()
            base = SimulatedProposer(env, 0.0, random.Random(seed + 7))  # true cause NOT boosted -> buried
            loop = GovernedLoop(
                gate=GovernedDecisionGate(_self_model()),
                proposer=MemoryReranker(base, mem),
                verifier=InterventionVerifier(env, random.Random(seed + 13)),
                actuator=LeverActuator(env), shell_view=CorrigibilityShell().view(),
                verify_budget=D, memory=mem,
            )
            r1 = loop.run_task(TaskSpec("t1", risk_tier=1))
            r2 = loop.run_task(TaskSpec("t2", risk_tier=1))
            self.assertEqual(r1.status, "acted")
            self.assertEqual(r2.status, "acted")
            self.assertLessEqual(r2.interventions, r1.interventions)
            saved += r1.interventions - r2.interventions
        self.assertGreater(saved, 0)   # across seeds, memory strictly reduced total interventions


class BoundaryAwareRerankerTests(unittest.TestCase):
    def _make_proposer(self, env, seed=0):
        return SimulatedProposer(env, 0.0, random.Random(seed + 7))

    def test_forbidden_candidates_not_promoted(self):
        env = CausalLeverEnv(random.Random(10))
        mem = ActionMemory()
        mem.remember(f"apply_lever:{env.c}")  # true cause known
        reranker = BoundaryAwareReranker(base=self._make_proposer(env, 10), memory=mem)
        reranker.update_boundaries(frozenset([env.c]))  # NOW forbidden

        ranked = reranker.rank(TaskSpec("t", risk_tier=1))
        first_target = ranked[0].target
        self.assertNotEqual(first_target, env.c,
                            "forbidden-but-known-effective must NOT be promoted to front")

    def test_non_forbidden_known_still_promoted(self):
        env = CausalLeverEnv(random.Random(11))
        mem = ActionMemory()
        mem.remember(f"apply_lever:{env.c}")
        reranker = BoundaryAwareReranker(base=self._make_proposer(env, 11), memory=mem)
        reranker.update_boundaries(frozenset())  # nothing forbidden

        ranked = reranker.rank(TaskSpec("t", risk_tier=1))
        self.assertEqual(ranked[0].target, env.c,
                         "non-forbidden known-effective should still be first")

    def test_dynamic_boundary_change(self):
        env = CausalLeverEnv(random.Random(12))
        mem = ActionMemory()
        mem.remember(f"apply_lever:{env.c}")
        reranker = BoundaryAwareReranker(base=self._make_proposer(env, 12), memory=mem)

        reranker.update_boundaries(frozenset())
        ranked1 = reranker.rank(TaskSpec("t", risk_tier=1))
        self.assertEqual(ranked1[0].target, env.c)

        reranker.update_boundaries(frozenset([env.c]))
        ranked2 = reranker.rank(TaskSpec("t", risk_tier=1))
        self.assertNotEqual(ranked2[0].target, env.c)

    def test_governed_loop_with_boundary_aware_reranker_blocks_forbidden(self):
        env = CausalLeverEnv(random.Random(13))
        mem = ActionMemory()
        mem.remember(f"apply_lever:{env.c}")
        shell = CorrigibilityShell()
        shell.op_tighten(env.c)

        reranker = BoundaryAwareReranker(
            base=self._make_proposer(env, 13), memory=mem)
        reranker.update_boundaries(frozenset([env.c]))

        loop = GovernedLoop(
            gate=GovernedDecisionGate(_self_model()),
            proposer=reranker,
            verifier=InterventionVerifier(env, random.Random(13 + 13)),
            actuator=LeverActuator(env),
            shell_view=shell.view(), verify_budget=D, memory=mem,
        )
        res = loop.run_task(TaskSpec("t", risk_tier=1))
        self.assertNotEqual(res.applied_target, env.c,
                            "boundary-aware reranker should prevent forbidden from being first tried")

    def test_adr0051_auto_boundary_notification(self):
        """ADR-0051: GovernedLoop auto-calls update_boundaries before ranking."""
        env = CausalLeverEnv(random.Random(14))
        mem = ActionMemory()
        mem.remember(f"apply_lever:{env.c}")
        shell = CorrigibilityShell()
        shell.op_tighten(env.c)

        reranker = BoundaryAwareReranker(
            base=self._make_proposer(env, 14), memory=mem)
        # Do NOT manually call update_boundaries — GovernedLoop should do it

        loop = GovernedLoop(
            gate=GovernedDecisionGate(_self_model()),
            proposer=reranker,
            verifier=InterventionVerifier(env, random.Random(14 + 13)),
            actuator=LeverActuator(env),
            shell_view=shell.view(), verify_budget=D, memory=mem,
        )
        res = loop.run_task(TaskSpec("t", risk_tier=1))
        # If auto-notification works, forbidden lever should NOT be first tried
        self.assertNotEqual(res.applied_target, env.c,
                            "ADR-0051: loop must auto-notify proposer of forbidden set")


if __name__ == "__main__":
    unittest.main()
