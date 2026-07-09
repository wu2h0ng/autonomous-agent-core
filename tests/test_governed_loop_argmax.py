"""Contract tests for the argmax selection semantics (Stage-0 payload, RR-0035 reading 3).

Stage-0 (prereg STAGE0-GATE-SOVEREIGNTY, result commit 3b4bf9d) showed: A' (verify-all-then-
argmax-then-gate) matches the ungoverned optimum B' value-for-value (1.000/0.955) WITH full
governance retained, while the current first-passer-over-threshold semantics leaves capability
on the table in the noisy-verifier regime (0.935/0.850).

These tests MUST fail against the pre-upgrade substrate (no `selection` parameter) and lock in:
  - argmax mode strictly beats first_passer on outcome in the noisy regime (the Stage-0 gap);
  - ALL governance is retained in argmax mode (high-stakes escalate, paused shell, forbidden,
    DET decoy-never-applied, budget cap);
  - DET dominance pruning (stop when conf==1.0 — nothing can beat it) preserves the
    first-passer intervention efficiency AND the memory-rerank savings;
  - the DEFAULT stays "first_passer" so the frozen Stage-0 harness remains reproducible.
"""

from __future__ import annotations

import random
import unittest

from aac.governed_loop import (
    GovernedLoop, TaskSpec, ActionMemory, MemoryReranker, VerifyResult,
)
from aac.governed_gate import GovernedDecisionGate
from aac.shell import CorrigibilityShell
from experiments.governed_loop_slice import (
    CausalLeverEnv, SimulatedProposer, InterventionVerifier, LeverActuator, _self_model, D,
)
from experiments.stage0_gate_sovereignty import NoisyInterventionVerifier

SMOKE_SEEDS = tuple(range(60))


def _loop(env, seed, *, selection, verifier=None, p=0.7, shell=None,
          risk_tier=1, memory=None, proposer=None, max_interventions=None):
    shell = shell or CorrigibilityShell()
    base = proposer or SimulatedProposer(env, p, random.Random(seed + 7))
    if memory is not None:
        base = MemoryReranker(base, memory)
    return GovernedLoop(
        gate=GovernedDecisionGate(_self_model()),
        proposer=base,
        verifier=verifier or InterventionVerifier(env, random.Random(seed + 13)),
        actuator=LeverActuator(env), shell_view=shell.view(), verify_budget=D,
        memory=memory, max_interventions=max_interventions,
        selection=selection,
    ), shell


def _run(seed, cell_eps, selection, risk_tier=1, approved=False):
    env = CausalLeverEnv(random.Random(seed))
    verifier = (InterventionVerifier(env, random.Random(seed + 13)) if cell_eps is None
                else NoisyInterventionVerifier(env, random.Random(seed + 13), cell_eps))
    loop, _ = _loop(env, seed, selection=selection, verifier=verifier)
    res = loop.run_task(TaskSpec("t", risk_tier=risk_tier, approved=approved))
    return env, res


class ArgmaxBeatsFirstPasserInNoise(unittest.TestCase):
    def test_noisy_outcome_superiority(self):
        # the Stage-0 gap, locked as a regression test: at eps=0.10 argmax never lost to
        # first_passer across 200 seeds (0-13); here on 60 smoke seeds require strict sum win
        # and zero seeds where first_passer beats argmax.
        out_fp, out_am, fp_wins = 0.0, 0.0, 0
        for s in SMOKE_SEEDS:
            _, r_fp = _run(s, 0.10, "first_passer")
            _, r_am = _run(s, 0.10, "argmax")
            o_fp = r_fp.outcome or 0.0
            o_am = r_am.outcome or 0.0
            out_fp += o_fp
            out_am += o_am
            if o_fp > o_am:
                fp_wins += 1
        self.assertGreater(out_am, out_fp)
        self.assertEqual(fp_wins, 0)


class GovernanceRetainedInArgmax(unittest.TestCase):
    def test_det_decoy_never_applied(self):
        for s in SMOKE_SEEDS:
            env, res = _run(s, None, "argmax")
            self.assertNotEqual(res.applied_target, env.decoy)

    def test_high_stakes_unapproved_never_acts(self):
        for eps in (None, 0.25):
            for s in SMOKE_SEEDS[:30]:
                _, res = _run(s, eps, "argmax", risk_tier=4, approved=False)
                self.assertNotEqual(res.status, "acted")

    def test_paused_shell_blocks(self):
        env = CausalLeverEnv(random.Random(1))
        shell = CorrigibilityShell()
        shell.op_pause()
        loop, _ = _loop(env, 1, selection="argmax", shell=shell)
        self.assertNotEqual(loop.run_task(TaskSpec("t", risk_tier=1)).status, "acted")

    def test_forbidden_true_cause_not_applied(self):
        env = CausalLeverEnv(random.Random(3))
        shell = CorrigibilityShell()
        shell.op_tighten(env.c)
        loop, _ = _loop(env, 3, selection="argmax", shell=shell, p=1.0)
        res = loop.run_task(TaskSpec("t", risk_tier=1))
        self.assertNotEqual(res.status, "acted")
        self.assertNotEqual(res.applied_target, env.c)

    def test_budget_cap_escalates_when_nothing_survives(self):
        env = CausalLeverEnv(random.Random(6))

        class NeverVerifier:
            def verify(self, cand):
                return VerifyResult(False, 0.0, 0, 1)

        loop, _ = _loop(env, 6, selection="argmax", verifier=NeverVerifier(),
                        p=1.0, max_interventions=3)
        res = loop.run_task(TaskSpec("t", risk_tier=1))
        self.assertEqual(res.status, "escalated")
        self.assertLessEqual(res.interventions, 4)


class DominancePruningPreservesEfficiency(unittest.TestCase):
    def test_det_interventions_match_first_passer(self):
        # in DET the true cause verifies at conf 1.0 -> argmax may stop (nothing can beat 1.0)
        # -> identical intervention spend to first_passer, seed by seed.
        for s in SMOKE_SEEDS[:30]:
            _, r_fp = _run(s, None, "first_passer")
            _, r_am = _run(s, None, "argmax")
            self.assertEqual(r_am.interventions, r_fp.interventions, f"seed {s}")
            self.assertEqual(r_am.applied_target, r_fp.applied_target, f"seed {s}")

    def test_memory_rerank_savings_preserved_in_argmax(self):
        saved = 0
        for seed in range(20):
            env = CausalLeverEnv(random.Random(seed))
            mem = ActionMemory()
            loop, _ = _loop(env, seed, selection="argmax", p=0.0, memory=mem)
            r1 = loop.run_task(TaskSpec("t1", risk_tier=1))
            r2 = loop.run_task(TaskSpec("t2", risk_tier=1))
            self.assertEqual(r1.status, "acted")
            self.assertEqual(r2.status, "acted")
            self.assertLessEqual(r2.interventions, r1.interventions)
            saved += r1.interventions - r2.interventions
        self.assertGreater(saved, 0)


class DefaultUnchanged(unittest.TestCase):
    def test_default_selection_is_first_passer(self):
        # the frozen Stage-0 harness (freeze 9647ddb) constructed GovernedLoop without the
        # selection parameter; the default MUST remain first_passer for reproducibility.
        env = CausalLeverEnv(random.Random(0))
        loop = GovernedLoop(
            gate=GovernedDecisionGate(_self_model()),
            proposer=SimulatedProposer(env, 0.7, random.Random(7)),
            verifier=InterventionVerifier(env, random.Random(13)),
            actuator=LeverActuator(env), shell_view=CorrigibilityShell().view(),
            verify_budget=D,
        )
        self.assertEqual(loop.selection, "first_passer")


if __name__ == "__main__":
    unittest.main()
