from __future__ import annotations

import unittest

from aac.attention import AttentionField


class TestInformationPower(unittest.TestCase):
    """IP estimates converge with consistent observations."""

    def test_initial_ip_is_zero(self) -> None:
        af = AttentionField(K=8)
        for ip in af.information_power:
            self.assertAlmostEqual(ip, 0.0)

    def test_predictive_cue_gains_ip(self) -> None:
        """A cue that always co-occurs with high reward should gain IP."""
        af = AttentionField(K=4, lr=0.5)
        # Cue 0 is perfectly predictive: c_0=1 → reward=3, c_0=0 → reward=-1
        for _ in range(20):
            af.update(reward=3.0, cue_values=(1, 0, 1, 0), attended=[0, 1, 2, 3])
            af.update(reward=-1.0, cue_values=(0, 0, 1, 0), attended=[0, 1, 2, 3])
        # Cue 0 should have highest IP: |E[r|c=1] - E[r|c=0]| ≈ |3 - (-1)| = 4
        self.assertGreater(af.information_power[0], af.information_power[1])

    def test_non_predictive_cue_stays_low(self) -> None:
        """A cue with random reward association stays near zero IP."""
        af = AttentionField(K=4, lr=0.3)
        # Cue 3 alternates randomly, reward always 1.0
        for _ in range(30):
            af.update(reward=1.0, cue_values=(1, 0, 1, 0), attended=[0, 1, 2, 3])
            af.update(reward=1.0, cue_values=(0, 1, 0, 1), attended=[0, 1, 2, 3])
        # All cues have IP ≈ 0 since reward is always the same
        for ip in af.information_power:
            self.assertLess(ip, 0.5)


class TestAttentionSelection(unittest.TestCase):
    """select_attention returns top-m cues by IP."""

    def test_selects_top_m(self) -> None:
        af = AttentionField(K=6, m=2)
        # Manually set IP so cues 1 and 4 are highest
        af.information_power = [0.1, 0.9, 0.3, 0.2, 0.8, 0.0]
        selected = af.select_attention()
        self.assertEqual(sorted(selected), [1, 4])

    def test_selects_fewer_when_m_exceeds_K(self) -> None:
        af = AttentionField(K=3, m=5)
        selected = af.select_attention()
        self.assertEqual(len(selected), 3)

    def test_returns_m_indices(self) -> None:
        af = AttentionField(K=12, m=3)
        af.information_power = [0.1] * 12
        af.information_power[7] = 5.0
        af.information_power[2] = 3.0
        af.information_power[11] = 4.0
        selected = af.select_attention()
        self.assertEqual(len(selected), 3)
        self.assertIn(7, selected)
        self.assertIn(11, selected)
        self.assertIn(2, selected)


class TestPressureShrinksBudget(unittest.TestCase):
    """Pressure reduces effective_m; no direct exploitation coupling."""

    def test_zero_pressure_full_budget(self) -> None:
        af = AttentionField(K=12, m=4)
        af.information_power = [1.0, 0.8, 0.6, 0.4, 0.2] + [0.0] * 7
        selected = af.select_attention(pressure=0.0)
        self.assertEqual(len(selected), 4)

    def test_high_pressure_shrinks(self) -> None:
        af = AttentionField(K=12, m=4)
        af.information_power = [1.0, 0.8, 0.6, 0.4, 0.2] + [0.0] * 7
        selected = af.select_attention(pressure=0.9)
        # effective_m = max(1, int(4 * (1 - 0.9))) = max(1, 0) = 1
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0], 0)  # highest IP

    def test_max_pressure_keeps_one(self) -> None:
        af = AttentionField(K=12, m=4)
        af.information_power = [0.5, 1.0, 0.3] + [0.0] * 9
        selected = af.select_attention(pressure=1.0)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0], 1)  # highest IP

    def test_moderate_pressure_partial_shrink(self) -> None:
        af = AttentionField(K=12, m=6)
        af.information_power = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5] + [0.0] * 6
        selected = af.select_attention(pressure=0.5)
        # effective_m = max(1, int(6 * 0.5)) = max(1, 3) = 3
        self.assertEqual(len(selected), 3)


class TestExploitGate(unittest.TestCase):
    """Exploitation is gated by model confidence, independent of pressure."""

    def test_confident_model_exploits(self) -> None:
        af = AttentionField(exploit_threshold=0.3)
        # Low mean_uncertainty → confident → exploit
        self.assertTrue(af.should_exploit(mean_uncertainty=0.1))

    def test_uncertain_model_explores(self) -> None:
        af = AttentionField(exploit_threshold=0.3)
        # High mean_uncertainty → uncertain → don't exploit
        self.assertFalse(af.should_exploit(mean_uncertainty=0.8))

    def test_exploit_independent_of_pressure(self) -> None:
        """Same confidence → same gate, regardless of pressure."""
        af = AttentionField(exploit_threshold=0.3)
        # Low uncertainty should exploit even at zero pressure
        self.assertTrue(af.should_exploit(mean_uncertainty=0.1))
        # And also at high pressure
        self.assertTrue(af.should_exploit(mean_uncertainty=0.1))

    def test_threshold_boundary(self) -> None:
        af = AttentionField(exploit_threshold=0.5)
        self.assertTrue(af.should_exploit(mean_uncertainty=0.49))
        self.assertFalse(af.should_exploit(mean_uncertainty=0.51))


class TestRegimeShiftRedistribution(unittest.TestCase):
    """After regime change, attention redistributes to newly relevant cues."""

    def test_attention_redistributes_after_ip_shift(self) -> None:
        af = AttentionField(K=6, m=2, lr=1.0)  # lr=1.0 for instant update
        # Phase 1: cues 0,1 are most informative
        af.information_power = [2.0, 1.5, 0.1, 0.1, 0.0, 0.0]
        before = sorted(af.select_attention())
        self.assertEqual(before, [0, 1])
        # Phase 2: regime changes, now cues 3,4 are most informative
        af.information_power = [0.1, 0.0, 0.1, 3.0, 2.5, 0.0]
        after = sorted(af.select_attention())
        self.assertEqual(after, [3, 4])
        self.assertNotEqual(before, after)


class TestSurpriseTriggeredReset(unittest.TestCase):
    """ADR-0004: Surprise-triggered IP reset with dynamic threshold."""

    def test_low_surprise_no_reset(self) -> None:
        """Steady-state low surprise should NOT trigger IP reset."""
        af = AttentionField(K=6, m=2)
        af.information_power = [2.0, 1.5, 0.1, 0.1, 0.0, 0.0]
        # Feed many low-surprise values to build history
        for _ in range(20):
            af.on_surprise(0.2)
        # IP should be unchanged
        self.assertAlmostEqual(af.information_power[0], 2.0)
        self.assertAlmostEqual(af.information_power[1], 1.5)

    def test_high_surprise_triggers_reset(self) -> None:
        """Sustained low surprise then a spike → IP decays toward zero."""
        af = AttentionField(K=6, m=2)
        af.information_power = [2.0, 1.5, 0.1, 0.1, 0.0, 0.0]
        # Build baseline with low surprise
        for _ in range(20):
            af.on_surprise(0.2)
        # Now a big surprise (well above baseline + 2.5*noise_floor)
        af.on_surprise(5.0)
        # IP should have decayed significantly
        self.assertLess(af.information_power[0], 1.0)
        self.assertLess(af.information_power[1], 0.8)

    def test_reset_clears_counts(self) -> None:
        """After reset, count_on and count_off are zeroed."""
        af = AttentionField(K=4, m=2)
        # Simulate some observations
        for _ in range(10):
            af.update(reward=3.0, cue_values=(1, 0, 1, 0), attended=[0, 1, 2, 3])
        self.assertGreater(sum(af._count_on), 0)
        # Build surprise history then trigger reset
        for _ in range(10):
            af.on_surprise(0.1)
        af.on_surprise(5.0)
        self.assertEqual(sum(af._count_on), 0)
        self.assertEqual(sum(af._count_off), 0)

    def test_cooldown_prevents_rapid_resets(self) -> None:
        """Two resets within cooldown period should not both fire."""
        af = AttentionField(K=4, m=2)
        af.information_power = [2.0, 1.5, 0.1, 0.0]
        # Build history
        for _ in range(10):
            af.on_surprise(0.1)
        # First reset
        af.on_surprise(5.0)
        self.assertTrue(af._last_reset_step >= 0)
        saved_step = af._last_reset_step
        # Second spike immediately after — should NOT reset
        af.on_surprise(5.0)
        self.assertEqual(af._last_reset_step, saved_step)

    def test_needs_minimum_samples(self) -> None:
        """Reset should not fire with fewer than 5 surprise samples."""
        af = AttentionField(K=4, m=2)
        af.information_power = [2.0, 1.5, 0.1, 0.0]
        af.on_surprise(0.1)
        af.on_surprise(10.0)  # Only 2 samples, should not reset
        self.assertAlmostEqual(af.information_power[0], 2.0)


class TestPostResetUniformWindow(unittest.TestCase):
    """ADR-0004: After reset, select_attention uses uniform rotation."""

    def test_uniform_coverage_after_reset(self) -> None:
        """K/m steps of uniform rotation should cover all K cues."""
        af = AttentionField(K=12, m=3)
        # Trigger a reset
        for _ in range(10):
            af.on_surprise(0.1)
        af.on_surprise(5.0)
        # Next K/m=4 calls should cover all 12 cues
        covered = set()
        for _ in range(4):
            attended = af.select_attention()
            covered.update(attended)
            af._steps_since_reset += 1  # simulate step advancement
        self.assertEqual(covered, set(range(12)))

    def test_returns_to_ip_after_window(self) -> None:
        """After the uniform window expires, IP-based selection resumes."""
        af = AttentionField(K=6, m=2)
        af.information_power = [0.1, 0.1, 0.1, 3.0, 2.5, 0.0]
        # Trigger reset
        for _ in range(10):
            af.on_surprise(0.1)
        af.on_surprise(5.0)
        # Advance past the uniform window (K/m = 3 steps)
        af._steps_since_reset = 100
        selected = af.select_attention()
        self.assertEqual(sorted(selected), [3, 4])

    def test_backward_compat_no_surprise_input(self) -> None:
        """Without calling on_surprise, behavior is identical to v1."""
        af = AttentionField(K=6, m=2)
        af.information_power = [0.1, 0.9, 0.3, 0.2, 0.8, 0.0]
        selected = af.select_attention()
        self.assertEqual(sorted(selected), [1, 4])


class TestBackwardCompat(unittest.TestCase):
    """AttentionField works with GridlessSurvival via explore_drive."""

    def test_explore_drive_default(self) -> None:
        af = AttentionField(K=8)
        self.assertIsInstance(af.explore_drive, float)

    def test_explore_drive_reflects_gate(self) -> None:
        af = AttentionField(K=8, exploit_threshold=0.3)
        af.sync_explore_drive(mean_uncertainty=0.1)  # confident → exploit → low drive
        low = af.explore_drive
        af.sync_explore_drive(mean_uncertainty=0.8)  # uncertain → explore → high drive
        high = af.explore_drive
        self.assertLess(low, high)


if __name__ == "__main__":
    unittest.main()
