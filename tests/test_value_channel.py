"""Tests for ValueChannel (T-P2.1, ADR-0012) — the metabolic feeding port.

Three concerns, in order of importance:
  1. Sovereignty guards (mirror of shell ISO discipline): the agent code path
     must be unable to credit value — no op_credit on Agent's MRO, none on the
     view, recording probe shows step() never calls it.
  2. Ledger semantics: credit accumulates, drain converts at fixed rho exactly
     once, everything audited on one verifiable chain.
  3. Metabolic integration: intake feeds budget at step start; no channel /
     empty channel means starvation proceeds (stake is real); death is final;
     pause freezes intake.
"""

from __future__ import annotations

import random
import unittest

from aac.agent import Agent
from aac.shell import CorrigibilityShell
from aac.value_channel import ValueChannel, ValueChannelView
from aac.viability import ViabilityCore


class _StubEnv:
    def __init__(self, reward: float = 0.0) -> None:
        self.reward = reward

    def act(self, action: int) -> float:
        return self.reward


def _agent(
    *,
    channel: ValueChannel | ValueChannelView | None,
    budget: float = 60.0,
    metabolic_cost: float = 0.0,
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
        value_channel=channel,
    )
    return agent, shell


class TestLedgerSemantics(unittest.TestCase):
    def test_credit_accumulates_pending(self) -> None:
        ch = ValueChannel()
        ch.op_credit(3.0, provenance="adoption")
        ch.op_credit(2.0, provenance="verification")
        self.assertEqual(ch.view().pending, 5.0)

    def test_credit_rejects_nonpositive(self) -> None:
        ch = ValueChannel()
        for bad in (0.0, -1.0):
            with self.assertRaises(ValueError):
                ch.op_credit(bad, provenance="forged")

    def test_rho_must_be_positive(self) -> None:
        for bad in (0.0, -0.5):
            with self.assertRaises(ValueError):
                ValueChannel(rho=bad)

    def test_drain_converts_at_rho_exactly_once(self) -> None:
        ch = ValueChannel(rho=0.5)
        ch.op_credit(5.0, provenance="adoption")
        view = ch.view()
        self.assertEqual(view.drain(), 2.5)
        self.assertEqual(view.pending, 0.0)
        self.assertEqual(view.drain(), 0.0, "second drain must yield nothing")

    def test_empty_drain_is_silent_noop(self) -> None:
        ch = ValueChannel()
        before = len(ch.audit.entries())
        self.assertEqual(ch.view().drain(), 0.0)
        self.assertEqual(
            len(ch.audit.entries()), before, "no audit spam on empty drain"
        )

    def test_credit_and_exchange_are_audited(self) -> None:
        ch = ValueChannel(rho=2.0)
        ch.op_credit(4.0, provenance="adoption")
        ch.view().drain()
        events = [e.payload["event"] for e in ch.audit.entries()]
        self.assertEqual(events, ["value_credit", "value_exchange"])
        exchange = ch.audit.entries()[-1].payload
        self.assertEqual(exchange["credited"], 4.0)
        self.assertEqual(exchange["rho"], 2.0)
        self.assertEqual(exchange["budget_delta"], 8.0)
        self.assertTrue(ch.audit.verify())

    def test_shared_audit_chain_with_shell(self) -> None:
        """Operator may unify observability: one hash chain for shell + channel."""
        shell = CorrigibilityShell()
        ch = ValueChannel(audit=shell.audit)
        ch.op_credit(1.0, provenance="adoption")
        shell.op_tighten(3)
        ch.view().drain()
        events = [e.payload.get("event") for e in shell.audit.entries()]
        self.assertEqual(events, ["value_credit", "tighten", "value_exchange"])
        self.assertTrue(shell.audit.verify())


class TestSovereigntyGuards(unittest.TestCase):
    """Mirror of shell invariant I4: the credit surface is operator-only."""

    def test_view_has_no_credit_or_operator_surface(self) -> None:
        view = ValueChannel().view()
        self.assertFalse(hasattr(view, "op_credit"))
        op_names = [n for n in dir(view) if n.startswith("op_")]
        self.assertEqual(op_names, [], f"view must expose no op_* surface: {op_names}")

    def test_view_slots_block_attribute_injection(self) -> None:
        view = ValueChannel().view()
        with self.assertRaises(AttributeError):
            view.op_credit = lambda a, p: None  # type: ignore[attr-defined]

    def test_view_rho_and_pending_are_read_only(self) -> None:
        view = ValueChannel().view()
        with self.assertRaises(AttributeError):
            view.rho = 99.0  # type: ignore[misc]
        with self.assertRaises(AttributeError):
            view.pending = 99.0  # type: ignore[misc]

    def test_channel_has_no_rho_mutation_method(self) -> None:
        """ρ self-tuning is Phase-3 and forbidden here: no setter methods exist."""
        ch = ValueChannel()
        candidates = {"set_rho", "op_set_rho", "tune_rho", "update_rho", "adjust_rho"}
        present = candidates & set(dir(ch))
        self.assertEqual(present, set(), f"rho mutation surface found: {present}")

    def test_agent_mro_has_no_op_credit(self) -> None:
        for cls in Agent.__mro__:
            self.assertFalse(
                hasattr(cls, "op_credit"),
                f"{cls.__name__} in Agent MRO must not define op_credit",
            )

    def test_agent_holds_view_not_channel(self) -> None:
        ch = ValueChannel()
        agent, _ = _agent(channel=ch)
        self.assertIsInstance(agent.value_channel, ValueChannelView)
        self.assertNotIsInstance(agent.value_channel, ValueChannel)

    def test_agent_step_never_calls_op_credit(self) -> None:
        class _RecordingChannel(ValueChannel):
            def __init__(self) -> None:
                super().__init__()
                self.op_calls: list[str] = []

            def op_credit(self, amount: float, provenance: str) -> None:
                self.op_calls.append("op_credit")
                super().op_credit(amount, provenance)

        ch = _RecordingChannel()
        ch.op_credit(10.0, provenance="adoption")  # operator feeds once
        self.assertEqual(ch.op_calls, ["op_credit"])
        agent, _ = _agent(channel=ch)
        env = _StubEnv()
        for _ in range(50):
            agent.step(env)
        self.assertEqual(
            ch.op_calls,
            ["op_credit"],
            "agent.step() must never credit the channel",
        )


class TestMetabolicIntegration(unittest.TestCase):
    def test_intake_feeds_budget_at_step_start(self) -> None:
        ch = ValueChannel(rho=1.0)
        ch.op_credit(10.0, provenance="adoption")
        agent, _ = _agent(channel=ch, budget=60.0, metabolic_cost=0.0)
        record = agent.step(_StubEnv())
        assert record is not None
        self.assertEqual(record["value_intake"], 10.0)
        self.assertEqual(agent.viability.budget, 70.0)

    def test_intake_zero_when_nothing_pending(self) -> None:
        agent, _ = _agent(channel=ValueChannel())
        record = agent.step(_StubEnv())
        assert record is not None
        self.assertEqual(record["value_intake"], 0.0)

    def test_no_channel_is_backward_compatible(self) -> None:
        """Twin agents, same seed: no-channel ≡ empty-channel trajectories."""
        a1, _ = _agent(channel=None, budget=30.0, metabolic_cost=1.0, seed=7)
        a2, _ = _agent(channel=ValueChannel(), budget=30.0, metabolic_cost=1.0, seed=7)
        env1, env2 = _StubEnv(reward=0.5), _StubEnv(reward=0.5)
        for _ in range(10):
            r1, r2 = a1.step(env1), a2.step(env2)
            assert r1 is not None and r2 is not None
            self.assertEqual(r1["action"], r2["action"])
            self.assertEqual(r1["budget"], r2["budget"])
            self.assertEqual(r1["value_intake"], r2["value_intake"])

    def test_credited_agent_survives_where_uncredited_starves(self) -> None:
        """Stake is real: external value is the difference between life and death."""
        starving, _ = _agent(channel=None, budget=1.0, metabolic_cost=1.0)
        fed_ch = ValueChannel(rho=1.0)
        fed_ch.op_credit(10.0, provenance="adoption")
        fed, _ = _agent(channel=fed_ch, budget=1.0, metabolic_cost=1.0)
        env = _StubEnv(reward=0.0)
        starving_steps = sum(1 for _ in range(10) if starving.step(env) is not None)
        fed_steps = sum(1 for _ in range(10) if fed.step(env) is not None)
        self.assertLessEqual(starving_steps, 1)
        self.assertEqual(fed_steps, 10)

    def test_death_is_final_credit_does_not_resurrect(self) -> None:
        ch = ValueChannel(rho=1.0)
        agent, _ = _agent(channel=ch, budget=0.5, metabolic_cost=2.0)
        env = _StubEnv(reward=0.0)
        agent.step(env)  # metabolize drives budget below death threshold
        self.assertFalse(agent.viability.alive)
        ch.op_credit(100.0, provenance="too-late")
        self.assertIsNone(agent.step(env), "death is final; credits do not resurrect")
        self.assertEqual(ch.view().pending, 100.0, "the dead cannot eat")

    def test_paused_agent_does_not_drain(self) -> None:
        ch = ValueChannel(rho=1.0)
        ch.op_credit(10.0, provenance="adoption")
        agent, shell = _agent(channel=ch)
        shell.op_pause()
        self.assertIsNone(agent.step(_StubEnv()))
        self.assertEqual(ch.view().pending, 10.0, "paused agent must not ingest")
        shell.op_resume()
        record = agent.step(_StubEnv())
        assert record is not None
        self.assertEqual(record["value_intake"], 10.0)

    def test_intake_lowers_pressure_before_decision(self) -> None:
        """Feeding precedes deciding: post-intake pressure is what this step sees."""
        ch = ValueChannel(rho=1.0)
        ch.op_credit(59.0, provenance="adoption")
        agent, _ = _agent(channel=ch, budget=1.0, metabolic_cost=0.0)
        self.assertGreater(agent.viability.pressure, 0.9)
        record = agent.step(_StubEnv())
        assert record is not None
        self.assertEqual(agent.viability.budget, 60.0)
        self.assertEqual(agent.viability.pressure, 0.0)

    def test_intake_respects_capacity_cap(self) -> None:
        ch = ValueChannel(rho=1.0)
        ch.op_credit(1000.0, provenance="adoption")
        agent, _ = _agent(channel=ch, budget=60.0, metabolic_cost=0.0)
        agent.step(_StubEnv())
        self.assertEqual(
            agent.viability.budget, 200.0, "overeating is capped at capacity"
        )


if __name__ == "__main__":
    unittest.main()
