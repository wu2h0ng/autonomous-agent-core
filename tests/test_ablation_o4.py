"""Tests for P1-T2 O4 ablation study and ablation flag behaviour."""
from __future__ import annotations

import inspect
import random
import unittest

from aac.agent import Agent
from aac.prior_organ import BeliefSnapshot, OrganAdvice
from aac.prior_organ_latent import LatentRegimeOrgan
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.structured_regime import StructuredRegimeEnv
import aac.prior_organ_latent as latent_module

from experiments.ablation_o4 import ARMS, ABLATION_NAMES


def _belief(mu: list[float], s: float = 0.1) -> BeliefSnapshot:
    return BeliefSnapshot(
        mu=tuple(mu),
        uncertainty=tuple([0.5] * len(mu)),
        last_surprise=s,
    )


def _make_organ_with_protos(**kwargs) -> LatentRegimeOrgan:
    """Create organ with 2 prototypes, past warmup, with active posterior."""
    organ = LatentRegimeOrgan(
        warmup=0,
        sigma=0.35,
        inject_weight=0.9,
        info_weight=0.5,
        min_posterior_obs=1,
        **kwargs,
    )
    organ._append_prototype({0: 4.0, 1: 0.0, 2: 0.0}, n_actions=3)
    organ._append_prototype({0: 0.0, 1: 4.0, 2: 0.0}, n_actions=3)
    organ._reset_posterior(departed_index=None)
    organ._seen = 10
    organ._mean = 0.1
    organ._mean_sq = 0.01
    return organ


# -- Ablation flag behaviour tests -------------------------------------------


class TestContinuousInjectFlag(unittest.TestCase):
    def test_false_injects_only_once_after_posterior_ready(self) -> None:
        organ = _make_organ_with_protos(continuous_inject=False)
        sit = {"last_action": 0, "last_reward": 4.0}

        a1 = organ.advise(sit, _belief([0.0, 0.0, 0.0]))
        a2 = organ.advise(sit, _belief([0.0, 0.0, 0.0]))
        a3 = organ.advise(sit, _belief([0.0, 0.0, 0.0]))

        # First call should produce non-empty belief_delta
        self.assertTrue(a1.belief_delta and any(v != 0 for v in a1.belief_delta.values()))
        # Subsequent calls should return empty OrganAdvice
        self.assertFalse(a2.belief_delta)
        self.assertFalse(a3.belief_delta)

    def test_true_injects_every_step(self) -> None:
        organ = _make_organ_with_protos(continuous_inject=True)
        sit = {"last_action": 0, "last_reward": 4.0}

        results = []
        for _ in range(3):
            advice = organ.advise(sit, _belief([0.0, 0.0, 0.0]))
            results.append(advice)

        # All calls should produce non-empty belief_delta
        for advice in results:
            self.assertTrue(advice.belief_delta and any(v != 0 for v in advice.belief_delta.values()))

    def test_spike_resets_ablation_injected(self) -> None:
        organ = _make_organ_with_protos(continuous_inject=False, spike_k=0.0)
        sit_normal = {"last_action": 0, "last_reward": 4.0}

        # First injection
        organ.advise(sit_normal, _belief([0.0, 0.0, 0.0]))
        # This should be blocked
        blocked = organ.advise(sit_normal, _belief([0.0, 0.0, 0.0]))
        self.assertFalse(blocked.belief_delta)

        # Trigger a spike (very high surprise)
        spike_belief = _belief([0.0, 0.0, 0.0], s=100.0)
        spike_advice = organ.advise(sit_normal, spike_belief)
        # Spike should produce full belief reset
        self.assertTrue(spike_advice.belief_delta)

        # After spike, next call should inject again (ablation_injected was reset)
        post_spike = organ.advise(sit_normal, _belief([0.0, 0.0, 0.0]))
        self.assertTrue(post_spike.belief_delta and any(v != 0 for v in post_spike.belief_delta.values()))


class TestBayesianUpdateFlag(unittest.TestCase):
    def test_false_keeps_posterior_static(self) -> None:
        organ = _make_organ_with_protos(bayesian_update=False)
        initial_log_post = list(organ._log_post)

        sit = {"last_action": 0, "last_reward": 4.0}
        organ.advise(sit, _belief([0.0, 0.0, 0.0]))
        organ.advise(sit, _belief([0.0, 0.0, 0.0]))

        # Posterior should not have changed
        for a, b in zip(initial_log_post, organ._log_post):
            self.assertAlmostEqual(a, b)

    def test_true_updates_posterior(self) -> None:
        organ = _make_organ_with_protos(bayesian_update=True)
        initial_log_post = list(organ._log_post)

        sit = {"last_action": 0, "last_reward": 4.0}
        organ.advise(sit, _belief([0.0, 0.0, 0.0]))

        # Posterior should have changed (reward=4.0 matches proto[0])
        changed = any(
            abs(a - b) > 1e-9
            for a, b in zip(initial_log_post, organ._log_post)
        )
        self.assertTrue(changed)


class TestDefaultFlagsMatchOriginal(unittest.TestCase):
    def test_deterministic_replay_with_defaults(self) -> None:
        seq = [
            ({"last_action": 0, "last_reward": 4.0}, _belief([0.0, 0.0], 0.1)),
            ({"last_action": 1, "last_reward": 0.0}, _belief([1.0, 0.0], 0.1)),
            ({"last_action": 0, "last_reward": -1.0}, _belief([2.0, 0.0], 8.0)),
            ({"last_action": 1, "last_reward": 4.0}, _belief([0.0, 0.0], 0.1)),
        ]
        a = LatentRegimeOrgan(warmup=0, min_finalise_obs=1, min_posterior_obs=1)
        b = LatentRegimeOrgan(warmup=0, min_finalise_obs=1, min_posterior_obs=1)
        for organ in (a, b):
            organ._seen = 10
            organ._mean = 0.1
            organ._mean_sq = 0.01

        out_a = [a.advise(s, belief) for s, belief in seq]
        out_b = [b.advise(s, belief) for s, belief in seq]
        self.assertEqual(out_a, out_b)

    def test_reset_clears_ablation_injected(self) -> None:
        organ = _make_organ_with_protos(continuous_inject=False)
        sit = {"last_action": 0, "last_reward": 4.0}
        organ.advise(sit, _belief([0.0, 0.0, 0.0]))
        self.assertTrue(organ._ablation_injected)
        organ.reset()
        self.assertFalse(organ._ablation_injected)


# -- C6/C7 guard tests for ablation variants -----------------------------------


class TestC6Guard(unittest.TestCase):
    def test_module_does_not_import_policy_or_shell(self) -> None:
        src = inspect.getsource(latent_module)
        self.assertNotIn("import aac.policy", src)
        self.assertNotIn("import aac.shell", src)

    def test_advice_fields_unchanged_for_all_variants(self) -> None:
        expected_fields = {
            "belief_delta", "uncertainty", "counterfactual_hint", "uncertainty_delta"
        }
        for name, (_, params) in ARMS.items():
            organ = LatentRegimeOrgan(**params)
            advice = organ.advise({}, _belief([0.0, 0.0]))
            self.assertEqual(
                set(advice.__dataclass_fields__),
                expected_fields,
                f"C6 violation in arm {name}",
            )


class TestC7Guard(unittest.TestCase):
    def _run_ablation_variant(self, variant_params: dict) -> None:
        """Verify variant respects op_pause."""
        organ = LatentRegimeOrgan(**variant_params)
        shell = CorrigibilityShell()
        agent = Agent(
            n_actions=8,
            shell=shell,
            rng=random.Random(0),
            viability=ViabilityCore(
                budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0
            ),
            prior_organ=organ,
        )
        env = StructuredRegimeEnv(rng=random.Random(1))
        for _ in range(20):
            agent.step(env)
        shell.op_pause()
        self.assertIsNone(agent.step(env))

    def test_all_ablation_variants_pausable(self) -> None:
        for name, (_, params) in ARMS.items():
            with self.subTest(arm=name):
                self._run_ablation_variant(params)


# -- Ablation experiment logic tests -------------------------------------------


class TestAblationExperiment(unittest.TestCase):
    def test_arms_count(self) -> None:
        self.assertEqual(len(ARMS), 5)

    def test_ablation_names(self) -> None:
        expected = [
            "O4-full", "O4-no-info", "O4-no-transition",
            "O4-oneshot", "O4-no-posterior",
        ]
        self.assertEqual(ABLATION_NAMES, expected)

    def test_arms_use_correct_params(self) -> None:
        # O4-full: no overrides
        _, full_params = ARMS["O4-full"]
        self.assertEqual(full_params["info_weight"], 0.3)
        self.assertEqual(full_params["departed_penalty"], 1.0)
        self.assertTrue(full_params.get("continuous_inject", True))
        self.assertTrue(full_params.get("bayesian_update", True))

        # O4-no-info: info_weight=0
        _, params = ARMS["O4-no-info"]
        self.assertEqual(params["info_weight"], 0.0)

        # O4-no-transition: departed_penalty=0
        _, params = ARMS["O4-no-transition"]
        self.assertEqual(params["departed_penalty"], 0.0)

        # O4-oneshot: continuous_inject=False
        _, params = ARMS["O4-oneshot"]
        self.assertFalse(params["continuous_inject"])

        # O4-no-posterior: bayesian_update=False
        _, params = ARMS["O4-no-posterior"]
        self.assertFalse(params["bayesian_update"])


if __name__ == "__main__":
    unittest.main()
