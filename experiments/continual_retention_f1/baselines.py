from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .contracts import (
    ArmBudget,
    CorrectionEvent,
    CostRecord,
    FeedbackEvent,
    OperationLedger,
    RawObservation,
)


def _key(obs: RawObservation) -> tuple[tuple[str, str], ...]:
    return obs.features


@dataclass(frozen=True)
class SingleStoreConfig:
    learning_rate: float = 0.5
    stability: float = 0.25
    detector_threshold: float = 0.4


@dataclass(frozen=True)
class FrozenQualificationConfig:
    qualification_seed_digest: str
    selected: SingleStoreConfig

    @classmethod
    def freeze(
        cls, qualification_seed_digest: str, selected: SingleStoreConfig
    ) -> "FrozenQualificationConfig":
        if len(qualification_seed_digest) != 64:
            raise ValueError("qualification digest must be sha256")
        return cls(qualification_seed_digest, selected)

    def for_result_seed(self, **changes: float) -> SingleStoreConfig:
        if changes:
            raise ValueError("frozen configuration cannot be retuned")
        return self.selected


class SingleStoreReplayStabilityArm:
    def __init__(self, config: SingleStoreConfig, budget: ArmBudget) -> None:
        self.config, self.budget = config, budget
        self._events: list[FeedbackEvent] = []
        self._values: dict[tuple[tuple[str, str], ...], dict[str, float]] = {}
        self._anchors: dict[tuple[tuple[str, str], ...], dict[str, float]] = {}
        self._ledger = OperationLedger()

    def act(self, observation: RawObservation) -> str:
        values = self._values.get(_key(observation), {})
        return max(
            observation.authorized_actions, key=lambda action: values.get(action, 0.0)
        )

    def observe(self, feedback: FeedbackEvent) -> None:
        self._events.append(feedback)
        self._apply(feedback, charge=True)

    def _apply(self, feedback: FeedbackEvent, charge: bool) -> None:
        self._update_value(feedback, self.budget.max_updates_per_feedback)
        replay_pool = (
            self._events[:-1]
            if self._events and self._events[-1] is feedback
            else self._events
        )
        for replay in replay_pool[-self.budget.max_replays_per_feedback :]:
            self._update_value(replay, 1)
        if charge:
            self._ledger.updates += self.budget.max_updates_per_feedback
            self._ledger.replays += self.budget.max_replays_per_feedback

    def _update_value(self, feedback: FeedbackEvent, repetitions: int) -> None:
        key = _key(feedback.observation)
        values = self._values.setdefault(key, {})
        anchors = self._anchors.setdefault(key, dict(values))
        for _ in range(repetitions):
            old = values.get(feedback.action, 0.0)
            learned = old + self.config.learning_rate * (feedback.reward - old)
            anchor = anchors.get(feedback.action, old)
            values[feedback.action] = (
                1 - self.config.stability
            ) * learned + self.config.stability * anchor

    def correct(self, correction: CorrectionEvent) -> None:
        self._events = [
            event
            for event in self._events
            if event.event_digest != correction.invalidated_event_digest
        ]
        self._values = {}
        self._anchors = {}
        for event in self._events:
            self._apply(event, charge=False)

    def decision_state(self) -> str:
        canonical = [
            (list(key), sorted(values.items()))
            for key, values in sorted(self._values.items())
        ]
        return hashlib.sha256(
            json.dumps(canonical, separators=(",", ":")).encode()
        ).hexdigest()

    def cost(self) -> CostRecord:
        return self._ledger.snapshot(len(repr(self._values).encode()))


class _ConfiguredArm(SingleStoreReplayStabilityArm):
    pass


class ResetOnChangeArm(_ConfiguredArm):
    def observe(self, feedback: FeedbackEvent) -> None:
        predicted = self._values.get(_key(feedback.observation), {}).get(
            feedback.action, 0.0
        )
        if abs(feedback.reward - predicted) > self.config.detector_threshold:
            self._events = []
            self._values = {}
            self._anchors = {}
        super().observe(feedback)


class RecencyArm(_ConfiguredArm):
    def observe(self, feedback: FeedbackEvent) -> None:
        super().observe(feedback)
        if len(self._events) > 16:
            self._events = self._events[-16:]
            self._values = {}
            self._anchors = {}
            for event in self._events:
                self._apply(event, charge=False)


class StaticArm(_ConfiguredArm):
    def observe(self, feedback: FeedbackEvent) -> None:
        if not self._events:
            super().observe(feedback)


class WSLSDiagnosticArm(_ConfiguredArm):
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
        "recency": SingleStoreConfig(learning_rate=0.8, stability=0.0),
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
