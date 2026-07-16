"""Wave A tests for TransferMonitor and C7 boundaries."""

from __future__ import annotations

import unittest

from experiments.w1w2_live_adaptation import (
    C7Controller,
    C7Snapshot,
    ScorerReceipt,
    ScorerReceiptBinding,
    SealedScorerOutcome,
    TrustedScorerPort,
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


class _TrustedScorer(TrustedScorerPort):
    def __init__(self) -> None:
        self._receipts: dict[str, ScorerReceipt] = {}
        self._consumed: set[str] = set()

    def score(self, binding: ScorerReceiptBinding, outcome: SealedScorerOutcome) -> str:
        receipt_id = f"sr-{binding.step}"
        self._receipts[receipt_id] = ScorerReceipt(
            receipt_id=receipt_id, binding=binding, outcome=outcome
        )
        return receipt_id

    def consume(self, receipt_id, expected):
        receipt = self._receipts.get(receipt_id)
        if (
            receipt_id in self._consumed
            or receipt is None
            or receipt.binding != expected
        ):
            return None
        self._consumed.add(receipt_id)
        return receipt


def _monitor(window: int, threshold: float) -> tuple[TransferMonitor, _TrustedScorer]:
    scorer = _TrustedScorer()
    return (
        TransferMonitor(
            regret_window=window,
            threshold=threshold,
            gate_digest="gd-1",
            run_id="run-1",
            scope=_scope(),
            arm_name="candidate",
            scorer_resolver=scorer,
        ),
        scorer,
    )


def _issue(
    scorer: _TrustedScorer, step: int, reward: float, baseline: float, oracle: float
) -> str:
    binding = ScorerReceiptBinding(
        run_id="run-1",
        scope=_scope(),
        arm_name="candidate",
        step=step,
        gate_digest="gd-1",
    )
    return scorer.score(
        binding,
        SealedScorerOutcome(
            reward=reward,
            frozen_reference_reward=baseline,
            oracle_reward=oracle,
        ),
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
    def test_sealed_outcome_rejects_ambiguous_baseline_reward_field(self) -> None:
        with self.assertRaises(Exception):
            SealedScorerOutcome(
                reward=1.0,
                baseline_reward=1.0,  # type: ignore[call-arg]
                oracle_reward=1.0,
            )

    def test_detects_negative_transfer_from_scorer_receipts(self) -> None:
        monitor, scorer = _monitor(3, 0.0)
        assessment: TransferAssessment | None = None
        for step in range(5):
            receipt_id = _issue(scorer, step=step, reward=0.0, baseline=1.0, oracle=1.0)
            assessment = monitor.assess(
                receipt_id,
                step,
                current_checkpoint_id="cp-0",
                authorized_option_ids=("opt-a", "opt-b"),
            )
        self.assertIsNotNone(assessment)
        assert assessment is not None
        self.assertTrue(assessment.negative_transfer_detected)

    def test_recommends_only_rollback_or_authorized_option(self) -> None:
        monitor, scorer = _monitor(2, 0.0)
        assessment: TransferAssessment | None = None
        for step in range(4):
            receipt_id = _issue(
                scorer, step=step, reward=-1.0, baseline=1.0, oracle=1.0
            )
            assessment = monitor.assess(
                receipt_id,
                step,
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
        monitor, scorer = _monitor(2, 0.0)
        assessment: TransferAssessment | None = None
        for step in range(4):
            receipt_id = _issue(
                scorer, step=step, reward=-1.0, baseline=1.0, oracle=1.0
            )
            assessment = monitor.assess(
                receipt_id,
                step,
                current_checkpoint_id="cp-0",
                authorized_option_ids=("opt-a",),
            )
        self.assertIsNotNone(assessment)
        assert assessment is not None
        self.assertFalse(assessment.recommended_action.startswith("W2_OPTION:opt-evil"))

    def test_replay_and_wrong_step_fail_closed(self) -> None:
        monitor, scorer = _monitor(2, 0.0)
        receipt_id = _issue(scorer, 0, 1.0, 1.0, 1.0)
        monitor.assess(receipt_id, 0, None, ("opt-a",))
        with self.assertRaises(ValueError):
            monitor.assess(receipt_id, 0, None, ("opt-a",))
        other_id = _issue(scorer, 1, 1.0, 1.0, 1.0)
        with self.assertRaises(ValueError):
            monitor.assess(other_id, 2, None, ("opt-a",))


if __name__ == "__main__":
    unittest.main()
