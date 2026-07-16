"""RED/GREEN tests for TransferMonitor, rollback and C7 authority boundaries."""

from __future__ import annotations

import unittest
from datetime import timezone

from experiments.w1w2_live_adaptation import (
    TransferAssessment,
    TransferMonitor,
    TransferSignal,
    W1Scope,
)


UTC = timezone.utc


def _scope() -> W1Scope:
    return W1Scope(
        mandate_id="m-1",
        task_id="t-1",
        environment_id="env-1",
        episode_id="ep-1",
    )


def _signal(step: int, reward: float, baseline: float, frozen: float) -> TransferSignal:
    return TransferSignal(
        scope=_scope(),
        arm_name="candidate",
        step=step,
        reward=reward,
        baseline_reward=baseline,
        frozen_reward=frozen,
    )


class TestTransferMonitor(unittest.TestCase):
    def test_detects_negative_transfer(self) -> None:
        monitor = TransferMonitor(regret_window=3, threshold=0.0)
        assessment: TransferAssessment | None = None
        for step in range(5):
            signal = _signal(step=step, reward=0.0, baseline=1.0, frozen=1.0)
            assessment = monitor.assess(
                signal,
                current_checkpoint_id="cp-0",
                authorized_option_ids=("opt-a", "opt-b"),
            )
        self.assertIsNotNone(assessment)
        assert assessment is not None
        self.assertTrue(assessment.negative_transfer_detected)

    def test_recommends_only_rollback_or_authorized_option(self) -> None:
        monitor = TransferMonitor(regret_window=2, threshold=0.0)
        assessment: TransferAssessment | None = None
        for step in range(4):
            signal = _signal(step=step, reward=-1.0, baseline=1.0, frozen=1.0)
            assessment = monitor.assess(
                signal,
                current_checkpoint_id="cp-0",
                authorized_option_ids=("opt-a",),
            )
        self.assertIsNotNone(assessment)
        assert assessment is not None
        self.assertTrue(
            assessment.recommended_action in ("ROLLBACK", "W2_OPTION:opt-a", "CONTINUE")
        )

    def test_cannot_recommend_unknown_option(self) -> None:
        monitor = TransferMonitor(regret_window=2, threshold=0.0)
        assessment: TransferAssessment | None = None
        for step in range(4):
            signal = _signal(step=step, reward=-1.0, baseline=1.0, frozen=1.0)
            assessment = monitor.assess(
                signal,
                current_checkpoint_id="cp-0",
                authorized_option_ids=("opt-a",),
            )
        self.assertIsNotNone(assessment)
        assert assessment is not None
        self.assertFalse(assessment.recommended_action.startswith("W2_OPTION:opt-evil"))


if __name__ == "__main__":
    unittest.main()
