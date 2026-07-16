"""Wave A tests for TransferMonitor and C7 boundaries."""

from __future__ import annotations

import unittest

from experiments.w1w2_live_adaptation import (
    C7Controller,
    C7Snapshot,
    ScorerReceipt,
    TransferAssessment,
    TransferMonitor,
    W1Scope,
)


def _scope() -> W1Scope:
    return W1Scope(
        mandate_id="m-1",
        task_id="t-1",
        environment_id="env-1",
        episode_id="ep-1",
    )


def _receipt(step: int, reward: float, baseline: float, oracle: float) -> ScorerReceipt:
    return ScorerReceipt(
        receipt_id=f"sr-{step}",
        scope=_scope(),
        arm_name="candidate",
        step=step,
        reward=reward,
        baseline_reward=baseline,
        oracle_reward=oracle,
    )


class TestC7Controller(unittest.TestCase):
    def test_candidate_snapshot_is_immutable(self) -> None:
        controller = C7Controller(correction_id="c7-1", scope_id="s-1")
        snapshot = controller.snapshot
        self.assertIsInstance(snapshot, C7Snapshot)
        with self.assertRaises(Exception):
            snapshot.halted = True  # type: ignore[misc]

    def test_candidate_cannot_call_halt(self) -> None:
        snapshot = C7Controller(correction_id="c7-1", scope_id="s-1").snapshot
        self.assertFalse(hasattr(snapshot, "halt"))

    def test_halt_advances_epoch(self) -> None:
        controller = C7Controller(correction_id="c7-1", scope_id="s-1")
        self.assertEqual(controller.snapshot.epoch, 0)
        controller.halt("test")
        self.assertTrue(controller.snapshot.halted)
        self.assertEqual(controller.snapshot.epoch, 1)


class TestTransferMonitor(unittest.TestCase):
    def test_detects_negative_transfer_from_scorer_receipts(self) -> None:
        monitor = TransferMonitor(regret_window=3, threshold=0.0, gate_digest="gd-1")
        assessment: TransferAssessment | None = None
        for step in range(5):
            receipt = _receipt(step=step, reward=0.0, baseline=1.0, oracle=1.0)
            assessment = monitor.assess(
                receipt,
                current_checkpoint_id="cp-0",
                authorized_option_ids=("opt-a", "opt-b"),
            )
        self.assertIsNotNone(assessment)
        assert assessment is not None
        self.assertTrue(assessment.negative_transfer_detected)

    def test_recommends_only_rollback_or_authorized_option(self) -> None:
        monitor = TransferMonitor(regret_window=2, threshold=0.0, gate_digest="gd-1")
        assessment: TransferAssessment | None = None
        for step in range(4):
            receipt = _receipt(step=step, reward=-1.0, baseline=1.0, oracle=1.0)
            assessment = monitor.assess(
                receipt,
                current_checkpoint_id="cp-0",
                authorized_option_ids=("opt-a",),
            )
        self.assertIsNotNone(assessment)
        assert assessment is not None
        self.assertIn(
            assessment.recommended_action,
            ("ROLLBACK", "W2_OPTION:opt-a", "CONTINUE"),
        )

    def test_cannot_recommend_unknown_option(self) -> None:
        monitor = TransferMonitor(regret_window=2, threshold=0.0, gate_digest="gd-1")
        assessment: TransferAssessment | None = None
        for step in range(4):
            receipt = _receipt(step=step, reward=-1.0, baseline=1.0, oracle=1.0)
            assessment = monitor.assess(
                receipt,
                current_checkpoint_id="cp-0",
                authorized_option_ids=("opt-a",),
            )
        self.assertIsNotNone(assessment)
        assert assessment is not None
        self.assertFalse(assessment.recommended_action.startswith("W2_OPTION:opt-evil"))


if __name__ == "__main__":
    unittest.main()
