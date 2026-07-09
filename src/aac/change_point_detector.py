"""Lightweight change-point detection for online causal discovery.

These detectors are intentionally simple: they look for distributional drift
between consecutive observation batches and signal the discovery loop to reset
its posterior (discard stale samples).  They do not modify the causal model
directly and hold no execution authority.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass


@dataclass
class MeanDriftDetector:
    """Detect a regime shift via standardized mean differences per variable.

    Args:
        threshold: minimum standardized mean difference that triggers a reset.
            A value of 1.0 means at least one variable shifted by one pooled
            standard deviation between consecutive batches.
    """

    threshold: float = 1.0

    def drift_detected(
        self,
        previous: list[list[float]],
        current: list[list[float]],
    ) -> bool:
        """Return True if ``current`` batch is distributionally shifted."""
        if not previous or not current:
            return False
        n_vars = len(previous[0])
        for j in range(n_vars):
            prev_vals = [row[j] for row in previous]
            curr_vals = [row[j] for row in current]
            mean_prev = statistics.mean(prev_vals)
            mean_curr = statistics.mean(curr_vals)
            std_prev = statistics.stdev(prev_vals) if len(prev_vals) > 1 else 0.0
            std_curr = statistics.stdev(curr_vals) if len(curr_vals) > 1 else 0.0
            pooled = math.sqrt((std_prev ** 2 + std_curr ** 2) / 2.0)
            if pooled == 0.0:
                continue
            if abs(mean_curr - mean_prev) / pooled > self.threshold:
                return True
        return False
