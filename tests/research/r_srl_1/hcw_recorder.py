from __future__ import annotations

import enum
from dataclasses import dataclass
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

    def category_breakdown(self, arm_id: str, unit_id: str) -> dict[HcwCategory, float]:
        """Return total seconds per HCW category for the arm/unit."""
        breakdown: dict[HcwCategory, float] = {
            category: 0.0 for category in HcwCategory
        }
        for annotation in self._annotations.get((arm_id, unit_id), []):
            breakdown[annotation.category] += annotation.duration_seconds()
        return breakdown


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
