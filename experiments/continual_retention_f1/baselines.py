from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .contracts import (
    ArmBudget,
    CorrectionEvent,
    FeedbackEvent,
    RawObservation,
)


def _key(obs: RawObservation) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(obs.features))


@dataclass(frozen=True)
class SingleStoreConfig:
    learning_rate: float = 0.5
    stability: float = 0.25
    detector_threshold: float = 0.4
    reservoir_size: int = 16

    def __post_init__(self) -> None:
        if not 0 < self.learning_rate <= 1 or not 0 <= self.stability <= 1:
            raise ValueError("invalid single-store learning configuration")
        if not 0 <= self.detector_threshold <= 1 or self.reservoir_size < 1:
            raise ValueError("invalid detector or reservoir configuration")


@dataclass(frozen=True)
class FrozenQualificationConfig:
    qualification_seed_digest: str
    selected: SingleStoreConfig
    search_trials: int
    selection_digest: str

    @classmethod
    def freeze(
        cls,
        qualification_seed_digest: str,
        selected: SingleStoreConfig,
        search_trials: int = 1,
    ) -> "FrozenQualificationConfig":
        if len(qualification_seed_digest) != 64 or search_trials <= 0:
            raise ValueError("qualification digest/search trials invalid")
        selection_digest = hashlib.sha256(
            repr((qualification_seed_digest, selected, search_trials)).encode()
        ).hexdigest()
        return cls(qualification_seed_digest, selected, search_trials, selection_digest)

    def for_result_seed(self, **changes: float) -> SingleStoreConfig:
        if changes:
            raise ValueError("frozen configuration cannot be retuned")
        return self.selected


class SingleStoreReplayStabilityArm:
    def __init__(
        self,
        config: SingleStoreConfig,
        budget: ArmBudget,
        qualification_search_trials: int = 1,
    ) -> None:
        if qualification_search_trials <= 0:
            raise ValueError("qualification search trials must be positive")
        self.config, self.budget = config, budget
        self.qualification_search_trials = qualification_search_trials
        self._events: list[FeedbackEvent] = []
        self._event_digests: set[str] = set()
        self._tombstones: set[str] = set()
        self._reservoir: list[FeedbackEvent] = []
        self._seen = 0
        self._values: dict[tuple[tuple[str, str], ...], dict[str, float]] = {}
        self._anchors: dict[tuple[tuple[str, str], ...], dict[str, float]] = {}
        self._importance: dict[tuple[tuple[str, str], ...], dict[str, int]] = {}

    @classmethod
    def from_frozen(
        cls, frozen: FrozenQualificationConfig, budget: ArmBudget
    ) -> "SingleStoreReplayStabilityArm":
        return cls(frozen.selected, budget, frozen.search_trials)

    def act(self, observation: RawObservation) -> str:
        values = self._values.get(_key(observation), {})
        return max(
            observation.authorized_actions,
            key=lambda action: (
                values.get(action, 0.0),
                -observation.authorized_actions.index(action),
            ),
        )

    def observe(self, feedback: FeedbackEvent) -> None:
        if feedback.event_digest in self._tombstones:
            raise ValueError("invalidated feedback digest cannot be consumed")
        if feedback.event_digest in self._event_digests:
            raise ValueError("duplicate feedback digest")
        self._events.append(feedback)
        self._event_digests.add(feedback.event_digest)
        self._learn(feedback, charge=True, include_replay=True)
        self._reservoir_add(feedback)

    def _update_value(self, feedback: FeedbackEvent, *, charge: bool) -> None:
        key = _key(feedback.observation)
        values = self._values.setdefault(key, {})
        anchors = self._anchors.setdefault(key, {})
        importance = self._importance.setdefault(key, {})
        old = values.get(feedback.action, 0.0)
        anchors.setdefault(feedback.action, old)
        previous_importance = importance.get(feedback.action, 0)
        importance[feedback.action] = previous_importance + 1
        learned = old + self.config.learning_rate * (feedback.reward - old)
        weight = importance[feedback.action] / (importance[feedback.action] + 1)
        penalty = self.config.stability * weight
        values[feedback.action] = (1 - penalty) * learned + penalty * anchors[
            feedback.action
        ]
        if feedback.reward >= 0.5:
            anchors[feedback.action] = (
                anchors[feedback.action] * previous_importance + values[feedback.action]
            ) / (previous_importance + 1)

    def _learn(
        self, feedback: FeedbackEvent, *, charge: bool, include_replay: bool
    ) -> None:
        for _ in range(self.budget.max_updates_per_feedback):
            self._update_value(feedback, charge=charge)
        if not include_replay or not self._reservoir:
            return
        ranked = sorted(
            self._reservoir,
            key=lambda event: hashlib.sha256(
                (feedback.event_digest + event.event_digest).encode()
            ).digest(),
        )
        for replay in ranked[: self.budget.max_replays_per_feedback]:
            self._replay_value(replay)

    def _replay_value(self, feedback: FeedbackEvent) -> None:
        self._update_value(feedback, charge=False)

    def _reservoir_add(self, feedback: FeedbackEvent) -> None:
        self._seen += 1
        if len(self._reservoir) < self.config.reservoir_size:
            self._reservoir.append(feedback)
            return
        slot = (
            int.from_bytes(
                hashlib.sha256(feedback.event_digest.encode()).digest()[:8], "big"
            )
            % self._seen
        )
        if slot < self.config.reservoir_size:
            self._reservoir[slot] = feedback

    def correct(self, correction: CorrectionEvent) -> None:
        digest = correction.invalidated_event_digest
        self._tombstones.add(digest)
        self._events = [event for event in self._events if event.event_digest != digest]
        self._event_digests.discard(digest)
        self._rebuild()

    def _rebuild(self) -> None:
        valid = tuple(self._events)
        self._values = {}
        self._anchors = {}
        self._importance = {}
        self._reservoir = []
        self._seen = 0
        for event in valid:
            self._rebuild_event(event)
            self._reservoir_add(event)

    def _rebuild_event(self, event: FeedbackEvent) -> None:
        self._learn(event, charge=True, include_replay=True)

    def decision_state(self) -> str:
        canonical = [
            (list(key), sorted(values.items()))
            for key, values in sorted(self._values.items())
        ]
        return hashlib.sha256(
            json.dumps(canonical, separators=(",", ":")).encode()
        ).hexdigest()

    def state_bytes(self) -> int:
        return len(
            repr(
                (self._values, self._anchors, self._importance, self._tombstones)
            ).encode()
        )

    @property
    def reservoir_event_digests(self) -> tuple[str, ...]:
        return tuple(event.event_digest for event in self._reservoir)


class ResetOnChangeArm(SingleStoreReplayStabilityArm):
    def observe(self, feedback: FeedbackEvent) -> None:
        predicted = self._values.get(_key(feedback.observation), {}).get(
            feedback.action, 0.0
        )
        if abs(feedback.reward - predicted) > self.config.detector_threshold:
            self._values = {}
            self._anchors = {}
            self._importance = {}
        super().observe(feedback)


class RecencyArm(SingleStoreReplayStabilityArm):
    def observe(self, feedback: FeedbackEvent) -> None:
        super().observe(feedback)
        if len(self._events) > self.config.reservoir_size:
            self._events = self._events[-self.config.reservoir_size :]
            self._event_digests = {event.event_digest for event in self._events}
            self._rebuild()


class StaticArm(SingleStoreReplayStabilityArm):
    def observe(self, feedback: FeedbackEvent) -> None:
        if len(self._events) < 8:
            super().observe(feedback)


class WSLSDiagnosticArm(SingleStoreReplayStabilityArm):
    def act(self, observation: RawObservation) -> str:
        relevant = [
            event
            for event in reversed(self._events)
            if event.observation.features == observation.features
        ]
        if not relevant or relevant[0].reward > 0:
            return relevant[0].action if relevant else observation.authorized_actions[0]
        index = observation.authorized_actions.index(relevant[0].action)
        return observation.authorized_actions[
            (index + 1) % len(observation.authorized_actions)
        ]


def make_non_oracle_arm(name: str, budget: ArmBudget):
    if name == "oracle":
        raise ValueError("oracle is evaluator-only")
    configs = {
        "single-store": SingleStoreConfig(),
        "reset": SingleStoreConfig(learning_rate=1.0, stability=0.0),
        "recency": SingleStoreConfig(
            learning_rate=0.8, stability=0.0, reservoir_size=16
        ),
        "static": SingleStoreConfig(learning_rate=0.2, stability=0.8),
        "wsls": SingleStoreConfig(learning_rate=1.0, stability=0.0),
    }
    classes = {
        "reset": ResetOnChangeArm,
        "recency": RecencyArm,
        "static": StaticArm,
        "wsls": WSLSDiagnosticArm,
    }
    if name not in configs:
        raise ValueError(f"unknown arm: {name}")
    return classes.get(name, SingleStoreReplayStabilityArm)(configs[name], budget)
