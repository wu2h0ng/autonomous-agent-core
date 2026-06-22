"""Tests for OutcomeJudge (T-P3.3, ADR-0014 D2)."""

from __future__ import annotations

import unittest

from aac.outcome_judge import OutcomeJudge


class TestOutcomeJudge(unittest.TestCase):
    def test_success_when_beating_random_baseline(self) -> None:
        judge = OutcomeJudge()
        judge.begin()
        judge.observe(realized_regret=0.5, baseline_regret=2.0)
        v = judge.verdict()
        self.assertEqual(v.outcome, "success")
        self.assertEqual((v.mean_realized, v.mean_baseline, v.steps), (0.5, 2.0, 1))

    def test_failure_when_not_beating_baseline(self) -> None:
        judge = OutcomeJudge()
        judge.begin()
        judge.observe(realized_regret=2.0, baseline_regret=2.0)  # tie -> not strictly <
        self.assertEqual(judge.verdict().outcome, "failure")

    def test_no_evidence_is_conservative_failure(self) -> None:
        judge = OutcomeJudge()
        judge.begin()
        v = judge.verdict()
        self.assertEqual(v.outcome, "failure")
        self.assertEqual(v.steps, 0)

    def test_means_over_multiple_steps(self) -> None:
        judge = OutcomeJudge()
        judge.begin()
        judge.observe(0.0, 2.0)
        judge.observe(3.0, 2.0)  # mean realized 1.5 < mean baseline 2.0
        v = judge.verdict()
        self.assertEqual(v.outcome, "success")
        self.assertEqual(v.mean_realized, 1.5)

    def test_begin_resets_stream(self) -> None:
        judge = OutcomeJudge()
        judge.begin()
        judge.observe(0.0, 2.0)
        judge.begin()
        self.assertEqual(judge.verdict().steps, 0)

    def test_beta_tightens_the_bar(self) -> None:
        # realized 1.5, baseline 2.0: passes at beta=1.0, fails at beta=0.5.
        self.assertEqual(_one(OutcomeJudge(beta=1.0), 1.5, 2.0), "success")
        self.assertEqual(_one(OutcomeJudge(beta=0.5), 1.5, 2.0), "failure")

    def test_beta_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            OutcomeJudge(beta=0.0)


def _one(judge: OutcomeJudge, realized: float, baseline: float) -> str:
    judge.begin()
    judge.observe(realized, baseline)
    return judge.verdict().outcome


if __name__ == "__main__":
    unittest.main()
