from __future__ import annotations

from .baselines import SingleStoreConfig, SingleStoreReplayStabilityArm
from .contracts import ArmBudget, CorrectionEvent, FeedbackEvent


class DualStoreRetentionArm(SingleStoreReplayStabilityArm):
    def __init__(self, budget: ArmBudget) -> None:
        super().__init__(SingleStoreConfig(learning_rate=0.7, stability=0.35), budget)
        self._slow: dict[tuple[tuple[str, str], ...], dict[str, float]] = {}

    def observe(self, feedback: FeedbackEvent) -> None:
        super().observe(feedback)
        key = feedback.observation.features
        self._slow[key] = dict(self._values[key])
        self._ledger.copies += 1

    def correct(self, correction: CorrectionEvent) -> None:
        super().correct(correction)
        self._slow = {key: dict(values) for key, values in self._values.items()}
