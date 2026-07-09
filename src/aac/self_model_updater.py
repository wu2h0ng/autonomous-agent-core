"""E6 AgentSelfModel runtime update — calibrates the self-model from governed outcomes.

The updater is a belief-channel mechanism: it reads action outcomes and writes
deltas into the AgentSelfModel's confidence thresholds, evidence requirements, and
tool reliability estimates. It never sees the shell, the gate verdict, or the
policy — only the observable outcome of an action the gate already passed.

C6 preserved: the updater is an organ-advisory mechanism, not a decision-maker.
C7 preserved: the updater never modifies pause/forbidden/approval/risk-ceiling — those
remain operator-controlled through the CorrigibilityShell.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ConfidenceTracker:
    """Per-risk-tier confidence calibration state."""

    ewma_error: float = 0.0
    count: int = 0
    last_calibrated_threshold: float = 0.0


@dataclass
class ToolReliability:
    """Per-tool reliability tracking."""

    successes: int = 0
    failures: int = 0
    ewma_reliability: float = 0.5


@dataclass
class AgentSelfModelUpdater:
    """Runtime self-model calibrator: updates confidence thresholds, evidence
    requirements, and tool reliability from governed action outcomes.

    This is E6 behavioral endogeneity: the system updates its own capability/risk/
    permission/failure model from evidence — all under C7's immutable correction
    boundary. The self-model never gains write access to C7 gates.

    An updater that always returns identity deltas is valid (ablation baseline).
    """

    n_actions: int
    calibration_lr: float = 0.1
    evidence_lr: float = 0.05
    reliability_lr: float = 0.1
    min_threshold: float = 0.1
    max_threshold: float = 0.95
    decay: float = 0.0

    confidence_trackers: dict[int, ConfidenceTracker] = field(default_factory=dict)
    tool_reliabilities: dict[str, ToolReliability] = field(default_factory=dict)
    evidence_outcomes: dict[int, list[float]] = field(default_factory=dict)
    total_updates: int = 0

    def calibrate_confidence(
        self,
        risk_tier: int,
        predicted_confidence: float,
        outcome_correct: bool,
    ) -> float:
        """Recalibrate confidence threshold for a risk tier.

        Returns the recommended new threshold. The caller applies it to the
        AgentSelfModel; the updater never writes the self-model directly.
        """
        tracker = self.confidence_trackers.setdefault(
            risk_tier, ConfidenceTracker()
        )
        error = float(outcome_correct) - predicted_confidence
        tracker.ewma_error = (
            (1.0 - self.calibration_lr) * tracker.ewma_error
            + self.calibration_lr * error
        )
        tracker.count += 1

        current = tracker.last_calibrated_threshold or 0.5
        adjusted = current - self.calibration_lr * tracker.ewma_error
        clamped = max(self.min_threshold, min(self.max_threshold, adjusted))
        tracker.last_calibrated_threshold = clamped
        return clamped

    def update_tool_reliability(self, action: str, success: bool) -> float:
        """Update and return the reliability score for a tool."""
        rel = self.tool_reliabilities.setdefault(action, ToolReliability())
        if success:
            rel.successes += 1
        else:
            rel.failures += 1
        total = rel.successes + rel.failures
        raw = rel.successes / max(1, total) if total > 0 else 0.5
        rel.ewma_reliability = (
            (1.0 - self.reliability_lr) * rel.ewma_reliability
            + self.reliability_lr * raw
        )
        return rel.ewma_reliability

    def adjust_evidence_requirement(
        self, risk_tier: int, evidence_count: int, outcome_quality: float
    ) -> int:
        """Recommend an evidence requirement delta.

        outcome_quality > 0: outcome was better than expected with this evidence.
        outcome_quality < 0: outcome was worse — may need more evidence.
        Returns a delta from current (not the absolute value).
        """
        outcomes = self.evidence_outcomes.setdefault(risk_tier, [])
        outcomes.append(outcome_quality)
        if len(outcomes) > 50:
            outcomes.pop(0)
        mean_quality = sum(outcomes) / len(outcomes)
        if mean_quality < -0.2 and evidence_count < 5:
            return 1
        if mean_quality > 0.2 and evidence_count > 1:
            return -1
        return 0

    def after_action(
        self,
        action: str,
        risk_tier: int,
        predicted_confidence: float,
        evidence_count: int,
        outcome: float,
        outcome_baseline: float,
    ) -> dict:
        """Full update pass after a governed action completes.

        Returns a dict with recommended deltas for the AgentSelfModel:
          - confidence_thresholds: {tier: new_threshold}
          - evidence_requirements: {tier: delta}
          - tool_reliability: {action: score}
        The caller (Agent / GovernedLoop) applies these to the self-model.
        """
        self.total_updates += 1
        success = outcome > outcome_baseline
        outcome_quality = (outcome - outcome_baseline) / max(1.0, abs(outcome_baseline) + 1e-9)

        new_conf = self.calibrate_confidence(risk_tier, predicted_confidence, success)
        rel = self.update_tool_reliability(action, success)
        ev_delta = self.adjust_evidence_requirement(risk_tier, evidence_count, outcome_quality)

        if self.decay > 0.0 and self.total_updates % 20 == 0:
            for t in self.confidence_trackers.values():
                t.ewma_error *= (1.0 - self.decay)

        return {
            "confidence_thresholds": {risk_tier: new_conf},
            "evidence_requirements": {risk_tier: ev_delta},
            "tool_reliability": {action: rel},
        }

    def get_tool_reliability(self, action: str) -> float:
        """Return the current reliability score for a tool, or 0.5 if unknown."""
        rel = self.tool_reliabilities.get(action)
        return rel.ewma_reliability if rel is not None else 0.5

    def get_confidence_threshold(self, risk_tier: int) -> Optional[float]:
        """Return the currently calibrated threshold for a tier, if any."""
        tracker = self.confidence_trackers.get(risk_tier)
        if tracker is not None and tracker.last_calibrated_threshold > 0:
            return tracker.last_calibrated_threshold
        return None

    def state(self) -> dict:
        """Serializable state for snapshot/restore."""
        return {
            "confidence_trackers": {
                t: {"ewma_error": c.ewma_error, "count": c.count,
                    "last_calibrated_threshold": c.last_calibrated_threshold}
                for t, c in self.confidence_trackers.items()
            },
            "tool_reliabilities": {
                a: {"successes": r.successes, "failures": r.failures,
                    "ewma_reliability": r.ewma_reliability}
                for a, r in self.tool_reliabilities.items()
            },
            "total_updates": self.total_updates,
        }

    def restore(self, saved: dict) -> None:
        """Restore from a state dict produced by state()."""
        self.confidence_trackers.clear()
        for t_str, c_data in saved.get("confidence_trackers", {}).items():
            self.confidence_trackers[int(t_str)] = ConfidenceTracker(**c_data)
        self.tool_reliabilities.clear()
        for a, r_data in saved.get("tool_reliabilities", {}).items():
            self.tool_reliabilities[a] = ToolReliability(**r_data)
        self.total_updates = saved.get("total_updates", 0)
