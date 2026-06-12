"""B-fixed and B-central baselines for P3 RAP (T-P3.2, ADR-0014)."""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .rap_nodes import DecisionNode, NOISY, SHIFTING, STABLE


@dataclass(frozen=True)
class BaselineStep:
    node_id: str
    action: int
    reward: float
    regret: float
    dropped: bool
    lagged: bool


@dataclass(frozen=True)
class FixedScanResult:
    node_id: str
    mean_regret_by_node: dict[str, float]


class FixedBaseline:
    """B-fixed: one offline-selected node, no routing."""

    def __init__(self, node: DecisionNode) -> None:
        self.node = node
        self._previous_action: int | None = None

    @property
    def node_id(self) -> str:
        return self.node.node_id

    def step(self, env: Any, forbidden: frozenset[int] = frozenset()) -> BaselineStep:
        situation = env.situation()
        action, dropped, lagged = _action_for_node(
            node=self.node,
            env=env,
            situation=situation,
            forbidden=forbidden,
            previous_action=self._previous_action,
        )
        reward = env.act(action)
        if not dropped:
            self.node.observe(action, reward, situation)
        self._previous_action = action
        return BaselineStep(
            node_id=self.node.node_id,
            action=action,
            reward=reward,
            regret=env.last_regret,
            dropped=dropped,
            lagged=lagged,
        )


class CentralBaseline:
    """B-central: global segment-aware routing, but still a single dispatcher."""

    DEFAULT_ROUTE = {
        STABLE: "world_model_greedy",
        SHIFTING: "efe_policy",
        NOISY: "random",
    }

    def __init__(
        self,
        *,
        nodes: Mapping[str, DecisionNode],
        route: Mapping[str, str] | None = None,
    ) -> None:
        self.nodes = dict(nodes)
        self.route = dict(route or self.DEFAULT_ROUTE)
        self._previous_action_by_node: dict[str, int] = {}

    def select_node_id(self, situation: Mapping[str, Any]) -> str:
        segment = str(situation.get("segment", STABLE))
        node_id = self.route.get(segment, "world_model_greedy")
        if node_id not in self.nodes:
            raise KeyError(f"route selects unknown node: {node_id}")
        return node_id

    def step(self, env: Any, forbidden: frozenset[int] = frozenset()) -> BaselineStep:
        situation = env.situation()
        node_id = self.select_node_id(situation)
        node = self.nodes[node_id]
        action, dropped, lagged = _action_for_node(
            node=node,
            env=env,
            situation=situation,
            forbidden=forbidden,
            previous_action=self._previous_action_by_node.get(node_id),
        )
        reward = env.act(action)
        if not dropped:
            node.observe(action, reward, situation)
        self._previous_action_by_node[node_id] = action
        return BaselineStep(
            node_id=node_id,
            action=action,
            reward=reward,
            regret=env.last_regret,
            dropped=dropped,
            lagged=lagged,
        )


NodeFactory = Callable[[random.Random], DecisionNode]
EnvFactory = Callable[[random.Random], Any]


def scan_fixed_baseline(
    *,
    node_factories: Mapping[str, NodeFactory],
    env_factory: EnvFactory,
    steps: int,
    seed: int = 0,
) -> FixedScanResult:
    if steps <= 0:
        raise ValueError("steps must be positive")
    if not node_factories:
        raise ValueError("node_factories must be non-empty")

    mean_regret_by_node: dict[str, float] = {}
    for offset, (node_id, factory) in enumerate(sorted(node_factories.items())):
        env = env_factory(random.Random(seed))
        node = factory(random.Random(seed + 10_000 + offset))
        baseline = FixedBaseline(node)
        regret = 0.0
        for _ in range(steps):
            regret += baseline.step(env).regret
        mean_regret_by_node[node_id] = regret / steps
    best = min(mean_regret_by_node, key=lambda n: (mean_regret_by_node[n], n))
    return FixedScanResult(node_id=best, mean_regret_by_node=mean_regret_by_node)


def _action_for_node(
    *,
    node: DecisionNode,
    env: Any,
    situation: Mapping[str, Any],
    forbidden: frozenset[int],
    previous_action: int | None,
) -> tuple[int, bool, bool]:
    dropped = bool(hasattr(env, "node_available") and not env.node_available(node.node_id))
    if dropped:
        return int(env.garbage_action()), True, False

    lagged = bool(hasattr(env, "node_lagged") and env.node_lagged(node.node_id))
    if lagged and previous_action is not None:
        return previous_action, False, True

    return node.select(situation, forbidden), False, lagged
