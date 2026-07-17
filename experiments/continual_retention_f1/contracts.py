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
class OperationReceipt:
    sequence: int
    kind: str
    turn: int
    event_digest: str
    previous_digest: str
    receipt_digest: str


@dataclass(frozen=True)
class ArmBudget:
    max_updates_per_feedback: int
    max_replays_per_feedback: int
    max_copies_per_feedback: int = 4
    max_retrievals_per_feedback: int = 4
    max_comparisons_per_feedback: int = 32
    max_rebuilds: int = 256
    max_search_trials: int = 16
    max_stored_events: int = 256
    max_state_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in (
                self.max_updates_per_feedback,
                self.max_replays_per_feedback,
                self.max_copies_per_feedback,
                self.max_retrievals_per_feedback,
                self.max_comparisons_per_feedback,
                self.max_rebuilds,
                self.max_search_trials,
                self.max_stored_events,
                self.max_state_bytes,
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


def stable_digest(label: str, value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(label.encode() + b"\x00" + encoded).hexdigest()
