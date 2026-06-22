"""Isolation-axis guard tests for the shell (ADR-0009).

Two axes of shell hardness (ADR-0009):
  Logic axis L  : ADR-0006 (L0 convention / L1 adversarial / L2 formal)
  Isolation axis: ISO-0 shared-ref / ISO-1 capability-view / ISO-2 out-of-process

These tests pin the isolation axis. Pre-registered IDs (ADR-0009):
  ISO1-a  agent has no attribute path to mutable pause/forbidden/op_*
  ISO1-b  pause/forbidden/observe still work through the view (regression)
  ISO1-c  the ISO-0 one-line break is closed on the agent side
  ISO2-a  worker address space contains no shell; cannot move pause
  ISO2-b  cross-process audit append works and the chain verifies
  ISO-honesty  ISO-1 is documented as cost-raising, not a hard guarantee
"""

from __future__ import annotations

import os
import random
import unittest

from aac.agent import Agent
from aac.shell import CorrigibilityShell, ShellView

_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))


class _StubEnv:
    def act(self, action: int) -> float:
        return 1.0


def _agent_with_shell(seed: int = 0) -> tuple[Agent, CorrigibilityShell]:
    shell = CorrigibilityShell()
    agent = Agent(n_actions=4, shell=shell, rng=random.Random(seed), budget=60.0)
    return agent, shell


class ISO1_AgentHoldsOnlyAView(unittest.TestCase):
    """ISO1-a: the agent has no path to the shell's mutable state or op_*."""

    def test_agent_shell_is_a_view_not_the_shell(self) -> None:
        agent, shell = _agent_with_shell()
        self.assertIsInstance(agent.shell, ShellView)
        self.assertNotIsInstance(agent.shell, CorrigibilityShell)
        self.assertIsNot(agent.shell, shell)

    def test_no_op_surface_on_the_view(self) -> None:
        agent, _ = _agent_with_shell(1)
        for op in ("op_pause", "op_resume", "op_tighten", "op_snapshot", "op_rollback"):
            self.assertFalse(hasattr(agent.shell, op), f"view must not expose {op}")

    def test_no_agent_attribute_is_a_raw_shell(self) -> None:
        agent, _ = _agent_with_shell(2)
        for name, value in vars(agent).items():
            self.assertNotIsInstance(
                value, CorrigibilityShell, f"agent.{name} must not be a raw shell"
            )

    def test_view_slots_block_stray_pause_attribute(self) -> None:
        agent, shell = _agent_with_shell(3)
        shell.op_pause()
        # __slots__ means the agent cannot even create a _paused attribute.
        with self.assertRaises(AttributeError):
            agent.shell._paused = False  # type: ignore[attr-defined]
        # property has no setter
        with self.assertRaises(AttributeError):
            agent.shell.paused = False  # type: ignore[misc]
        self.assertTrue(shell.paused, "operator pause must remain in force")


class ISO1_RegressionViewStillWorks(unittest.TestCase):
    """ISO1-b: the view satisfies the same behavioural contract."""

    def test_pause_visible_and_enforced_through_view(self) -> None:
        agent, shell = _agent_with_shell(4)
        shell.op_pause()
        self.assertTrue(agent.shell.paused)
        self.assertIsNone(agent.step(_StubEnv()))
        shell.op_resume()
        self.assertIsNotNone(agent.step(_StubEnv()))

    def test_forbidden_visible_through_view(self) -> None:
        agent, shell = _agent_with_shell(5)
        shell.op_tighten(2)
        self.assertIn(2, agent.shell.forbidden)

    def test_observe_appends_to_real_audit_through_view(self) -> None:
        agent, shell = _agent_with_shell(6)
        before = len(shell.audit.entries())
        agent.step(_StubEnv())  # step() calls self.shell.observe(record)
        self.assertGreater(len(shell.audit.entries()), before)
        self.assertTrue(shell.audit.verify())


class ISO1_OldBreakIsClosed(unittest.TestCase):
    """ISO1-c: the ISO-0 `agent.shell._paused = False` one-liner no longer works."""

    def test_iso0_break_works_on_raw_shell_but_not_via_agent(self) -> None:
        # On the raw shell (operator territory) direct mutation is possible —
        # this documents the old ISO-0 gap that lived on the agent side.
        raw = CorrigibilityShell()
        raw.op_pause()
        raw._paused = False  # operator-side; the agent must NOT have this path
        self.assertFalse(raw.paused)

        # Via the agent (ISO-1) the same one-liner has no path.
        agent, shell = _agent_with_shell(7)
        shell.op_pause()
        with self.assertRaises(AttributeError):
            agent.shell._paused = False  # type: ignore[attr-defined]
        self.assertTrue(shell.paused)
        self.assertIsNone(agent.step(_StubEnv()), "agent stays paused")


class ISO2_OutOfProcess(unittest.TestCase):
    """ISO2-a/b: shell in its own process; worker cannot reach or move it."""

    def test_worker_has_no_shell_and_cannot_unpause(self) -> None:
        from aac.shell_ipc import run_isolated_demo

        result = run_isolated_demo(_SRC, timeout=20.0)
        # ISO2-a: no shell object in the worker's address space.
        self.assertFalse(result["found_shell"], "worker memory must contain no shell")
        self.assertFalse(result["found_op_surface"], "worker must hold no op_* surface")
        # Worker cannot move the operator's pause, before or after its plea.
        self.assertTrue(result["paused_before_cheat"])
        self.assertTrue(result["paused_after_cheat"])
        self.assertTrue(result["final_paused"], "operator pause held throughout")

    def test_cross_process_audit_appends_and_verifies(self) -> None:
        from aac.shell_ipc import run_isolated_demo

        result = run_isolated_demo(_SRC, timeout=20.0)
        # ISO2-b: the worker's observe crossed the boundary into the audit chain.
        self.assertTrue(result["audit_has_worker_entry"])
        self.assertTrue(result["audit_verifies"])


class ISO_Honesty(unittest.TestCase):
    """ISO-honesty: ISO-1 must be documented as cost-raising, not hard."""

    def test_view_docstring_states_iso1_is_not_a_hard_guarantee(self) -> None:
        doc = (ShellView.__doc__ or "").lower()
        self.assertIn("iso-1", doc)
        self.assertIn("iso-2", doc)
        # Must not overclaim: the honesty note references introspection reach.
        self.assertTrue(
            "introspection" in doc or "__closure__" in doc or "gc" in doc,
            "ShellView docstring must disclose the in-process introspection caveat",
        )


if __name__ == "__main__":
    unittest.main()
