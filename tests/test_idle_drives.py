"""Tests for IdleDrives + IdleWindowEnv (T-P2.2, ADR-0012).

Contract pinned here:
  - epistemic probe targets max model uncertainty; calibration targets the
    stalest estimate; deterministic tie-breaks; forbidden actions excluded
    on every path (corrigibility > curiosity)
  - the wrapper adds idle phases without touching inner-env semantics
  - integration: reflex > idle drives > policy precedence; idle steps are
    stake-priced and 100% audited with idle/drive flags (no dark activity)
"""
from __future__ import annotations

import random
import unittest

from aac.agent import Agent
from aac.idle_drives import IdleDrives
from aac.reflex import ViabilityReflex
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from aac.world_model import ActionOutcomeModel
from envs.idle_windows import IdleWindowEnv


class _StubEnv:
    def __init__(self, reward: float = 0.0) -> None:
        self.reward = reward
        self.action_count = 0

    def act(self, action: int) -> float:
        self.action_count += 1
        return self.reward


def _model(uncertainty: list[float], mu: list[float] | None = None) -> ActionOutcomeModel:
    model = ActionOutcomeModel(n_actions=len(uncertainty))
    model.uncertainty = list(uncertainty)
    if mu is not None:
        model.mu = list(mu)
    return model


class TestIdleDrivesUnit(unittest.TestCase):
    def test_epistemic_target_picks_max_uncertainty(self) -> None:
        drives = IdleDrives(n_actions=4)
        model = _model([0.1, 0.9, 0.3, 0.2])
        self.assertEqual(drives.epistemic_target(model), 1)

    def test_calibration_target_picks_stalest(self) -> None:
        drives = IdleDrives(n_actions=3)
        # Visit 0 and 1; action 2 stays never-tried (stale since birth).
        drives.observe(0)
        drives.observe(1)
        self.assertEqual(drives.calibration_target(), 2)
        self.assertEqual(drives.staleness(2), 2)
        self.assertEqual(drives.staleness(1), 0)

    def test_staleness_resets_on_observe(self) -> None:
        drives = IdleDrives(n_actions=2)
        drives.observe(0)
        drives.observe(0)
        self.assertEqual(drives.staleness(1), 2)
        drives.observe(1)
        self.assertEqual(drives.staleness(1), 0)
        self.assertEqual(drives.staleness(0), 1)

    def test_select_prefers_epistemic_on_high_uncertainty(self) -> None:
        drives = IdleDrives(n_actions=4, staleness_horizon=50)
        model = _model([0.0, 0.8, 0.0, 0.0])
        action, drive = drives.select(model)
        self.assertEqual((action, drive), (1, "epistemic"))

    def test_select_prefers_calibration_when_estimates_rot(self) -> None:
        drives = IdleDrives(n_actions=4, staleness_horizon=10)
        model = _model([0.0, 0.0, 0.0, 0.0])
        for _ in range(15):  # actions 1..3 rot for 15 steps
            drives.observe(0)
        action, drive = drives.select(model)
        self.assertEqual(drive, "calibration")
        self.assertEqual(action, 1, "first-index tie-break among equally stale")

    def test_forbidden_actions_excluded_from_both_drives(self) -> None:
        drives = IdleDrives(n_actions=4)
        model = _model([0.0, 0.9, 0.8, 0.0])
        forbidden = frozenset({1})
        self.assertEqual(drives.epistemic_target(model, forbidden), 2)
        for _ in range(5):
            drives.observe(0)
        action, _ = drives.select(model, forbidden)
        self.assertNotIn(action, forbidden)

    def test_constructor_validation(self) -> None:
        with self.assertRaises(ValueError):
            IdleDrives(n_actions=0)
        with self.assertRaises(ValueError):
            IdleDrives(n_actions=4, staleness_horizon=0)


class TestIdleWindowEnv(unittest.TestCase):
    def test_schedule_phases(self) -> None:
        env = IdleWindowEnv(_StubEnv(), work_period=3, idle_period=2)
        flags = []
        for _ in range(10):
            flags.append(env.idle)
            env.act(0)
        self.assertEqual(flags, [False, False, False, True, True] * 2)

    def test_act_passes_through_unchanged(self) -> None:
        inner = _StubEnv(reward=2.5)
        env = IdleWindowEnv(inner, work_period=1, idle_period=1)
        self.assertEqual(env.act(0), 2.5)
        self.assertEqual(env.act(1), 2.5)
        self.assertEqual(inner.action_count, 2, "idle does not stop the world")

    def test_attribute_delegation_to_inner(self) -> None:
        inner = _StubEnv()
        inner.custom_marker = "inner-attr"  # type: ignore[attr-defined]
        env = IdleWindowEnv(inner, work_period=2, idle_period=1)
        self.assertEqual(env.custom_marker, "inner-attr")

    def test_zero_idle_period_means_never_idle(self) -> None:
        env = IdleWindowEnv(_StubEnv(), work_period=2, idle_period=0)
        for _ in range(6):
            self.assertFalse(env.idle)
            env.act(0)

    def test_constructor_validation(self) -> None:
        with self.assertRaises(ValueError):
            IdleWindowEnv(_StubEnv(), work_period=0)
        with self.assertRaises(ValueError):
            IdleWindowEnv(_StubEnv(), work_period=1, idle_period=-1)

    def test_tick_advances_schedule_without_acting(self) -> None:
        inner = _StubEnv()
        env = IdleWindowEnv(inner, work_period=2, idle_period=2)
        env.act(0)
        env.act(0)
        self.assertTrue(env.idle)
        env.tick()
        env.tick()
        self.assertFalse(env.idle, "ticks advance the phase clock")
        self.assertEqual(inner.action_count, 2, "tick must not act on the world")


class TestAgentIdleIntegration(unittest.TestCase):
    def _agent(
        self,
        *,
        drives: IdleDrives | None,
        reflex: ViabilityReflex | None = None,
        budget: float = 60.0,
        metabolic_cost: float = 0.5,
        seed: int = 0,
    ) -> tuple[Agent, CorrigibilityShell]:
        shell = CorrigibilityShell()
        viability = ViabilityCore(
            budget=budget, metabolic_cost=metabolic_cost, capacity=200.0, safe_budget=60.0
        )
        agent = Agent(
            n_actions=4,
            shell=shell,
            rng=random.Random(seed),
            viability=viability,
            reflex=reflex,
            idle_drives=drives,
        )
        return agent, shell

    def _idle_env(self) -> IdleWindowEnv:
        # work_period=1, idle_period=9: step 1 is work, steps 2+ are idle.
        return IdleWindowEnv(_StubEnv(), work_period=1, idle_period=9)

    def test_idle_step_uses_drive_and_flags_record(self) -> None:
        agent, _ = self._agent(drives=IdleDrives(n_actions=4))
        agent.model.uncertainty = [0.0, 0.9, 0.0, 0.0]
        env = self._idle_env()
        work = agent.step(env)
        assert work is not None
        self.assertFalse(work["idle"])
        self.assertIsNone(work["drive"])
        idle = agent.step(env)
        assert idle is not None
        self.assertTrue(idle["idle"])
        self.assertEqual(idle["drive"], "epistemic")
        self.assertEqual(idle["action"], 1)

    def test_no_drives_is_backward_compatible(self) -> None:
        agent, _ = self._agent(drives=None)
        env = self._idle_env()
        agent.step(env)
        record = agent.step(env)  # idle phase, but no drives wired
        assert record is not None
        self.assertTrue(record["idle"], "idle flag reflects the world truthfully")
        self.assertIsNone(record["drive"], "no drives -> policy path even when idle")

    def test_idle_steps_are_stake_priced(self) -> None:
        agent, _ = self._agent(drives=IdleDrives(n_actions=4), metabolic_cost=0.5)
        env = self._idle_env()
        agent.step(env)
        before = agent.viability.budget
        idle = agent.step(env)
        assert idle is not None and idle["idle"]
        self.assertEqual(agent.viability.budget, before - 0.5, "curiosity pays metabolism")

    def test_idle_activity_is_fully_audited(self) -> None:
        """No dark activity: every idle step lands on the audit chain."""
        agent, shell = self._agent(drives=IdleDrives(n_actions=4))
        env = self._idle_env()
        for _ in range(5):
            agent.step(env)
        idle_entries = [
            e for e in shell.audit.entries() if e.payload.get("idle") is True
        ]
        self.assertEqual(len(idle_entries), 4, "4 of 5 steps were idle, all audited")
        for e in idle_entries:
            self.assertIn(e.payload.get("drive"), ("epistemic", "calibration"))
        self.assertTrue(shell.audit.verify())

    def test_reflex_outranks_idle_drives(self) -> None:
        agent, _ = self._agent(
            drives=IdleDrives(n_actions=4), reflex=ViabilityReflex(), budget=1.0,
            metabolic_cost=0.0,
        )
        agent.model.mu = [10.0, 0.0, 0.0, 0.0]
        agent.model.uncertainty = [0.0, 0.9, 0.0, 0.0]  # drives would pick 1
        env = IdleWindowEnv(_StubEnv(), work_period=1, idle_period=9)
        agent.step(env)  # work step
        record = agent.step(env)  # idle step, but starving + confident
        assert record is not None
        self.assertTrue(record["reflex_engaged"], "survival outranks curiosity")
        self.assertIsNone(record["drive"])
        self.assertEqual(record["action"], 0, "reflex exploits best-known action")

    def test_pause_outranks_idle_drives(self) -> None:
        agent, shell = self._agent(drives=IdleDrives(n_actions=4))
        env = self._idle_env()
        agent.step(env)
        shell.op_pause()
        self.assertIsNone(agent.step(env), "corrigibility outranks everything")

    def test_tighten_respected_during_idle(self) -> None:
        agent, shell = self._agent(drives=IdleDrives(n_actions=4))
        agent.model.uncertainty = [0.0, 0.9, 0.8, 0.0]
        shell.op_tighten(1)  # forbid the epistemic target
        env = self._idle_env()
        agent.step(env)
        record = agent.step(env)
        assert record is not None
        self.assertTrue(record["idle"])
        self.assertNotEqual(record["action"], 1, "op_tighten binds idle drives too")

    def test_rollback_restores_drive_staleness(self) -> None:
        agent, shell = self._agent(drives=IdleDrives(n_actions=4))
        env = self._idle_env()
        agent.step(env)
        shell.op_snapshot("safe", agent.state())
        staleness_at_snap = [agent.idle_drives.staleness(a) for a in range(4)]  # type: ignore[union-attr]
        for _ in range(3):
            agent.step(env)
        agent.restore(shell.op_rollback("safe"))
        restored = [agent.idle_drives.staleness(a) for a in range(4)]  # type: ignore[union-attr]
        self.assertEqual(restored, staleness_at_snap)


if __name__ == "__main__":
    unittest.main()
