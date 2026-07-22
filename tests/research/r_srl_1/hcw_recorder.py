from __future__ import annotations

import enum
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Iterable


class HcwCategory(enum.Enum):
    """Hidden cognitive work category codes for R-SRL-1 raters.

    See ``docs/research/R-SRL-1-preregistration-2026-07-16.md`` §6.1.
    """

    DISCOVER = "DISCOVER"
    RESTATE = "RESTATE"
    GOAL_FORM = "GOAL_FORM"
    LOCATE = "LOCATE"
    PRIORITIZE = "PRIORITIZE"
    INTERPRET = "INTERPRET"
    REPEAT = "REPEAT"
    AUTH = "AUTH"
    WAIT = "WAIT"
    OTHER = "OTHER"


@dataclass(frozen=True)
class HcwAnnotation:
    """A single blind-rater HCW segment annotation."""

    segment_id: str
    arm_id: str
    unit_id: str
    event_id: str | None
    category: HcwCategory
    start_seconds: float
    end_seconds: float
    rater_id: str
    notes: str = ""

    def duration_seconds(self) -> float:
        """Return ``end_seconds - start_seconds``."""
        return self.end_seconds - self.start_seconds


@dataclass(frozen=True)
class HcwArmSummary:
    """Comparable HCW summary for one R-SRL-1 arm/unit."""

    arm_id: str
    unit_id: str
    hcw_minutes: float
    operator_interventions: int
    verified_outcomes: int

    @property
    def outcomes_per_hcw_minute(self) -> float:
        """Return verified outcomes divided by HCW minutes.

        A zero-HCW arm with verified outcomes is treated as infinite efficiency;
        a zero-HCW arm without outcomes has zero efficiency.  The comparison
        function still requires real annotations so missing HCW data does not
        become a free win.
        """
        if self.hcw_minutes == 0.0:
            return float("inf") if self.verified_outcomes > 0 else 0.0
        return self.verified_outcomes / self.hcw_minutes


@dataclass(frozen=True)
class HcwIrreducibilityComparison:
    """SRL-vs-baselines comparison for the HCW primary metric.

    ``VERIFIED_HCW_REDUCTION`` is only a scorer-level comparison verdict. It is
    not a full R-SRL-1 experiment verdict and does not imply a product or
    autonomy claim.
    """

    verdict: str
    srl: HcwArmSummary
    best_baseline: HcwArmSummary | None
    best_baseline_arm_id: str | None
    hcw_minutes_ratio: float | None
    operator_intervention_ratio: float | None
    outcomes_per_hcw_minute_ratio: float | None
    gaps: tuple[str, ...]


class HcwRecorder:
    """Stores blind-rater HCW annotations per (arm_id, unit_id) and computes
    primary-metric aggregates.
    """

    def __init__(self) -> None:
        self._annotations: dict[tuple[str, str], list[HcwAnnotation]] = {}

    def add_annotation(self, annotation: HcwAnnotation) -> None:
        """Store an annotation after basic validity checks."""
        if annotation.end_seconds < annotation.start_seconds:
            raise ValueError(
                f"end_seconds ({annotation.end_seconds}) must be >= "
                f"start_seconds ({annotation.start_seconds})"
            )
        key = (annotation.arm_id, annotation.unit_id)
        self._annotations.setdefault(key, [])
        self._annotations[key].append(annotation)

    def list_annotations(self, arm_id: str, unit_id: str) -> tuple[HcwAnnotation, ...]:
        """Return all annotations for the given arm/unit, in insertion order."""
        return tuple(self._annotations.get((arm_id, unit_id), []))

    def total_hcw_minutes(
        self, arm_id: str, unit_id: str, exclude_auth_wait: bool = True
    ) -> float:
        """Sum segment durations, optionally excluding AUTH and WAIT categories.

        Returns minutes (seconds / 60.0).  The preregistration excludes WAIT from
        the HCW numerator and counts AUTH separately.
        """
        excluded = {HcwCategory.AUTH, HcwCategory.WAIT} if exclude_auth_wait else set()
        total_seconds = 0.0
        for annotation in self._annotations.get((arm_id, unit_id), []):
            if annotation.category in excluded:
                continue
            total_seconds += annotation.duration_seconds()
        return total_seconds / 60.0

    def operator_intervention_count(
        self, arm_id: str, unit_id: str, exclude_auth_wait: bool = True
    ) -> int:
        """Count operator HCW segments for the arm/unit.

        This redirects R-SRL-1 away from a pure task-success metric toward the
        actual operator interventions needed to keep the Mandate on track.
        AUTH and WAIT are excluded by default to match the preregistered HCW
        numerator treatment.
        """
        excluded = {HcwCategory.AUTH, HcwCategory.WAIT} if exclude_auth_wait else set()
        return sum(
            1
            for annotation in self._annotations.get((arm_id, unit_id), [])
            if annotation.category not in excluded
        )

    def category_breakdown(self, arm_id: str, unit_id: str) -> dict[HcwCategory, float]:
        """Return total seconds per HCW category for the arm/unit."""
        breakdown: dict[HcwCategory, float] = {
            category: 0.0 for category in HcwCategory
        }
        for annotation in self._annotations.get((arm_id, unit_id), []):
            breakdown[annotation.category] += annotation.duration_seconds()
        return breakdown

    def arm_summary(
        self,
        arm_id: str,
        unit_id: str,
        verified_outcomes: int = 0,
    ) -> HcwArmSummary:
        """Return the comparable HCW summary for one arm/unit."""
        if verified_outcomes < 0:
            raise ValueError("verified_outcomes must be >= 0")
        return HcwArmSummary(
            arm_id=arm_id,
            unit_id=unit_id,
            hcw_minutes=self.total_hcw_minutes(arm_id, unit_id),
            operator_interventions=self.operator_intervention_count(arm_id, unit_id),
            verified_outcomes=verified_outcomes,
        )


def compare_srl_to_baselines(
    recorder: HcwRecorder,
    *,
    unit_id: str,
    srl_arm_id: str,
    baseline_arm_ids: tuple[str, ...],
    verified_outcomes: Mapping[str, int],
    max_hcw_minutes_ratio: float = 0.70,
    max_operator_intervention_ratio: float = 0.70,
    min_outcomes_per_hcw_minute_ratio: float = 1.30,
) -> HcwIrreducibilityComparison:
    """Compare SRL HCW against the strongest available baseline.

    The reported "best baseline" is the baseline with the highest verified
    outcomes per HCW minute. The verdict still requires SRL to beat every
    baseline by the frozen margins, matching the preregistered "each baseline"
    condition rather than a convenient weaker or single-best baseline.
    Missing SRL/baseline annotations fail closed as ``INVALID``.
    """
    srl_annotations = recorder.list_annotations(srl_arm_id, unit_id)
    srl_verified_outcomes = _verified_outcome_count(
        verified_outcomes, srl_arm_id, required=False
    )
    srl = recorder.arm_summary(
        srl_arm_id,
        unit_id,
        verified_outcomes=0
        if srl_verified_outcomes is None
        else srl_verified_outcomes,
    )
    if not srl_annotations:
        return HcwIrreducibilityComparison(
            verdict="INVALID",
            srl=srl,
            best_baseline=None,
            best_baseline_arm_id=None,
            hcw_minutes_ratio=None,
            operator_intervention_ratio=None,
            outcomes_per_hcw_minute_ratio=None,
            gaps=("no SRL arm has HCW annotations",),
        )

    outcome_count_gaps: list[str] = []
    zero_denominator_gaps: list[str] = []
    if srl_verified_outcomes is None:
        outcome_count_gaps.append(f"missing verified outcome count for {srl_arm_id}")
    if srl.hcw_minutes == 0.0:
        zero_denominator_gaps.append("SRL arm has zero comparable HCW minutes")

    baseline_summaries: list[HcwArmSummary] = []
    for arm_id in baseline_arm_ids:
        if not recorder.list_annotations(arm_id, unit_id):
            continue
        baseline_verified_outcomes = _verified_outcome_count(
            verified_outcomes, arm_id, required=False
        )
        baseline_summaries.append(
            recorder.arm_summary(
                arm_id,
                unit_id,
                verified_outcomes=0
                if baseline_verified_outcomes is None
                else baseline_verified_outcomes,
            )
        )
    if not baseline_summaries:
        return HcwIrreducibilityComparison(
            verdict="INVALID",
            srl=srl,
            best_baseline=None,
            best_baseline_arm_id=None,
            hcw_minutes_ratio=None,
            operator_intervention_ratio=None,
            outcomes_per_hcw_minute_ratio=None,
            gaps=("no baseline arm has HCW annotations",),
        )

    for summary in baseline_summaries:
        if _verified_outcome_count(verified_outcomes, summary.arm_id, required=False) is None:
            outcome_count_gaps.append(
                f"missing verified outcome count for {summary.arm_id}"
            )
        if summary.hcw_minutes == 0.0:
            zero_denominator_gaps.append(
                f"baseline arm {summary.arm_id} has zero comparable HCW minutes"
            )

    invalid_gaps = tuple(outcome_count_gaps + zero_denominator_gaps)
    if invalid_gaps:
        return HcwIrreducibilityComparison(
            verdict="INVALID",
            srl=srl,
            best_baseline=None,
            best_baseline_arm_id=None,
            hcw_minutes_ratio=None,
            operator_intervention_ratio=None,
            outcomes_per_hcw_minute_ratio=None,
            gaps=invalid_gaps,
        )

    best_baseline = max(
        baseline_summaries,
        key=lambda summary: (
            summary.outcomes_per_hcw_minute,
            summary.verified_outcomes,
            -summary.hcw_minutes,
        ),
    )
    gaps: list[str] = []
    for baseline in baseline_summaries:
        hcw_ratio = _safe_ratio(srl.hcw_minutes, baseline.hcw_minutes)
        operator_ratio = _safe_ratio(
            float(srl.operator_interventions),
            float(baseline.operator_interventions),
        )
        efficiency_ratio = _safe_ratio(
            srl.outcomes_per_hcw_minute,
            baseline.outcomes_per_hcw_minute,
        )

        if hcw_ratio is None or hcw_ratio > max_hcw_minutes_ratio:
            gaps.append(
                f"SRL HCW minutes do not beat baseline {baseline.arm_id} by the required margin"
            )
        if (
            operator_ratio is None
            or operator_ratio > max_operator_intervention_ratio
        ):
            gaps.append(
                f"SRL operator intervention count does not beat baseline {baseline.arm_id} by the required margin"
            )
        if (
            efficiency_ratio is None
            or efficiency_ratio < min_outcomes_per_hcw_minute_ratio
        ):
            gaps.append(
                f"SRL verified outcomes per HCW minute do not beat baseline {baseline.arm_id} by the required margin"
            )
        if srl.verified_outcomes < baseline.verified_outcomes:
            gaps.append(
                f"SRL verified outcomes are lower than baseline {baseline.arm_id}"
            )

    hcw_minutes_ratio = _safe_ratio(srl.hcw_minutes, best_baseline.hcw_minutes)
    operator_intervention_ratio = _safe_ratio(
        float(srl.operator_interventions), float(best_baseline.operator_interventions)
    )
    outcomes_per_hcw_minute_ratio = _safe_ratio(
        srl.outcomes_per_hcw_minute,
        best_baseline.outcomes_per_hcw_minute,
    )

    return HcwIrreducibilityComparison(
        verdict="VERIFIED_HCW_REDUCTION" if not gaps else "NOT_MET",
        srl=srl,
        best_baseline=best_baseline,
        best_baseline_arm_id=best_baseline.arm_id,
        hcw_minutes_ratio=hcw_minutes_ratio,
        operator_intervention_ratio=operator_intervention_ratio,
        outcomes_per_hcw_minute_ratio=outcomes_per_hcw_minute_ratio,
        gaps=tuple(gaps),
    )


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    """Return numerator/denominator, failing closed on undefined comparisons."""
    if denominator == 0.0:
        return 0.0 if numerator == 0.0 else None
    return numerator / denominator


def _verified_outcome_count(
    verified_outcomes: Mapping[str, int], arm_id: str, *, required: bool = True
) -> int | None:
    """Return a validated verified-outcome count for an arm.

    HCW comparisons use outcome counts to choose the strongest baseline. Missing
    or malformed counts therefore cannot be silently coerced to zero: that would
    make an unscored baseline look weak and allow a false irreducibility win.
    """
    if arm_id not in verified_outcomes:
        if required:
            raise ValueError(f"missing verified outcome count for {arm_id}")
        return None
    count = verified_outcomes[arm_id]
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        if required:
            raise ValueError(
                f"verified outcome count for {arm_id} must be a non-negative int"
            )
        return None
    return count


def run_rater_prompt(
    arm_id: str,
    unit_id: str,
    event_id: str | None,
    transcript_lines: Iterable[str],
) -> HcwAnnotation:
    """Print a structured rater prompt to stdout and return a sample annotation.

    This is a prototype CLI helper; it does not perform real input handling.
    """
    transcript = "\n".join(transcript_lines)
    print("--- R-SRL-1 HCW rater prompt ---")
    print(f"arm_id: {arm_id}")
    print(f"unit_id: {unit_id}")
    print(f"event_id: {event_id}")
    print("Instructions:")
    print("  1. Read the transcript segment below.")
    print("  2. Mark one HCW category from the taxonomy in §6.1.")
    print("  3. Record start/end times in seconds relative to the segment.")
    print("  4. Add brief, category-justifying notes.")
    print("Transcript:")
    print(transcript)
    print("--- end prompt ---")
    return HcwAnnotation(
        segment_id=f"{arm_id}-{unit_id}-{event_id or 'none'}-sample",
        arm_id=arm_id,
        unit_id=unit_id,
        event_id=event_id,
        category=HcwCategory.OTHER,
        start_seconds=0.0,
        end_seconds=30.0,
        rater_id="prototype-rater",
        notes="Sample annotation produced by the prototype CLI.",
    )
