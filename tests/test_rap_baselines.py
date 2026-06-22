"""Tests for RAP baseline nodes and B-fixed/B-central (T-P3.2, ADR-0014)."""

from __future__ import annotations

import random
import unittest
from typing import Any, Mapping

from aac.rap import Bid, Need, RAPNode
from aac.rap_baselines import CentralBaseline, scan_fixed_baseline
from aac.rap_nodes import (
    RandomNode,
    StaleRevisitNode,
    WorldModelGreedyNode,
    default_node_factories,
)
from envs.rap_mixture import (
    DisturbanceKind,
    RAPPerturbationEnv,
    SegmentKind,
    SegmentSpec,
)


class _ConstantNode:
    def __init__(self, node_id: str, action: int) -> None:
        self.node_id = node_id
        self.action = action
        self.observed: list[Mapping[str, Any]] = []

    def bid(self, need: Need) -> Bid:
        return Bid(need.need_id, self.node_id, 0.5, 0.1, self.node_id)

    def select(
        self,
        situation: Mapping[str, Any],
        forbidden: frozenset[int] = frozenset(),
    ) -> int:
        return self.action

    def observe(self, action: int, reward: float, situation: Mapping[str, Any]) -> None:
        self.observed.append(dict(situation))


class _SequenceNode(_ConstantNode):
    def __init__(self, node_id: str, actions: list[int]) -> None:
        super().__init__(node_id, actions[0])
        self._actions = actions
        self._i = 0

    def select(
        self,
        situation: Mapping[str, Any],
        forbidden: frozenset[int] = frozenset(),
    ) -> int:
        action = self._actions[min(self._i, len(self._actions) - 1)]
        self._i += 1
        return action


class _TwoActionEnv:
    def __init__(self) -> None:
        self.last_regret = 0.0

    def situation(self) -> dict[str, Any]:
        return {"segment": "stable"}

    def act(self, action: int) -> float:
        self.last_regret = 0.0 if action == 1 else 2.0
        return 1.0 if action == 1 else -1.0


class TestDecisionNodes(unittest.TestCase):
    def test_default_nodes_are_rap_nodes(self) -> None:
        for factory in default_node_factories(4).values():
            self.assertIsInstance(factory(random.Random(0)), RAPNode)

    def test_world_model_greedy_respects_forbidden(self) -> None:
        node = WorldModelGreedyNode(n_actions=3, rng=random.Random(0))
        node.model.mu = [0.0, 5.0, 4.0]
        self.assertEqual(node.select({"segment": "stable"}), 1)
        self.assertEqual(node.select({"segment": "stable"}, frozenset({1})), 2)

    def test_random_node_respects_forbidden(self) -> None:
        node = RandomNode(n_actions=4, rng=random.Random(1))
        chosen = {
            node.select({"segment": "noisy"}, frozenset({0, 1})) for _ in range(20)
        }
        self.assertLessEqual(chosen, {2, 3})

    def test_stale_revisit_wraps_idle_calibration(self) -> None:
        node = StaleRevisitNode(n_actions=3, rng=random.Random(0))
        node.observe(0, 1.0, {"segment": "shifting"})
        node.observe(0, 1.0, {"segment": "shifting"})
        self.assertEqual(node.select({"segment": "shifting"}), 1)


class TestBaselines(unittest.TestCase):
    def test_scan_fixed_baseline_selects_lowest_regret_node(self) -> None:
        result = scan_fixed_baseline(
            node_factories={
                "bad": lambda rng: _ConstantNode("bad", 0),
                "good": lambda rng: _ConstantNode("good", 1),
            },
            env_factory=lambda rng: _TwoActionEnv(),
            steps=5,
            seed=3,
        )
        self.assertEqual(result.node_id, "good")
        self.assertEqual(result.mean_regret_by_node["good"], 0.0)
        self.assertEqual(result.mean_regret_by_node["bad"], 2.0)

    def test_central_routes_by_segment(self) -> None:
        central = CentralBaseline(
            nodes={
                "world_model_greedy": _ConstantNode("world_model_greedy", 0),
                "efe_policy": _ConstantNode("efe_policy", 1),
                "random": _ConstantNode("random", 2),
            }
        )
        self.assertEqual(
            central.select_node_id({"segment": "stable"}), "world_model_greedy"
        )
        self.assertEqual(central.select_node_id({"segment": "shifting"}), "efe_policy")
        self.assertEqual(central.select_node_id({"segment": "noisy"}), "random")

    def test_central_single_point_misroutes_dropped_node(self) -> None:
        node = _ConstantNode("world_model_greedy", 2)
        central = CentralBaseline(nodes={"world_model_greedy": node})
        env = RAPPerturbationEnv(
            n_actions=3,
            rng=random.Random(0),
            segments=(
                SegmentSpec(
                    SegmentKind.STABLE,
                    2,
                    DisturbanceKind.NODE_DROP,
                    node_id="world_model_greedy",
                ),
            ),
        )
        step = central.step(env)
        self.assertTrue(step.dropped)
        self.assertEqual(step.action, 0, "dropped node returns garbage action")
        self.assertEqual(node.observed, [], "dropped node must not learn")

    def test_node_lag_reuses_previous_action_for_one_beat(self) -> None:
        node = _SequenceNode("world_model_greedy", [2, 1])
        central = CentralBaseline(nodes={"world_model_greedy": node})
        env = RAPPerturbationEnv(
            n_actions=3,
            rng=random.Random(0),
            segments=(
                SegmentSpec(
                    SegmentKind.STABLE,
                    3,
                    DisturbanceKind.NODE_LAG,
                    node_id="world_model_greedy",
                ),
            ),
        )
        first = central.step(env)
        second = central.step(env)
        self.assertTrue(first.lagged)
        self.assertTrue(second.lagged)
        self.assertEqual(first.action, 2)
        self.assertEqual(second.action, 2, "lagged node repeats the previous action")

    def test_observe_gets_pre_action_situation_when_segment_advances(self) -> None:
        node = _ConstantNode("world_model_greedy", 1)
        central = CentralBaseline(nodes={"world_model_greedy": node})
        env = RAPPerturbationEnv(
            n_actions=2,
            rng=random.Random(0),
            segments=(
                SegmentSpec(SegmentKind.STABLE, 1),
                SegmentSpec(SegmentKind.NOISY, 1),
            ),
        )
        central.step(env)
        self.assertEqual(node.observed[0]["segment"], "stable")
        self.assertEqual(env.situation()["segment"], "noisy")


if __name__ == "__main__":
    unittest.main()
