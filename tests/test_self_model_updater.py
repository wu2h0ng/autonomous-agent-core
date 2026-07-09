"""Contract tests for E6 AgentSelfModelUpdater — runtime self-model calibration.

Hard Boundary #17: tests written before implementation; must fail if the
updater returns constant deltas or ignores outcomes.
"""

from __future__ import annotations

import unittest

from aac.self_model_updater import (
    AgentSelfModelUpdater,
    ConfidenceTracker,
    ToolReliability,
)


class ConfidenceCalibration(unittest.TestCase):
    def test_correct_outcome_lowers_threshold_when_overconfident(self):
        updater = AgentSelfModelUpdater(n_actions=4)
        updater.confidence_trackers[1] = ConfidenceTracker(
            ewma_error=0.0, count=10, last_calibrated_threshold=0.9
        )
        threshold = updater.calibrate_confidence(1, predicted_confidence=0.95, outcome_correct=True)
        self.assertLessEqual(threshold, 0.9)

    def test_incorrect_outcome_raises_threshold_when_underconfident(self):
        updater = AgentSelfModelUpdater(n_actions=4)
        updater.confidence_trackers[1] = ConfidenceTracker(
            ewma_error=0.0, count=10, last_calibrated_threshold=0.3
        )
        threshold = updater.calibrate_confidence(1, predicted_confidence=0.3, outcome_correct=False)
        self.assertGreaterEqual(threshold, 0.3)

    def test_threshold_stays_in_bounds(self):
        updater = AgentSelfModelUpdater(n_actions=4, min_threshold=0.1, max_threshold=0.9)
        for _ in range(100):
            updater.calibrate_confidence(1, predicted_confidence=0.5, outcome_correct=False)
        new_t = updater.calibrate_confidence(1, predicted_confidence=0.5, outcome_correct=False)
        self.assertGreaterEqual(new_t, 0.1)
        self.assertLessEqual(new_t, 0.9)

    def test_returns_different_thresholds_for_different_tiers(self):
        updater = AgentSelfModelUpdater(n_actions=4)
        t1 = updater.calibrate_confidence(0, 0.9, True)
        t2 = updater.calibrate_confidence(4, 0.5, False)
        self.assertNotAlmostEqual(t1, t2)


class ToolReliability(unittest.TestCase):
    def test_reliability_rises_with_success(self):
        updater = AgentSelfModelUpdater(n_actions=4, reliability_lr=0.3)
        for _ in range(10):
            r = updater.update_tool_reliability("apply_lever", success=True)
        self.assertGreater(r, 0.5)

    def test_reliability_falls_with_failure(self):
        updater = AgentSelfModelUpdater(n_actions=4, reliability_lr=0.3)
        for _ in range(10):
            r = updater.update_tool_reliability("apply_lever", success=False)
        self.assertLess(r, 0.5)

    def test_unknown_tool_returns_default(self):
        updater = AgentSelfModelUpdater(n_actions=4)
        self.assertEqual(updater.get_tool_reliability("unknown"), 0.5)

    def test_multiple_tools_independent(self):
        updater = AgentSelfModelUpdater(n_actions=4, reliability_lr=0.5)
        updater.update_tool_reliability("tool_a", success=True)
        updater.update_tool_reliability("tool_a", success=True)
        updater.update_tool_reliability("tool_b", success=False)
        updater.update_tool_reliability("tool_b", success=False)
        self.assertGreater(updater.get_tool_reliability("tool_a"),
                           updater.get_tool_reliability("tool_b"))


class EvidenceAdjustment(unittest.TestCase):
    def test_raises_evidence_when_consistently_bad(self):
        updater = AgentSelfModelUpdater(n_actions=4, evidence_lr=0.1)
        for _ in range(30):
            updater.adjust_evidence_requirement(2, evidence_count=1, outcome_quality=-0.5)
        delta = updater.adjust_evidence_requirement(2, evidence_count=1, outcome_quality=-0.5)
        self.assertEqual(delta, 1)

    def test_lowers_evidence_when_consistently_good(self):
        updater = AgentSelfModelUpdater(n_actions=4, evidence_lr=0.1)
        for _ in range(30):
            updater.adjust_evidence_requirement(2, evidence_count=3, outcome_quality=0.5)
        delta = updater.adjust_evidence_requirement(2, evidence_count=3, outcome_quality=0.5)
        self.assertEqual(delta, -1)


class AfterActionFullUpdate(unittest.TestCase):
    def test_returns_all_required_keys(self):
        updater = AgentSelfModelUpdater(n_actions=4)
        result = updater.after_action(
            action="apply_lever", risk_tier=1, predicted_confidence=0.8,
            evidence_count=2, outcome=10.0, outcome_baseline=5.0,
        )
        self.assertIn("confidence_thresholds", result)
        self.assertIn("evidence_requirements", result)
        self.assertIn("tool_reliability", result)

    def test_different_outcomes_produce_different_deltas(self):
        updater = AgentSelfModelUpdater(n_actions=4)
        r1 = updater.after_action("a", 1, 0.8, 2, 10.0, 5.0)
        r2 = updater.after_action("a", 1, 0.8, 2, -5.0, 5.0)
        self.assertNotEqual(
            r1["confidence_thresholds"].get(1),
            r2["confidence_thresholds"].get(1),
        )

    def test_increments_update_count(self):
        updater = AgentSelfModelUpdater(n_actions=4)
        self.assertEqual(updater.total_updates, 0)
        updater.after_action("a", 1, 0.8, 2, 10.0, 5.0)
        self.assertEqual(updater.total_updates, 1)
        updater.after_action("b", 2, 0.5, 1, 3.0, 5.0)
        self.assertEqual(updater.total_updates, 2)


class NotAConstant(unittest.TestCase):
    """Guard: the updater must produce different outputs for different inputs."""

    def test_get_confidence_threshold_returns_none_for_unknown_tier(self):
        updater = AgentSelfModelUpdater(n_actions=4)
        self.assertIsNone(updater.get_confidence_threshold(99))

    def test_confidence_threshold_changes_after_multiple_updates(self):
        updater = AgentSelfModelUpdater(n_actions=4)
        updater.calibrate_confidence(1, 0.5, False)
        t1 = updater.get_confidence_threshold(1)
        for _ in range(20):
            updater.calibrate_confidence(1, 0.5, False)
        t2 = updater.get_confidence_threshold(1)
        self.assertIsNotNone(t1)
        self.assertIsNotNone(t2)
        self.assertNotEqual(t1, t2)


class StateRestoreRoundtrip(unittest.TestCase):
    def test_roundtrip(self):
        updater = AgentSelfModelUpdater(n_actions=4)
        updater.after_action("a", 1, 0.8, 2, 10.0, 5.0)
        updater.after_action("b", 2, 0.5, 1, 3.0, 5.0)
        saved = updater.state()

        restored = AgentSelfModelUpdater(n_actions=4)
        restored.restore(saved)
        self.assertEqual(restored.total_updates, updater.total_updates)
        self.assertEqual(
            len(restored.tool_reliabilities),
            len(updater.tool_reliabilities),
        )


if __name__ == "__main__":
    unittest.main()
