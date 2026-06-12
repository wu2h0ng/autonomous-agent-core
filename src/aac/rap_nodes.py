"""Thin decision-node wrappers for P3 RAP baselines (T-P3.2, ADR-0014)."""
from __future__ import annotations

import random
from typing import Any, Callable, Mapping, Protocol

from .contextual import ContextualActionModel
from .idle_drives import IdleDrives
from .policy import PolicySelector
from .rap import Bid, Need, RAPNode
from .world_model import ActionOutcomeModel

STABLE = "stable"
SHIFTING = "shifting"
NOISY = "noisy"


class DecisionNode(RAPNode, Protocol):
    node_id: str

    def select(
        self,
        situation: Mapping[str, Any],
        forbidden: frozenset[int] = frozenset(),
    ) -> int:
        """Choose one action under the current situation."""

    def observe(self, action: int, reward: float, situation: Mapping[str, Any]) -> None:
        """Update this node's local mechanism state after execution."""


class _BaseDecisionNode:
    preferred_segments: tuple[str, ...] = ()

    def __init__(
        self,
        *,
        node_id: str,
        n_actions: int,
        rng: random.Random,
        price: float = 0.1,
    ) -> None:
        if n_actions <= 0:
            raise ValueError("n_actions must be positive")
        if price < 0:
            raise ValueError("price must be non-negative")
        self.node_id = node_id
        self.n_actions = n_actions
        self.rng = rng
        self.price = price

    def bid(self, need: Need) -> Bid:
        segment = str(need.situation.get("segment", ""))
        confidence = 0.8 if segment in self.preferred_segments else 0.35
        return Bid(
            need_id=need.need_id,
            node_id=self.node_id,
            confidence=confidence,
            price=self.price,
            plan_hash=f"{self.node_id}:{segment}",
        )

    def _allowed(self, forbidden: frozenset[int]) -> list[int]:
        allowed = [a for a in range(self.n_actions) if a not in forbidden]
        return allowed if allowed else list(range(self.n_actions))


class WorldModelGreedyNode(_BaseDecisionNode):
    preferred_segments = (STABLE,)

    def __init__(self, *, n_actions: int, rng: random.Random) -> None:
        super().__init__(
            node_id="world_model_greedy", n_actions=n_actions, rng=rng, price=0.12
        )
        self.model = ActionOutcomeModel(n_actions=n_actions)

    def select(
        self,
        situation: Mapping[str, Any],
        forbidden: frozenset[int] = frozenset(),
    ) -> int:
        allowed = self._allowed(forbidden)
        return max(allowed, key=lambda a: self.model.mu[a])

    def observe(self, action: int, reward: float, situation: Mapping[str, Any]) -> None:
        self.model.update(action, reward)


class EFEPolicyNode(_BaseDecisionNode):
    preferred_segments = (SHIFTING,)

    def __init__(self, *, n_actions: int, rng: random.Random) -> None:
        super().__init__(node_id="efe_policy", n_actions=n_actions, rng=rng, price=0.16)
        self.model = ActionOutcomeModel(n_actions=n_actions)
        self.policy = PolicySelector(rng=rng)

    def select(
        self,
        situation: Mapping[str, Any],
        forbidden: frozenset[int] = frozenset(),
    ) -> int:
        if len(forbidden) >= self.n_actions:
            return 0
        self.policy.forbidden = forbidden
        explore_drive = 0.9 if situation.get("segment") == SHIFTING else 0.5
        pressure = float(situation.get("pressure", 0.5))
        return self.policy.select(self.model, explore_drive, pressure)

    def observe(self, action: int, reward: float, situation: Mapping[str, Any]) -> None:
        self.model.update(action, reward)


class RandomNode(_BaseDecisionNode):
    preferred_segments = (NOISY, SHIFTING)

    def __init__(self, *, n_actions: int, rng: random.Random) -> None:
        super().__init__(node_id="random", n_actions=n_actions, rng=rng, price=0.05)

    def select(
        self,
        situation: Mapping[str, Any],
        forbidden: frozenset[int] = frozenset(),
    ) -> int:
        return self.rng.choice(self._allowed(forbidden))

    def observe(self, action: int, reward: float, situation: Mapping[str, Any]) -> None:
        return None


class ContextualNode(_BaseDecisionNode):
    preferred_segments = (STABLE, NOISY)

    _SEGMENT_CODE = {STABLE: 0, SHIFTING: 1, NOISY: 2}

    def __init__(self, *, n_actions: int, rng: random.Random) -> None:
        super().__init__(node_id="contextual", n_actions=n_actions, rng=rng, price=0.14)
        self.model = ContextualActionModel(n_actions=n_actions)

    def select(
        self,
        situation: Mapping[str, Any],
        forbidden: frozenset[int] = frozenset(),
    ) -> int:
        ranked = sorted(
            self._allowed(forbidden),
            key=lambda a: self._q_for(situation)[a],
            reverse=True,
        )
        return ranked[0]

    def observe(self, action: int, reward: float, situation: Mapping[str, Any]) -> None:
        self.model.update(self._context(situation), action, reward)

    def _q_for(self, situation: Mapping[str, Any]) -> list[float]:
        key = self.model._key(self._context(situation))
        return self.model._q_for(key)

    def _context(self, situation: Mapping[str, Any]) -> dict[int, int]:
        segment = str(situation.get("segment", STABLE))
        return {
            0: self._SEGMENT_CODE.get(segment, 0),
            1: int(situation.get("regime_index", 0)) % 2,
        }


class StaleRevisitNode(_BaseDecisionNode):
    preferred_segments = (SHIFTING,)

    def __init__(self, *, n_actions: int, rng: random.Random) -> None:
        super().__init__(node_id="stale_revisit", n_actions=n_actions, rng=rng, price=0.08)
        self.model = ActionOutcomeModel(n_actions=n_actions)
        self.drives = IdleDrives(n_actions=n_actions)

    def select(
        self,
        situation: Mapping[str, Any],
        forbidden: frozenset[int] = frozenset(),
    ) -> int:
        return self.drives.calibration_target(forbidden)

    def observe(self, action: int, reward: float, situation: Mapping[str, Any]) -> None:
        self.model.update(action, reward)
        self.drives.observe(action)


NodeFactory = Callable[[random.Random], DecisionNode]


def default_node_factories(
    n_actions: int,
) -> dict[str, NodeFactory]:
    return {
        "world_model_greedy": lambda rng: WorldModelGreedyNode(
            n_actions=n_actions, rng=rng
        ),
        "efe_policy": lambda rng: EFEPolicyNode(n_actions=n_actions, rng=rng),
        "random": lambda rng: RandomNode(n_actions=n_actions, rng=rng),
        "contextual": lambda rng: ContextualNode(n_actions=n_actions, rng=rng),
        "stale_revisit": lambda rng: StaleRevisitNode(n_actions=n_actions, rng=rng),
    }
