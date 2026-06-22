"""ADR-0035/G12 guards for the P7 ecological environment axis."""

from __future__ import annotations

import inspect
import random
import unittest

from aac.agent import Agent
from aac.prior_organ_o1 import ResetScaffoldOrgan
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore


class TestEcologicalRegimeEnv(unittest.TestCase):
    def test_thin_cell_has_no_reward_topology(self) -> None:
        from envs.ecological_regime import EcologicalRegimeEnv

        env = EcologicalRegimeEnv(
            n_actions=8,
            n_regimes=5,
            rng=random.Random(1),
            structured=False,
            reversible=True,
            noise=0.0,
        )
        rewards = env._regime
        best = env.best_action
        non_best_values = {rewards[a] for a in range(env.n_actions) if a != best}
        self.assertEqual(rewards[best], 4.0)
        self.assertEqual(non_best_values, {-1.0})

    def test_ecological_cell_has_transferable_neighbor_topology(self) -> None:
        from envs.ecological_regime import EcologicalRegimeEnv

        env = EcologicalRegimeEnv(
            n_actions=8,
            n_regimes=5,
            rng=random.Random(1),
            structured=True,
            reversible=True,
            noise=0.0,
        )
        rewards = env._regime
        best = env.best_action
        left = (best - 1) % env.n_actions
        far = (best + 4) % env.n_actions
        self.assertEqual(rewards[best], 4.0)
        self.assertGreater(rewards[left], rewards[far])

    def test_ecological_best_action_moves_by_neighbor(self) -> None:
        from envs.ecological_regime import EcologicalRegimeEnv

        env = EcologicalRegimeEnv(
            n_actions=8,
            n_regimes=5,
            rng=random.Random(2),
            structured=True,
            reversible=True,
            noise=0.0,
        )
        first = env.best_action
        env.force_regime_change()
        second = env.best_action
        self.assertIn((second - first) % env.n_actions, {1, env.n_actions - 1})

    def test_reversible_cell_rolls_back_external_damage_at_shift(self) -> None:
        from envs.ecological_regime import EcologicalRegimeEnv

        env = EcologicalRegimeEnv(
            n_actions=4,
            n_regimes=2,
            period=2,
            rng=random.Random(3),
            structured=False,
            reversible=True,
            noise=0.0,
        )
        miss = next(a for a in range(env.n_actions) if a != env.best_action)
        env.act(miss)
        self.assertGreater(env.current_damage, 0.0)
        env.act(miss)
        self.assertTrue(env.just_shifted)
        self.assertEqual(env.current_damage, 0.0)
        self.assertEqual(env.irreversible_damage, 0.0)

    def test_irreversible_cell_accumulates_external_damage(self) -> None:
        from envs.ecological_regime import EcologicalRegimeEnv

        env = EcologicalRegimeEnv(
            n_actions=4,
            n_regimes=2,
            period=2,
            rng=random.Random(3),
            structured=False,
            reversible=False,
            noise=0.0,
        )
        miss = next(a for a in range(env.n_actions) if a != env.best_action)
        env.act(miss)
        before = env.irreversible_damage
        env.act(miss)
        self.assertTrue(env.just_shifted)
        self.assertGreater(env.irreversible_damage, before)
        self.assertGreater(env.current_damage, 0.0)
        self.assertFalse(hasattr(env, "rollback_external_world"))

    def test_o1_internal_reset_does_not_modify_external_env_state(self) -> None:
        from envs.ecological_regime import EcologicalRegimeEnv

        env = EcologicalRegimeEnv(
            n_actions=8,
            n_regimes=5,
            rng=random.Random(4),
            structured=True,
            reversible=False,
            noise=0.0,
        )
        shell = CorrigibilityShell()
        agent = Agent(
            n_actions=8,
            shell=shell,
            rng=random.Random(5),
            viability=ViabilityCore(
                budget=1e9,
                metabolic_cost=0.0,
                capacity=1e9,
                safe_budget=1.0,
            ),
            prior_organ=ResetScaffoldOrgan(),
        )
        for _ in range(50):
            agent.step(env)
        state = (env.t, env.regime_index, env.current_damage, env.irreversible_damage)
        agent.prior_organ.reset()
        self.assertEqual(
            (env.t, env.regime_index, env.current_damage, env.irreversible_damage),
            state,
        )


class TestG12Harness(unittest.TestCase):
    def test_cell_grid_is_preregistered_2x2(self) -> None:
        from experiments import ecological_g12 as exp

        self.assertEqual(
            tuple(cell.name for cell in exp.g12_cells()),
            ("C00", "C01", "C10", "C11"),
        )
        self.assertEqual(
            [(cell.structured, cell.reversible) for cell in exp.g12_cells()],
            [(False, True), (False, False), (True, True), (True, False)],
        )

    def test_run_seed_uses_agent_step(self) -> None:
        from experiments import ecological_g12 as exp

        source = inspect.getsource(exp.run_seed)
        self.assertIn("agent.step(env)", source)
        self.assertNotIn(".policy.select", source)

    def test_rstar_params_loaded_from_adr0034_freeze(self) -> None:
        from experiments import ecological_g12 as exp

        params = exp.load_rstar_params()
        self.assertEqual(params.base_temperature, 0.03)
        self.assertEqual(params.inertia, 0.25)
        self.assertEqual(params.surprise_gain, 1.0)

    def test_cell_win_requires_irreversible_damage_reduction(self) -> None:
        from experiments import ecological_g12 as exp

        stats = exp.cell_stats(
            p0_loss=[1.0] * 30,
            cheap_loss=[2.0] * 30,
            p0_damage=[10.0] * 30,
            cheap_damage=[10.0] * 30,
            irreversible=True,
        )
        self.assertFalse(stats["win"])
        self.assertGreater(stats["adv"], 0.2)


if __name__ == "__main__":
    unittest.main()
