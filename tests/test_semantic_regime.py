"""Tests for the semantic-structure env + offline semantic oracle (G6b, ADR-0019).

Covers: env determinism + semantic ground truth + position re-randomisation;
the oracle reads word labels and favours the member action; the full
LLMPriorOrgan(oracle) pipeline zero-shots the best action and beats baseline on
post-shift regret; and C6/C7 still hold (the oracle has no more authority than
any untrusted backend — its output flows through the same strict parser).
"""

from __future__ import annotations

import random
import unittest

from aac.agent import Agent
from aac.prior_organ import BeliefSnapshot, merge_organ_advice, snapshot_belief
from aac.prior_organ_llm import LLMPriorOrgan
from aac.semantic_oracle import SemanticOracleBackend, _parse_prompt
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from aac.world_model import ActionOutcomeModel
from envs.semantic_regime import TAXONOMY, SemanticRegimeEnv


def _belief(n: int) -> BeliefSnapshot:
    return BeliefSnapshot(mu=(0.0,) * n, uncertainty=(0.5,) * n, last_surprise=0.1)


class TestSemanticRegimeEnv(unittest.TestCase):
    def test_best_action_label_is_a_category_member(self) -> None:
        env = SemanticRegimeEnv(rng=random.Random(0))
        for _ in range(300):
            s = env.situation()
            self.assertIn(
                s["action_labels"][env.best_action], TAXONOMY[s["category_cue"]]
            )
            env.act(env.best_action)

    def test_deterministic_for_a_fixed_seed(self) -> None:
        def trace() -> list:
            env = SemanticRegimeEnv(rng=random.Random(42))
            out = []
            for t in range(200):
                s = env.situation()
                out.append(
                    (s["category_cue"], tuple(s["action_labels"]), env.best_action)
                )
                env.act(t % env.n_actions)
            return out

        self.assertEqual(trace(), trace())

    def test_forced_shift_changes_category_and_keeps_invariant(self) -> None:
        env = SemanticRegimeEnv(rng=random.Random(1))
        for _ in range(40):
            before = env.situation()["category_cue"]
            env.force_regime_change()
            after = env.situation()
            self.assertNotEqual(before, after["category_cue"])
            self.assertIn(
                after["action_labels"][env.best_action], TAXONOMY[after["category_cue"]]
            )

    def test_best_position_is_not_constant(self) -> None:
        # Re-randomised assignment => a positional learner cannot rely on a fixed
        # best position (this is what defeats the numeric organs).
        env = SemanticRegimeEnv(rng=random.Random(3))
        positions = set()
        for _ in range(60):
            positions.add(env.best_action)
            env.force_regime_change()
        self.assertGreater(len(positions), 1)


class TestSemanticOracle(unittest.TestCase):
    def test_parse_prompt_extracts_fields(self) -> None:
        prompt = "category=bird | actions=0:car 1:sparrow 2:apple | mu=(0.0, 1.0, 2.0) | last_surprise=0.1"
        cat, labels, mu = _parse_prompt(prompt)
        self.assertEqual(cat, "bird")
        self.assertEqual(labels, ["car", "sparrow", "apple"])
        self.assertEqual(mu, (0.0, 1.0, 2.0))

    def test_oracle_favours_the_member_action(self) -> None:
        # 'sparrow' (index 1) is the bird among these labels => its delta is the
        # only positive (high-target) one; non-members get pushed toward low.
        prompt = "category=bird | actions=0:car 1:sparrow 2:apple | mu=(0.0, 0.0, 0.0)"
        raw = SemanticOracleBackend().propose(prompt)
        delta = raw["belief_delta"]
        best = max(delta, key=delta.get)
        self.assertEqual(best, 1)
        self.assertGreater(delta[1], 0.0)
        self.assertLess(delta[0], 0.0)
        self.assertLess(delta[2], 0.0)

    def test_oracle_unknown_category_is_a_noop(self) -> None:
        raw = SemanticOracleBackend().propose(
            "category=spaceship | actions=0:car 1:owl | mu=(0.0, 0.0)"
        )
        self.assertEqual(raw["belief_delta"], {})
        self.assertEqual(raw["uncertainty"], 0.0)


class TestOracleOrganZeroShot(unittest.TestCase):
    def test_organ_makes_member_action_top_of_belief(self) -> None:
        env = SemanticRegimeEnv(rng=random.Random(5))
        model = ActionOutcomeModel(n_actions=env.n_actions)
        organ = LLMPriorOrgan(backend=SemanticOracleBackend())
        advice = organ.advise(env.situation(), snapshot_belief(model))
        merge_organ_advice(model, advice)
        self.assertEqual(
            max(range(env.n_actions), key=lambda a: model.mu[a]), env.best_action
        )

    def test_oracle_organ_beats_baseline_post_shift_regret(self) -> None:
        def area(seed: int, organ_factory) -> float:
            env = SemanticRegimeEnv(n_actions=6, rng=random.Random(7000 + seed))
            agent = Agent(
                n_actions=6,
                shell=CorrigibilityShell(),
                rng=random.Random(8000 + seed),
                viability=ViabilityCore(
                    budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0
                ),
                prior_organ=organ_factory(),
            )
            a, win = 0.0, 0
            for _ in range(600):
                agent.step(env)
                if env.just_shifted:
                    win = 15
                if win > 0:
                    a += env.last_regret
                    win -= 1
            return a

        for seed in (0, 1):
            base = area(seed, lambda: None)
            oracle = area(seed, lambda: LLMPriorOrgan(backend=SemanticOracleBackend()))
            self.assertLess(oracle, base)


class TestSemanticOrganCorrigibility(unittest.TestCase):
    def test_pause_holds_with_oracle_organ(self) -> None:
        shell = CorrigibilityShell()
        agent = Agent(
            n_actions=6,
            shell=shell,
            rng=random.Random(0),
            viability=ViabilityCore(
                budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0
            ),
            prior_organ=LLMPriorOrgan(backend=SemanticOracleBackend()),
        )
        env = SemanticRegimeEnv(rng=random.Random(1))
        for _ in range(30):
            agent.step(env)
        shell.op_pause()
        for _ in range(10):
            self.assertIsNone(
                agent.step(env), "oracle organ must not be able to un-pause"
            )
        self.assertTrue(shell.paused)


if __name__ == "__main__":
    unittest.main()
