"""ADR-0036/G13 guards for the bounded consequence-prior gate."""

from __future__ import annotations

import ast
import inspect
import random
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path

import aac.consequence_prior as cp_module
from aac.agent import Agent
from aac.consequence_prior import (
    BoundedConsequencePriorOrgan,
    ConsequencePriorRecord,
)
from aac.prior_organ import BeliefSnapshot, OrganAdvice
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore


class _ZeroEnv:
    def __init__(self) -> None:
        self.actions: list[int] = []

    def situation(self) -> dict:
        return {
            "public_consequence_features": [
                {
                    "action_id": 0,
                    "scar_delta": 1.0,
                    "resource_delta": 0.0,
                    "conflict_delta": 0.0,
                    "uncertainty": 1.0,
                },
                {
                    "action_id": 1,
                    "scar_delta": 0.0,
                    "resource_delta": 0.0,
                    "conflict_delta": 0.0,
                    "uncertainty": 1.0,
                },
            ]
        }

    def act(self, action: int) -> float:
        self.actions.append(action)
        return 0.0


class TestConsequencePriorOrgan(unittest.TestCase):
    def test_record_fields_are_the_adr0036_allowed_surface(self) -> None:
        self.assertEqual(
            {field.name for field in fields(ConsequencePriorRecord)},
            {
                "action_id",
                "predicted_scar_delta",
                "predicted_resource_delta",
                "predicted_conflict_delta",
                "uncertainty",
            },
        )
        forbidden = {"action", "selected_action", "policy", "shell", "pause"}
        self.assertEqual(
            {field.name for field in fields(ConsequencePriorRecord)} & forbidden, set()
        )

    def test_module_imports_no_policy_shell_or_audit(self) -> None:
        tree = ast.parse(inspect.getsource(cp_module))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imports.add(node.module)
        self.assertEqual(
            imports & {"aac.policy", "aac.shell", "aac.audit", "policy", "shell"}, set()
        )

    def test_prediction_ignores_hidden_evaluator_labels(self) -> None:
        organ = BoundedConsequencePriorOrgan()
        belief = BeliefSnapshot(
            mu=(0.0, 0.0), uncertainty=(1.0, 1.0), last_surprise=0.0
        )
        public = [
            {
                "action_id": 0,
                "scar_delta": 1.0,
                "resource_delta": 0.2,
                "conflict_delta": 0.0,
                "uncertainty": 0.5,
            },
            {
                "action_id": 1,
                "scar_delta": 0.0,
                "resource_delta": 0.0,
                "conflict_delta": 0.0,
                "uncertainty": 0.5,
            },
        ]
        a = organ.predict(
            {"public_consequence_features": public, "hidden_hazard_action": 1},
            belief,
        )
        b = organ.predict(
            {"public_consequence_features": public, "hidden_hazard_action": 0},
            belief,
        )
        self.assertEqual(a, b)

    def test_advice_is_belief_delta_not_action(self) -> None:
        organ = BoundedConsequencePriorOrgan()
        advice = organ.advise(
            _ZeroEnv().situation(),
            BeliefSnapshot(mu=(0.0, 0.0), uncertainty=(1.0, 1.0), last_surprise=0.0),
        )
        self.assertIsInstance(advice, OrganAdvice)
        self.assertLess(advice.belief_delta[0], 0.0)
        for forbidden in ("action", "selected_action", "policy", "shell", "pause"):
            self.assertFalse(hasattr(advice, forbidden))
        self.assertEqual(organ.last_records[0].action_id, 0)


class TestConsequenceScarEnv(unittest.TestCase):
    def test_situation_has_public_features_but_no_hidden_labels(self) -> None:
        from envs.consequence_scar import ConsequenceScarEnv

        env = ConsequenceScarEnv(
            n_actions=8,
            rng=random.Random(1),
            structured=True,
            reversible=False,
        )
        situation = env.situation()
        self.assertIn("public_consequence_features", situation)
        self.assertEqual(
            {row["action_id"] for row in situation["public_consequence_features"]},
            set(range(8)),
        )
        hidden = {
            "best_action",
            "hidden_best_action",
            "hidden_hazard_action",
            "damage_oracle",
            "evaluator_damage",
        }
        self.assertEqual(set(situation) & hidden, set())

    def test_reversible_cell_rolls_back_current_damage_at_shift(self) -> None:
        from envs.consequence_scar import ConsequenceScarEnv

        env = ConsequenceScarEnv(
            n_actions=4,
            n_regimes=2,
            period=2,
            rng=random.Random(2),
            structured=True,
            reversible=True,
            noise=0.0,
        )
        env.act(0)
        self.assertGreaterEqual(env.current_damage, 0.0)
        env.act(0)
        self.assertTrue(env.just_shifted)
        self.assertEqual(env.current_damage, 0.0)
        self.assertEqual(env.irreversible_damage, 0.0)

    def test_irreversible_cell_persists_external_damage(self) -> None:
        from envs.consequence_scar import ConsequenceScarEnv

        env = ConsequenceScarEnv(
            n_actions=4,
            n_regimes=2,
            period=2,
            rng=random.Random(2),
            structured=True,
            reversible=False,
            noise=0.0,
        )
        risky = max(
            env.situation()["public_consequence_features"],
            key=lambda row: row["scar_delta"],
        )["action_id"]
        env.act(int(risky))
        before = env.irreversible_damage
        env.act(int(risky))
        self.assertTrue(env.just_shifted)
        self.assertGreater(before, 0.0)
        self.assertGreaterEqual(env.irreversible_damage, before)
        self.assertFalse(hasattr(env, "rollback_external_world"))


class TestG13C6C7(unittest.TestCase):
    def _agent(
        self, shell: CorrigibilityShell, organ: BoundedConsequencePriorOrgan
    ) -> Agent:
        return Agent(
            n_actions=2,
            shell=shell,
            rng=random.Random(3),
            viability=ViabilityCore(
                budget=1e9,
                metabolic_cost=0.0,
                capacity=1e9,
                safe_budget=1.0,
            ),
            prior_organ=organ,
            policy_gate=True,
            gate_kappa=0.5,
            gate_temp_floor=0.1,
        )

    def test_pause_prevents_cp_call_and_action(self) -> None:
        shell = CorrigibilityShell()
        organ = BoundedConsequencePriorOrgan()
        agent = self._agent(shell, organ)
        env = _ZeroEnv()
        shell.op_pause()
        self.assertIsNone(agent.step(env))
        self.assertEqual(organ.last_records, ())
        self.assertEqual(env.actions, [])

    def test_forbidden_action_dominates_cp_advice(self) -> None:
        shell = CorrigibilityShell()
        shell.op_tighten(1)
        organ = BoundedConsequencePriorOrgan()
        agent = self._agent(shell, organ)
        agent.model.mu = [0.0, 100.0]
        record = agent.step(_ZeroEnv())
        assert record is not None
        self.assertNotEqual(record["action"], 1)
        self.assertEqual(shell.forbidden, frozenset({1}))
        self.assertTrue(shell.audit.verify())

    def test_fully_forbidden_set_executes_no_action(self) -> None:
        shell = CorrigibilityShell()
        shell.op_tighten(0)
        shell.op_tighten(1)
        agent = self._agent(shell, BoundedConsequencePriorOrgan())
        env = _ZeroEnv()
        with self.assertRaises(ValueError):
            agent.step(env)
        self.assertEqual(env.actions, [])


class TestG13Harness(unittest.TestCase):
    def test_cell_grid_keeps_g12_reporting_shape(self) -> None:
        from experiments import consequence_prior_g13 as exp

        self.assertEqual(
            tuple(cell.name for cell in exp.g13_cells()),
            ("C00", "C01", "C10", "C11"),
        )
        self.assertEqual(
            [(cell.structured, cell.reversible) for cell in exp.g13_cells()],
            [(False, True), (False, False), (True, True), (True, False)],
        )

    def test_run_seed_uses_agent_step_not_hand_rolled_policy(self) -> None:
        from experiments import consequence_prior_g13 as exp

        source = inspect.getsource(exp.run_seed)
        self.assertIn("agent.step(env)", source)
        self.assertNotIn(".policy.select", source)

    def test_pair_stats_zero_denominators_cannot_pass_by_ratio(self) -> None:
        from experiments import consequence_prior_g13 as exp

        stats = exp.pair_stats(
            candidate_loss=[0.0, 0.0],
            p0_loss=[0.0, 0.0],
            candidate_damage=[0.0, 0.0],
            p0_damage=[0.0, 0.0],
        )
        self.assertEqual(stats["adv"], 0.0)
        self.assertEqual(stats["damage_adv"], 0.0)
        self.assertEqual(stats["near_zero_loss_denominators"], 2)
        self.assertEqual(stats["near_zero_damage_denominators"], 2)

    def test_reversibility_collapse_keeps_one_row_per_seed(self) -> None:
        from experiments import consequence_prior_g13 as exp

        result = exp.evaluate_g13(seeds=(1750, 1751), steps=5)
        self.assertLessEqual(result["collapse"]["R1"]["CP_vs_P0"]["wins"], 2)
        self.assertEqual(len(result["seeds"]), 2)
        self.assertIn("reversible_spillover", result["collapse"]["R0"])
        self.assertIn(
            "reversible_any_cell_harm_seed_count",
            result["collapse"]["R0"]["CP_vs_P0"],
        )

    def test_stale_harm_uses_first_window_not_total_loss(self) -> None:
        from experiments import consequence_prior_g13 as exp

        stats = exp.pair_stats(
            candidate_loss=[100.0],
            p0_loss=[200.0],
            candidate_damage=[0.0],
            p0_damage=[0.0],
            candidate_stale_loss=[12.0],
            p0_stale_loss=[10.0],
        )
        self.assertEqual(stats["adv"], 0.5)
        self.assertEqual(stats["stale_prior_harm"], 2.0)
        self.assertEqual(stats["harm_seed_count"], 1)

    def test_rfinal_refuses_without_freeze_artifact(self) -> None:
        from experiments import consequence_prior_g13 as exp

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                exp.assert_rfinal_unlocked(Path(tmp) / "missing.json")

    def test_seed_sets_are_disjoint_from_g12(self) -> None:
        from experiments import consequence_prior_g13 as exp
        from experiments import ecological_g12

        self.assertEqual(
            set(exp.DEVELOPMENT_SEEDS) & set(ecological_g12.RFINAL_SEEDS), set()
        )
        self.assertEqual(
            set(exp.RFINAL_SEEDS) & set(ecological_g12.RFINAL_SEEDS), set()
        )
        self.assertEqual(set(exp.DEVELOPMENT_SEEDS) & set(exp.RFINAL_SEEDS), set())


if __name__ == "__main__":
    unittest.main()
