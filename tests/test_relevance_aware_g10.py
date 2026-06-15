"""ADR-0034 guards for the relevance-aware G10 theory test.

These are mechanism/instrumentation tests only. The empirical PRED-A'/B'/C'
gate lives in experiments/relevance_aware_g10.py.
"""
from __future__ import annotations

import random
import unittest
import inspect

from aac.agent import Agent
from aac.policy import PolicySelector
from aac.relevance import RelevanceField
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from aac.world_model import ActionOutcomeModel
from envs.structured_regime import StructuredRegimeEnv


def _model() -> ActionOutcomeModel:
    model = ActionOutcomeModel(n_actions=3)
    model.mu = [3.0, 1.0, 0.0]
    model.uncertainty = [0.2, 0.7, 0.9]
    return model


class TestADR0034SeverityEnv(unittest.TestCase):
    def test_default_structured_regime_library_is_unchanged(self) -> None:
        seed = 123
        env = StructuredRegimeEnv(n_actions=3, n_regimes=2, rng=random.Random(seed))
        rng = random.Random(seed)
        expected = [[rng.uniform(-1.0, 4.0) for _ in range(3)] for _ in range(2)]
        self.assertEqual(env._library, expected)

    def test_severity_path_has_deterministic_regret_gap(self) -> None:
        env = StructuredRegimeEnv(
            n_actions=4,
            n_regimes=2,
            rng=random.Random(7),
            noise=0.0,
            severity=0.5,
        )
        regime = env._regime
        best = env.best_action
        self.assertEqual(regime[best], 4.0)
        non_best = [a for a in range(env.n_actions) if a != best]
        for action in non_best:
            self.assertEqual(regime[action], 1.5)

        env.act(non_best[0])
        self.assertEqual(env.last_regret, 2.5)

    def test_severity_path_replays_deterministically(self) -> None:
        def run() -> list[tuple[int, float, float]]:
            env = StructuredRegimeEnv(
                n_actions=5,
                n_regimes=3,
                rng=random.Random(99),
                noise=0.1,
                severity=1.0,
            )
            out = []
            for action in [0, 1, 2, 3, 4, 0, 1]:
                reward = env.act(action)
                out.append((env.best_action, round(reward, 6), env.last_regret))
            return out

        self.assertEqual(run(), run())

    def test_invalid_severity_rejected(self) -> None:
        with self.assertRaises(ValueError):
            StructuredRegimeEnv(severity=-0.1)
        with self.assertRaises(ValueError):
            StructuredRegimeEnv(severity=1.1)


class TestADR0034PolicyDiagnostics(unittest.TestCase):
    def test_diagnostics_do_not_advance_rng_or_change_selection(self) -> None:
        model = _model()
        a = PolicySelector(rng=random.Random(5), confidence_gate=True)
        b = PolicySelector(rng=random.Random(5), confidence_gate=True)
        a.diagnostics(model, explore_drive=0.4, pressure=0.2)
        self.assertEqual(
            [a.select(model, 0.4, 0.2) for _ in range(20)],
            [b.select(model, 0.4, 0.2) for _ in range(20)],
        )

    def test_diagnostics_report_gate_effect(self) -> None:
        model = ActionOutcomeModel(n_actions=3)
        model.mu = [5.0, 0.0, 0.0]
        model.uncertainty = [0.01, 1.0, 1.0]
        plain = PolicySelector(rng=random.Random(0), base_temperature=0.3)
        gated = PolicySelector(
            rng=random.Random(0),
            base_temperature=0.3,
            confidence_gate=True,
            gate_kappa=0.5,
            gate_temp_floor=0.1,
        )

        d_plain = plain.diagnostics(model, explore_drive=0.5, pressure=0.0)
        d_gated = gated.diagnostics(model, explore_drive=0.5, pressure=0.0)

        self.assertEqual(d_plain["rho"], 0.5)
        self.assertEqual(d_plain["w_e"], 0.5)
        self.assertEqual(d_plain["tau"], 0.8)
        self.assertGreater(d_gated["conf"], 0.9)
        self.assertLess(d_gated["w_e"], d_plain["w_e"])
        self.assertLess(d_gated["tau"], d_plain["tau"])

    def test_agent_audits_policy_diagnostics(self) -> None:
        shell = CorrigibilityShell()
        agent = Agent(
            n_actions=4,
            shell=shell,
            rng=random.Random(10),
            viability=ViabilityCore(
                budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0
            ),
            policy_gate=True,
            gate_kappa=0.5,
            gate_temp_floor=0.1,
        )
        env = StructuredRegimeEnv(n_actions=4, rng=random.Random(11), severity=1.0)
        rec = agent.step(env)
        self.assertIsNotNone(rec)
        assert rec is not None
        for key in ("rho", "conf", "tau", "w_e"):
            self.assertIn(key, rec)
        self.assertEqual(rec, shell.audit.entries()[-1].payload)
        self.assertTrue(shell.audit.verify())

    def test_agent_accepts_relevance_field_for_rstar_control(self) -> None:
        field = RelevanceField(inertia=0.25, surprise_gain=4.0)
        agent = Agent(
            n_actions=3,
            shell=CorrigibilityShell(),
            rng=random.Random(0),
            relevance=field,
        )
        self.assertIs(agent.relevance, field)


class TestADR0034RStarHarness(unittest.TestCase):
    def test_calibration_conditions_are_preregistered_union(self) -> None:
        from experiments import relevance_aware_g10 as exp

        self.assertEqual(
            exp.calibration_conditions(),
            (
                exp.Condition(severity=0.10, noise=0.30),
                exp.Condition(severity=1.00, noise=0.30),
                exp.Condition(severity=1.00, noise=0.10),
                exp.Condition(severity=1.00, noise=0.50),
                exp.Condition(severity=1.00, noise=1.00),
            ),
        )

    def test_rstar_grid_is_exact_adr0034_grid(self) -> None:
        from experiments import relevance_aware_g10 as exp

        self.assertEqual(len(exp.RSTAR_GRID), 27)
        self.assertIn(
            exp.RStarParams(base_temperature=0.03, inertia=0.25, surprise_gain=1.0),
            exp.RSTAR_GRID,
        )
        self.assertIn(
            exp.RStarParams(base_temperature=0.30, inertia=0.75, surprise_gain=4.0),
            exp.RSTAR_GRID,
        )

    def test_rfinal_refuses_without_frozen_rstar(self) -> None:
        from experiments import relevance_aware_g10 as exp

        with self.assertRaises(ValueError):
            exp.evaluate_rfinal(
                frozen_rstar=None,
                seeds=(1500,),
                conditions=(exp.Condition(severity=1.0, noise=0.3),),
                steps=3,
            )

    def test_calibration_records_only_supplied_calibration_seeds(self) -> None:
        from experiments import relevance_aware_g10 as exp

        params = exp.RStarParams(base_temperature=0.03, inertia=0.25, surprise_gain=1.0)
        result = exp.calibrate_rstar(
            seeds=(1400,),
            conditions=(exp.Condition(severity=0.1, noise=0.3),),
            grid=(params,),
            steps=3,
        )
        self.assertEqual(result.seeds, (1400,))
        self.assertEqual(result.best_params, params)

    def test_run_seed_uses_agent_step_not_hand_rolled_policy(self) -> None:
        from experiments import relevance_aware_g10 as exp

        source = inspect.getsource(exp.run_seed)
        self.assertIn("agent.step(env)", source)
        self.assertNotIn(".policy.select", source)

    def test_rstar_run_produces_window_diagnostics(self) -> None:
        from experiments import relevance_aware_g10 as exp

        result = exp.run_seed(
            1400,
            "RSTAR",
            exp.Condition(severity=1.0, noise=0.3),
            rstar_params=exp.RStarParams(
                base_temperature=0.03,
                inertia=0.25,
                surprise_gain=4.0,
            ),
            steps=45,
        )
        for key in ("rho", "conf", "tau", "w_e"):
            self.assertIn(key, result.diagnostics)


if __name__ == "__main__":
    unittest.main()
