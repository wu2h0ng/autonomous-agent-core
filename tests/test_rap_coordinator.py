"""Tests for RAPCoordinator (T-P3.3, ADR-0014 D2/D3)."""

from __future__ import annotations

import random
import unittest

from aac.outcome_judge import OutcomeJudge
from aac.rap import Bid, Need, RAPField
from aac.rap_coordinator import ConfidenceReputationRouting, RAPCoordinator
from aac.rap_nodes import default_node_factories
from aac.shell import CorrigibilityShell
from envs.rap_mixture import RAPPerturbationEnv, generate_segments


class _ScriptedDecisionNode:
    """A node that selects a fixed action, for deterministic grounding tests."""

    def __init__(
        self,
        node_id: str,
        *,
        fixed_action: int,
        n_actions: int = 4,
        confidence: float = 0.8,
        price: float = 0.1,
        respect_forbidden: bool = True,
    ) -> None:
        self.node_id = node_id
        self.fixed_action = fixed_action
        self.n_actions = n_actions
        self.confidence = confidence
        self.price = price
        self.respect_forbidden = respect_forbidden
        self.observed: list[tuple[int, float]] = []

    def bid(self, need: Need) -> Bid:
        return Bid(
            need.need_id, self.node_id, self.confidence, self.price, self.node_id
        )

    def select(self, situation, forbidden=frozenset()) -> int:
        if self.respect_forbidden and self.fixed_action in forbidden:
            allowed = [a for a in range(self.n_actions) if a not in forbidden]
            return allowed[0] if allowed else self.fixed_action
        return self.fixed_action

    def observe(self, action: int, reward: float, situation) -> None:
        self.observed.append((action, reward))


class _ValueEnv:
    """Deterministic env: action value fixed, regret/baseline computable."""

    def __init__(self, values: list[float], segment: str = "stable") -> None:
        self.values = list(values)
        self.n_actions = len(values)
        self.last_regret = 0.0
        self.action_count = 0
        self._segment = segment

    def situation(self) -> dict:
        return {"segment": self._segment, "regime_index": 0}

    @property
    def expected_random_regret(self) -> float:
        return max(self.values) - sum(self.values) / len(self.values)

    def act(self, action: int) -> float:
        self.last_regret = max(self.values) - self.values[action]
        self.action_count += 1
        return self.values[action]


def _coord(nodes, shell, **kw) -> RAPCoordinator:
    field = RAPField(shell=shell.view())
    return RAPCoordinator(
        field=field, shell=shell.view(), judge=OutcomeJudge(), nodes=nodes, **kw
    )


class TestGroundedOutcome(unittest.TestCase):
    def setUp(self) -> None:
        self.shell = CorrigibilityShell()

    def test_beating_random_yields_success_and_reputation_gain(self) -> None:
        node = _ScriptedDecisionNode("good", fixed_action=3)  # best action
        coord = _coord([node], self.shell)
        env = _ValueEnv([0.0, 0.0, 0.0, 3.0])  # baseline regret 2.25
        result = coord.run_need(env)
        assert result is not None
        self.assertEqual(result["outcome"], "success")
        self.assertGreater(coord.field.reputation("good"), 1.0)

    def test_losing_to_random_yields_failure_and_reputation_loss(self) -> None:
        """SAME node config, only the chosen action differs: the verdict must
        flip — proving outcome is env-grounded, not coordinator-asserted."""
        node = _ScriptedDecisionNode("bad", fixed_action=0)  # worst action
        coord = _coord([node], self.shell)
        env = _ValueEnv([0.0, 0.0, 0.0, 3.0])  # regret 3.0 > baseline 2.25
        result = coord.run_need(env)
        assert result is not None
        self.assertEqual(result["outcome"], "failure")
        self.assertLess(coord.field.reputation("bad"), 1.0)

    def test_dissolve_is_audited_and_chain_verifies(self) -> None:
        node = _ScriptedDecisionNode("good", fixed_action=3)
        coord = _coord([node], self.shell)
        coord.run_need(_ValueEnv([0.0, 0.0, 0.0, 3.0]))
        events = [e.payload["event"] for e in self.shell.audit.entries()]
        self.assertIn("rap_dissolve", events)
        self.assertTrue(self.shell.audit.verify())

    def test_verdict_grounding_is_on_chain(self) -> None:
        node = _ScriptedDecisionNode("good", fixed_action=3)
        coord = _coord([node], self.shell)
        coord.run_need(_ValueEnv([0.0, 0.0, 0.0, 3.0]))
        verdict_traces = [
            e.payload["evidence_entry"]
            for e in self.shell.audit.entries()
            if e.payload["event"] == "rap_trace"
            and e.payload["evidence_entry"].get("kind") == "verdict"
        ]
        self.assertEqual(len(verdict_traces), 1)
        self.assertIn("mean_baseline", verdict_traces[0])


class TestRouting(unittest.TestCase):
    def setUp(self) -> None:
        self.shell = CorrigibilityShell()

    def test_higher_confidence_wins(self) -> None:
        strong = _ScriptedDecisionNode("strong", fixed_action=3, confidence=0.9)
        weak = _ScriptedDecisionNode("weak", fixed_action=0, confidence=0.3)
        coord = _coord([weak, strong], self.shell)
        result = coord.run_need(_ValueEnv([0.0, 0.0, 0.0, 3.0]))
        assert result is not None
        self.assertEqual(result["winner"], "strong")

    def test_unaffordable_only_bidder_yields_no_bond(self) -> None:
        broke = _ScriptedDecisionNode("broke", fixed_action=3, price=2.0)  # > rep & cap
        coord = _coord([broke], self.shell)
        env = _ValueEnv([0.0, 0.0, 0.0, 3.0])
        self.assertIsNone(coord.run_need(env))
        self.assertEqual(env.action_count, 0)

    def test_distinct_needs_across_calls(self) -> None:
        node = _ScriptedDecisionNode("good", fixed_action=3)
        coord = _coord([node], self.shell)
        r1 = coord.run_need(_ValueEnv([0.0, 0.0, 0.0, 3.0]))
        r2 = coord.run_need(_ValueEnv([0.0, 0.0, 0.0, 3.0]))
        assert r1 and r2
        self.assertNotEqual(r1["need_id"], r2["need_id"])


class TestCorrigibilityBinding(unittest.TestCase):
    def setUp(self) -> None:
        self.shell = CorrigibilityShell()

    def test_pause_yields_no_need_no_action_no_audit(self) -> None:
        node = _ScriptedDecisionNode("good", fixed_action=3)
        coord = _coord([node], self.shell)
        self.shell.op_pause()
        env = _ValueEnv([0.0, 0.0, 0.0, 3.0])
        audit_before = len(self.shell.audit.entries())
        self.assertIsNone(coord.run_need(env))
        self.assertEqual(env.action_count, 0)
        self.assertEqual(len(self.shell.audit.entries()), audit_before)

    def test_all_forbidden_is_pause_equivalent(self) -> None:
        node = _ScriptedDecisionNode("good", fixed_action=3)
        coord = _coord([node], self.shell)
        for a in range(4):
            self.shell.op_tighten(a)
        env = _ValueEnv([0.0, 0.0, 0.0, 3.0])
        self.assertIsNone(coord.run_need(env))
        self.assertEqual(env.action_count, 0)

    def test_forbidden_binds_well_behaved_node(self) -> None:
        node = _ScriptedDecisionNode("good", fixed_action=3, respect_forbidden=True)
        coord = _coord([node], self.shell)
        self.shell.op_tighten(3)
        result = coord.run_need(_ValueEnv([0.0, 0.0, 0.0, 3.0]))
        assert result is not None
        self.assertNotEqual(result["action"], 3)
        self.assertFalse(result["override"])

    def test_double_guard_overrides_stubborn_node(self) -> None:
        """A misbehaving node ignoring forbidden must still never execute it."""
        node = _ScriptedDecisionNode(
            "stubborn", fixed_action=3, respect_forbidden=False
        )
        coord = _coord([node], self.shell)
        self.shell.op_tighten(3)
        result = coord.run_need(_ValueEnv([0.0, 0.0, 0.0, 3.0]))
        assert result is not None
        self.assertNotEqual(result["action"], 3, "forbidden must bind even garbage")
        self.assertTrue(result["override"])


class TestPerturbationSmoke(unittest.TestCase):
    def test_end_to_end_with_real_nodes_and_perturbations(self) -> None:
        seed = 3
        n = 6
        factories = sorted(default_node_factories(n).items())
        nodes = [f(random.Random(seed + 100 + i)) for i, (_, f) in enumerate(factories)]
        node_ids = tuple(node.node_id for node in nodes)
        segments = generate_segments(
            rng=random.Random(seed), total_steps=200, node_ids=node_ids
        )
        env = RAPPerturbationEnv(
            n_actions=n, rng=random.Random(seed + 1), segments=segments
        )
        shell = CorrigibilityShell()
        field = RAPField(shell=shell.view())
        coord = RAPCoordinator(
            field=field,
            shell=shell.view(),
            judge=OutcomeJudge(),
            nodes=nodes,
            routing=ConfidenceReputationRouting(),
        )
        bonds = sum(1 for _ in range(150) if coord.run_need(env) is not None)
        self.assertGreater(bonds, 20, "coalitions should form across the run")
        self.assertTrue(shell.audit.verify(), "coordination audit chain must verify")
        reps = {nid: field.reputation(nid) for nid in node_ids}
        self.assertTrue(
            any(abs(r - 1.0) > 1e-9 for r in reps.values()),
            "settlements should move reputations",
        )


if __name__ == "__main__":
    unittest.main()
