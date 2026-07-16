from __future__ import annotations

from tests.research.r_srl_1.hcw_recorder import (
    HcwAnnotation,
    HcwCategory,
    HcwRecorder,
)


ARM_ID = "arm3"
UNIT_ID = "r-srl-1-u00"

SYNTHETIC_TRANSCRIPT = [
    "[00:00] operator reads mission statement",
    "[00:12] operator notices a new failing test in the event ledger",
    "[00:35] operator searches for the test file",
    "[01:05] operator restates the mission and current commitment",
    "[01:40] operator decides to fix the failing test before reviewing logs",
    "[02:10] operator waits while the model generates a patch",
    "[02:50] operator interprets the test result and confirms the fix",
    "[03:20] operator asks the model to re-state the prior plan",
]


def _annotation(
    segment_id: str,
    event_id: str | None,
    category: HcwCategory,
    start: float,
    end: float,
    rater_id: str,
    notes: str,
) -> HcwAnnotation:
    return HcwAnnotation(
        segment_id=segment_id,
        arm_id=ARM_ID,
        unit_id=UNIT_ID,
        event_id=event_id,
        category=category,
        start_seconds=start,
        end_seconds=end,
        rater_id=rater_id,
        notes=notes,
    )


def main() -> None:
    recorder = HcwRecorder()

    # Rater 1 annotations.
    rater1 = "rater-1"
    recorder.add_annotation(
        _annotation(
            "u00-r1-discover",
            "event-01",
            HcwCategory.DISCOVER,
            12.0,
            25.0,
            rater1,
            "noticed new failing test",
        )
    )
    recorder.add_annotation(
        _annotation(
            "u00-r1-locate",
            "event-01",
            HcwCategory.LOCATE,
            35.0,
            55.0,
            rater1,
            "searched for test file",
        )
    )
    recorder.add_annotation(
        _annotation(
            "u00-r1-restate",
            "event-01",
            HcwCategory.RESTATE,
            65.0,
            80.0,
            rater1,
            "restated mission/commitment",
        )
    )
    recorder.add_annotation(
        _annotation(
            "u00-r1-prioritize",
            "event-01",
            HcwCategory.PRIORITIZE,
            100.0,
            115.0,
            rater1,
            "chose next step",
        )
    )
    recorder.add_annotation(
        _annotation(
            "u00-r1-wait",
            "event-01",
            HcwCategory.WAIT,
            130.0,
            170.0,
            rater1,
            "waiting for model output",
        )
    )
    recorder.add_annotation(
        _annotation(
            "u00-r1-interpret",
            "event-01",
            HcwCategory.INTERPRET,
            170.0,
            195.0,
            rater1,
            "interpreted test result",
        )
    )

    # Rater 2 annotations (slightly different segmentation).
    rater2 = "rater-2"
    recorder.add_annotation(
        _annotation(
            "u00-r2-discover",
            "event-01",
            HcwCategory.DISCOVER,
            10.0,
            22.0,
            rater2,
            "noticed failing test",
        )
    )
    recorder.add_annotation(
        _annotation(
            "u00-r2-locate",
            "event-01",
            HcwCategory.LOCATE,
            33.0,
            58.0,
            rater2,
            "searched for test file",
        )
    )
    recorder.add_annotation(
        _annotation(
            "u00-r2-goal-form",
            "event-01",
            HcwCategory.GOAL_FORM,
            60.0,
            78.0,
            rater2,
            "formed fix goal",
        )
    )
    recorder.add_annotation(
        _annotation(
            "u00-r2-prioritize",
            "event-01",
            HcwCategory.PRIORITIZE,
            98.0,
            118.0,
            rater2,
            "ordered work",
        )
    )
    recorder.add_annotation(
        _annotation(
            "u00-r2-wait",
            "event-01",
            HcwCategory.WAIT,
            128.0,
            172.0,
            rater2,
            "idle wait",
        )
    )
    recorder.add_annotation(
        _annotation(
            "u00-r2-interpret",
            "event-01",
            HcwCategory.INTERPRET,
            172.0,
            200.0,
            rater2,
            "confirmed fix",
        )
    )

    print("=== R-SRL-1 u00 HCW pilot report ===")
    print(f"Arm: {ARM_ID}")
    print(f"Unit: {UNIT_ID}")
    print()

    for rater_id in (rater1, rater2):
        annotations = [
            a
            for a in recorder.list_annotations(ARM_ID, UNIT_ID)
            if a.rater_id == rater_id
        ]
        total_minutes = recorder.total_hcw_minutes(ARM_ID, UNIT_ID)
        # Recompute per-rater total by filtering the full list manually.
        rater_seconds = sum(
            a.duration_seconds()
            for a in annotations
            if a.category not in {HcwCategory.AUTH, HcwCategory.WAIT}
        )
        rater_minutes = rater_seconds / 60.0
        rater_breakdown: dict[HcwCategory, float] = {}
        for category in HcwCategory:
            rater_breakdown[category] = sum(
                a.duration_seconds() for a in annotations if a.category == category
            )

        print(f"--- {rater_id} ---")
        print(f"Annotations: {len(annotations)}")
        print(f"Total HCW minutes (excl. AUTH/WAIT): {rater_minutes:.2f}")
        print("Category breakdown (seconds):")
        for category, seconds in rater_breakdown.items():
            if seconds > 0:
                print(f"  {category.value}: {seconds:.1f}")
        print()

    print(f"Combined total HCW minutes (recorder aggregate): {total_minutes:.2f}")
    print("Transcript lines:")
    for line in SYNTHETIC_TRANSCRIPT:
        print(f"  {line}")


if __name__ == "__main__":
    main()
