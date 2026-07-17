from __future__ import annotations

import hashlib
import json

from .baselines import SingleStoreConfig, SingleStoreReplayStabilityArm, _key
from .contracts import ArmBudget, CorrectionEvent, FeedbackEvent, RawObservation


class DualStoreRetentionArm(SingleStoreReplayStabilityArm):
    """Fast values plus versioned retained prototypes consumed on public error."""

    def __init__(self, budget: ArmBudget, qualification_search_trials: int = 1) -> None:
        super().__init__(
            SingleStoreConfig(learning_rate=0.7, stability=0.0),
            budget,
            qualification_search_trials,
        )
        self._slow: dict[tuple[tuple[str, str], ...], list[dict[str, float]]] = {}
        self._retrieval_count = 0

    def act(self, observation: RawObservation) -> str:
        key = _key(observation)
        if key not in self._values and self._slow.get(key):
            self._values[key] = dict(self._slow[key][-1])
            self._charge("retrieve")
            self._retrieval_count += 1
        return super().act(observation)

    def observe(self, feedback: FeedbackEvent) -> None:
        key = _key(feedback.observation)
        current = self._values.get(key)
        predicted = 0.0 if current is None else current.get(feedback.action, 0.0)
        self._charge("compare")
        if current and feedback.reward + self.config.detector_threshold < predicted:
            versions = self._slow.setdefault(key, [])
            versions.append(dict(current))
            self._charge("copy")
            # Oldest retained state is the return anchor; the fast store remains plastic.
            self._values[key] = dict(versions[0])
            self._charge("retrieve")
            self._retrieval_count += 1
        super().observe(feedback)

    def correct(self, correction: CorrectionEvent) -> None:
        super().correct(correction)
        self._slow = {key: [dict(values)] for key, values in self._values.items()}
        if self._slow:
            self._charge("copy", len(self._slow))

    def prototype_versions(self, observation: RawObservation) -> int:
        return len(self._slow.get(_key(observation), ()))

    @property
    def retrieval_count(self) -> int:
        return self._retrieval_count

    def decision_state(self) -> str:
        payload = {
            "fast": super().decision_state(),
            "slow": [
                (list(key), [sorted(version.items()) for version in versions])
                for key, versions in sorted(self._slow.items())
            ],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def state_bytes(self) -> int:
        return super().state_bytes() + len(repr(self._slow).encode())
