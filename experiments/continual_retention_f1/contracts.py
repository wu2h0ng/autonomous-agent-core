from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RawObservation:
    features: tuple[tuple[str, str], ...]
    authorized_actions: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not self.features
            or not self.authorized_actions
            or len(set(self.authorized_actions)) != len(self.authorized_actions)
        ):
            raise ValueError("closed observation requires features and unique actions")

    def to_dict(self) -> dict[str, object]:
        return {
            "features": [list(x) for x in self.features],
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


@dataclass(frozen=True)
class CorrectionEvent:
    invalidated_event_digest: str


@dataclass(frozen=True)
class ArmBudget:
    max_updates_per_feedback: int
    max_replays_per_feedback: int

    def __post_init__(self) -> None:
        if self.max_updates_per_feedback <= 0 or self.max_replays_per_feedback <= 0:
            raise ValueError("budget limits must be positive")


@dataclass(frozen=True)
class CostRecord:
    updates: int
    replays: int
    comparisons: int
    copies: int
    state_bytes: int


class OperationLedger:
    def __init__(self) -> None:
        self.updates = self.replays = self.comparisons = self.copies = 0

    def snapshot(self, state_bytes: int = 0) -> CostRecord:
        return CostRecord(
            self.updates, self.replays, self.comparisons, self.copies, state_bytes
        )
