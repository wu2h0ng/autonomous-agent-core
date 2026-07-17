from __future__ import annotations

import hashlib
import json

from .baselines import SingleStoreConfig, SingleStoreReplayStabilityArm, _key
from .contracts import ArmBudget, CorrectionEvent, FeedbackEvent, RawObservation


class DualStoreRetentionArm(SingleStoreReplayStabilityArm):
    """Fast values plus versioned retained prototypes consumed on public error."""

    def __init__(
        self,
        budget: ArmBudget,
        qualification_search_trials: int = 1,
        *,
        slow_enabled: bool = True,
    ) -> None:
        super().__init__(
            SingleStoreConfig(learning_rate=0.7, stability=0.0),
            budget,
            qualification_search_trials,
        )
        self._slow: dict[tuple[tuple[str, str], ...], list[dict[str, float]]] = {}
        self._retrieval_count = 0
        self._slow_enabled = slow_enabled
        self._slow_override: dict[tuple[tuple[str, str], ...], str] = {}

    def act(self, observation: RawObservation) -> str:
        key = _key(observation)
        override = self._slow_override.pop(key, None)
        if override in observation.authorized_actions:
            return override
        if self._slow_enabled and key not in self._values and self._slow.get(key):
            self._retrieve_prototype(key)
        return super().act(observation)

    def observe(self, feedback: FeedbackEvent) -> None:
        key = _key(feedback.observation)
        current = self._values.get(key)
        predicted = 0.0 if current is None else current.get(feedback.action, 0.0)
        if current and feedback.reward + self.config.detector_threshold < predicted:
            if self._slow_enabled:
                self._copy_prototype(key, current)
            self._values.pop(key, None)
            if self._slow_enabled:
                self._retrieve_prototype(key)
                retained = self._slow[key][-1]
                alternatives = [
                    action
                    for action in feedback.observation.authorized_actions
                    if action != feedback.action
                ]
                if alternatives:
                    self._slow_override[key] = max(
                        alternatives,
                        key=lambda action: (
                            retained.get(action, 0.0),
                            -feedback.observation.authorized_actions.index(action),
                        ),
                    )
        super().observe(feedback)
        # Publicly successful updates are the only source of retained prototypes.
        # A later public prediction error can therefore recover an older successful
        # policy instead of falling back to the authorization-order default.
        if self._slow_enabled and feedback.reward >= 0.5:
            self._copy_prototype(key, self._values[key])

    def _copy_prototype(self, key, current) -> None:
        versions = self._slow.setdefault(key, [])
        versions.append(dict(current))
        del versions[:-8]

    def _retrieve_prototype(self, key) -> None:
        self._values[key] = dict(self._slow[key][0])
        self._retrieval_count += 1

    def correct(self, correction: CorrectionEvent) -> None:
        super().correct(correction)
        self._slow = (
            {key: [dict(values)] for key, values in self._values.items()}
            if self._slow_enabled
            else {}
        )
        self._slow_override = {}

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
            "override": [
                (list(key), action)
                for key, action in sorted(self._slow_override.items())
            ],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def state_bytes(self) -> int:
        return super().state_bytes() + len(repr(self._slow).encode())
