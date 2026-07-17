from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RawObservation:
    features: tuple[tuple[str, str], ...]
    authorized_actions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.features or not self.authorized_actions:
            raise ValueError("closed observation requires features and actions")
        if len(set(self.authorized_actions)) != len(self.authorized_actions):
            raise ValueError("authorized actions must be unique")
        if any(not key or not value for key, value in self.features):
            raise ValueError("features must be non-empty opaque pairs")

    def to_dict(self) -> dict[str, object]:
        return {
            "features": [list(item) for item in self.features],
            "authorized_actions": list(self.authorized_actions),
        }


@dataclass(frozen=True)
class FeedbackEvent:
    event_digest: str
    observation: RawObservation
    action: str
    reward: float

    def __post_init__(self) -> None:
        if (
            not self.event_digest
            or self.action not in self.observation.authorized_actions
        ):
            raise ValueError("invalid feedback")
        if not math.isfinite(self.reward) or not 0.0 <= self.reward <= 1.0:
            raise ValueError("feedback reward must be finite in [0,1]")


@dataclass(frozen=True)
class CorrectionEvent:
    invalidated_event_digest: str

    def __post_init__(self) -> None:
        if not self.invalidated_event_digest:
            raise ValueError("correction digest is required")


@dataclass(frozen=True)
class CorrectionReceipt:
    invalidated_event_digest: str
    delivered_turn: int
    original_feedback_turn: int
    arm_state_digest: str


@dataclass(frozen=True)
class FeedbackReceipt:
    event_digest: str
    action_turn: int
    delivered_turn: int
    delivered_reward: float
    corrupted: bool


@dataclass(frozen=True)
class ArmBudget:
    max_updates_per_feedback: int
    max_replays_per_feedback: int
    max_copies_per_feedback: int = 4
    max_comparisons_per_feedback: int = 32
    max_rebuilds: int = 256
    max_search_trials: int = 16

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in (
                self.max_updates_per_feedback,
                self.max_replays_per_feedback,
                self.max_copies_per_feedback,
                self.max_comparisons_per_feedback,
                self.max_rebuilds,
                self.max_search_trials,
            )
        ):
            raise ValueError("budget limits must be positive integers")


@dataclass(frozen=True)
class CostRecord:
    updates: int = 0
    replays: int = 0
    comparisons: int = 0
    copies: int = 0
    rebuilds: int = 0
    retrievals: int = 0
    search_trials: int = 0
    stored_events: int = 0
    state_bytes: int = 0

    @property
    def charged_work(self) -> int:
        return (
            self.updates
            + self.replays
            + self.comparisons
            + self.copies
            + self.rebuilds
            + self.retrievals
            + self.search_trials
        )


class OperationMeter:
    """Executor-owned mutable meter; arms receive only its charging surface."""

    def __init__(self, budget: ArmBudget) -> None:
        self.budget = budget
        self._counts = {
            "updates": 0,
            "replays": 0,
            "comparisons": 0,
            "copies": 0,
            "rebuilds": 0,
            "retrievals": 0,
            "search_trials": 0,
        }

    def _charge(self, field: str, count: int = 1) -> None:
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("operation charge must be a non-negative integer")
        self._counts[field] += count
        if field == "rebuilds" and self._counts[field] > self.budget.max_rebuilds:
            raise RuntimeError("rebuild budget exceeded")
        if (
            field == "search_trials"
            and self._counts[field] > self.budget.max_search_trials
        ):
            raise RuntimeError("search budget exceeded")

    def update(self, count: int = 1) -> None:
        self._charge("updates", count)

    def replay(self, count: int = 1) -> None:
        self._charge("replays", count)

    def compare(self, count: int = 1) -> None:
        self._charge("comparisons", count)

    def copy(self, count: int = 1) -> None:
        self._charge("copies", count)

    def rebuild(self, count: int = 1) -> None:
        self._charge("rebuilds", count)

    def retrieve(self, count: int = 1) -> None:
        self._charge("retrievals", count)

    def search(self, count: int = 1) -> None:
        self._charge("search_trials", count)

    def snapshot(self, *, stored_events: int = 0, state_bytes: int = 0) -> CostRecord:
        return CostRecord(
            **self._counts, stored_events=stored_events, state_bytes=state_bytes
        )

    def delta(
        self, before: CostRecord, *, stored_events: int = 0, state_bytes: int = 0
    ) -> CostRecord:
        after = self.snapshot(stored_events=stored_events, state_bytes=state_bytes)
        return CostRecord(
            updates=after.updates - before.updates,
            replays=after.replays - before.replays,
            comparisons=after.comparisons - before.comparisons,
            copies=after.copies - before.copies,
            rebuilds=after.rebuilds - before.rebuilds,
            retrievals=after.retrievals - before.retrievals,
            search_trials=after.search_trials - before.search_trials,
            stored_events=after.stored_events,
            state_bytes=after.state_bytes,
        )


def stable_digest(label: str, value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(label.encode() + b"\x00" + encoded).hexdigest()
