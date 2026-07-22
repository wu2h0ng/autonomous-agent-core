from __future__ import annotations

import pytest

from tests.research.r_srl_1.hcw_recorder import (
    HcwAnnotation,
    HcwCategory,
    HcwRecorder,
    compare_srl_to_baselines,
    run_rater_prompt,
)


def _make_annotation(
    category: HcwCategory,
    start: float,
    end: float,
    segment_id: str = "seg-01",
    event_id: str | None = "event-01",
    rater_id: str = "rater-a",
) -> HcwAnnotation:
    return HcwAnnotation(
        segment_id=segment_id,
        arm_id="arm3",
        unit_id="u00",
        event_id=event_id,
        category=category,
        start_seconds=start,
        end_seconds=end,
        rater_id=rater_id,
    )


def _make_arm_annotation(
    arm_id: str,
    category: HcwCategory,
    start: float,
    end: float,
    segment_id: str,
) -> HcwAnnotation:
    return HcwAnnotation(
        segment_id=segment_id,
        arm_id=arm_id,
        unit_id="u00",
        event_id="event-01",
        category=category,
        start_seconds=start,
        end_seconds=end,
        rater_id="rater-a",
    )


def test_add_and_list_annotations() -> None:
    recorder = HcwRecorder()
    a1 = _make_annotation(HcwCategory.DISCOVER, 0.0, 15.0)
    a2 = _make_annotation(HcwCategory.INTERPRET, 15.0, 45.0, segment_id="seg-02")
    recorder.add_annotation(a1)
    recorder.add_annotation(a2)

    listed = recorder.list_annotations("arm3", "u00")
    assert listed == (a1, a2)


def test_list_annotations_returns_empty_for_unknown_unit() -> None:
    recorder = HcwRecorder()
    assert recorder.list_annotations("arm1", "unknown") == ()


def test_total_hcw_minutes_excludes_auth_and_wait_by_default() -> None:
    recorder = HcwRecorder()
    recorder.add_annotation(_make_annotation(HcwCategory.DISCOVER, 0.0, 60.0))
    recorder.add_annotation(_make_annotation(HcwCategory.AUTH, 60.0, 120.0))
    recorder.add_annotation(_make_annotation(HcwCategory.WAIT, 120.0, 180.0))

    assert recorder.total_hcw_minutes("arm3", "u00") == pytest.approx(1.0)


def test_total_hcw_minutes_includes_auth_and_wait_when_not_excluded() -> None:
    recorder = HcwRecorder()
    recorder.add_annotation(_make_annotation(HcwCategory.DISCOVER, 0.0, 60.0))
    recorder.add_annotation(_make_annotation(HcwCategory.AUTH, 60.0, 120.0))
    recorder.add_annotation(_make_annotation(HcwCategory.WAIT, 120.0, 180.0))

    assert recorder.total_hcw_minutes(
        "arm3", "u00", exclude_auth_wait=False
    ) == pytest.approx(3.0)


def test_total_hcw_minutes_for_empty_unit_is_zero() -> None:
    recorder = HcwRecorder()
    assert recorder.total_hcw_minutes("arm3", "u00") == 0.0


def test_operator_intervention_count_excludes_auth_and_wait_by_default() -> None:
    recorder = HcwRecorder()
    recorder.add_annotation(_make_annotation(HcwCategory.DISCOVER, 0.0, 10.0))
    recorder.add_annotation(_make_annotation(HcwCategory.PRIORITIZE, 10.0, 20.0))
    recorder.add_annotation(_make_annotation(HcwCategory.AUTH, 20.0, 30.0))
    recorder.add_annotation(_make_annotation(HcwCategory.WAIT, 30.0, 40.0))

    assert recorder.operator_intervention_count("arm3", "u00") == 2
    assert (
        recorder.operator_intervention_count(
            "arm3", "u00", exclude_auth_wait=False
        )
        == 4
    )


def test_category_breakdown_sums_seconds_per_category() -> None:
    recorder = HcwRecorder()
    recorder.add_annotation(_make_annotation(HcwCategory.DISCOVER, 0.0, 10.0))
    recorder.add_annotation(_make_annotation(HcwCategory.DISCOVER, 10.0, 25.0))
    recorder.add_annotation(_make_annotation(HcwCategory.LOCATE, 25.0, 40.0))
    recorder.add_annotation(_make_annotation(HcwCategory.WAIT, 40.0, 60.0))

    breakdown = recorder.category_breakdown("arm3", "u00")
    assert breakdown[HcwCategory.DISCOVER] == pytest.approx(25.0)
    assert breakdown[HcwCategory.LOCATE] == pytest.approx(15.0)
    assert breakdown[HcwCategory.WAIT] == pytest.approx(20.0)
    assert breakdown[HcwCategory.RESTATE] == pytest.approx(0.0)


def test_compare_srl_to_baselines_verifies_irreducible_hcw_gain() -> None:
    recorder = HcwRecorder()
    for index in range(6):
        recorder.add_annotation(
            _make_arm_annotation(
                "arm1",
                HcwCategory.DISCOVER,
                index * 60.0,
                (index + 1) * 60.0,
                f"b1-{index}",
            )
        )
    for index in range(5):
        recorder.add_annotation(
            _make_arm_annotation(
                "arm2",
                HcwCategory.PRIORITIZE,
                index * 60.0,
                (index + 1) * 60.0,
                f"b2-{index}",
            )
        )
    for index in range(3):
        recorder.add_annotation(
            _make_arm_annotation(
                "arm3",
                HcwCategory.LOCATE,
                index * 60.0,
                (index + 1) * 60.0,
                f"srl-{index}",
            )
        )

    comparison = compare_srl_to_baselines(
        recorder,
        unit_id="u00",
        srl_arm_id="arm3",
        baseline_arm_ids=("arm1", "arm2"),
        verified_outcomes={"arm1": 3, "arm2": 4, "arm3": 4},
    )

    assert comparison.verdict == "VERIFIED_HCW_REDUCTION"
    assert comparison.best_baseline_arm_id == "arm2"
    assert comparison.srl.operator_interventions == 3
    assert comparison.best_baseline is not None
    assert comparison.best_baseline.operator_interventions == 5
    assert comparison.hcw_minutes_ratio == pytest.approx(0.6)
    assert comparison.outcomes_per_hcw_minute_ratio == pytest.approx(5 / 3)
    assert comparison.gaps == ()


def test_compare_srl_to_baselines_fails_closed_without_baseline() -> None:
    recorder = HcwRecorder()
    recorder.add_annotation(
        _make_arm_annotation("arm3", HcwCategory.LOCATE, 0.0, 60.0, "srl-1")
    )

    comparison = compare_srl_to_baselines(
        recorder,
        unit_id="u00",
        srl_arm_id="arm3",
        baseline_arm_ids=("arm1", "arm2"),
        verified_outcomes={"arm3": 1},
    )

    assert comparison.verdict == "INVALID"
    assert comparison.gaps == ("no baseline arm has HCW annotations",)


def test_compare_srl_to_baselines_rejects_task_success_only_tie() -> None:
    recorder = HcwRecorder()
    for index in range(4):
        recorder.add_annotation(
            _make_arm_annotation(
                "arm1",
                HcwCategory.DISCOVER,
                index * 60.0,
                (index + 1) * 60.0,
                f"baseline-{index}",
            )
        )
    for index in range(4):
        recorder.add_annotation(
            _make_arm_annotation(
                "arm3",
                HcwCategory.LOCATE,
                index * 60.0,
                (index + 1) * 60.0,
                f"srl-{index}",
            )
        )

    comparison = compare_srl_to_baselines(
        recorder,
        unit_id="u00",
        srl_arm_id="arm3",
        baseline_arm_ids=("arm1",),
        verified_outcomes={"arm1": 4, "arm3": 4},
    )

    assert comparison.verdict == "NOT_MET"
    assert comparison.hcw_minutes_ratio == pytest.approx(1.0)
    assert comparison.operator_intervention_ratio == pytest.approx(1.0)
    assert (
        "SRL HCW minutes do not beat baseline arm1 by the required margin"
        in comparison.gaps
    )
    assert (
        "SRL operator intervention count does not beat baseline arm1 by the required margin"
        in comparison.gaps
    )


def test_compare_srl_to_baselines_must_beat_each_baseline() -> None:
    recorder = HcwRecorder()
    recorder.add_annotation(
        _make_arm_annotation("arm1", HcwCategory.DISCOVER, 0.0, 300.0, "b1")
    )
    recorder.add_annotation(
        _make_arm_annotation("arm2", HcwCategory.PRIORITIZE, 0.0, 180.0, "b2")
    )
    recorder.add_annotation(
        _make_arm_annotation("arm3", HcwCategory.LOCATE, 0.0, 150.0, "srl")
    )

    comparison = compare_srl_to_baselines(
        recorder,
        unit_id="u00",
        srl_arm_id="arm3",
        baseline_arm_ids=("arm1", "arm2"),
        verified_outcomes={"arm1": 5, "arm2": 3, "arm3": 5},
    )

    assert comparison.verdict == "NOT_MET"
    assert comparison.best_baseline_arm_id == "arm1"
    assert comparison.hcw_minutes_ratio == pytest.approx(0.5)
    assert (
        "SRL HCW minutes do not beat baseline arm2 by the required margin"
        in comparison.gaps
    )


def test_compare_srl_to_baselines_fails_closed_without_verified_outcome_counts() -> None:
    recorder = HcwRecorder()
    recorder.add_annotation(
        _make_arm_annotation("arm1", HcwCategory.LOCATE, 0.0, 60.0, "b1-1")
    )
    recorder.add_annotation(
        _make_arm_annotation("arm3", HcwCategory.LOCATE, 0.0, 60.0, "srl-1")
    )

    comparison = compare_srl_to_baselines(
        recorder,
        unit_id="u00",
        srl_arm_id="arm3",
        baseline_arm_ids=("arm1",),
        verified_outcomes={"arm3": 1},
    )

    assert comparison.verdict == "INVALID"
    assert comparison.gaps == ("missing verified outcome count for arm1",)


def test_compare_srl_to_baselines_fails_closed_without_srl_outcome_count() -> None:
    recorder = HcwRecorder()
    recorder.add_annotation(
        _make_arm_annotation("arm1", HcwCategory.LOCATE, 0.0, 60.0, "b1-1")
    )
    recorder.add_annotation(
        _make_arm_annotation("arm3", HcwCategory.LOCATE, 0.0, 60.0, "srl-1")
    )

    comparison = compare_srl_to_baselines(
        recorder,
        unit_id="u00",
        srl_arm_id="arm3",
        baseline_arm_ids=("arm1",),
        verified_outcomes={"arm1": 1},
    )

    assert comparison.verdict == "INVALID"
    assert comparison.gaps == ("missing verified outcome count for arm3",)


def test_compare_srl_to_baselines_rejects_lower_verified_outcomes() -> None:
    recorder = HcwRecorder()
    recorder.add_annotation(
        _make_arm_annotation("arm1", HcwCategory.DISCOVER, 0.0, 120.0, "baseline")
    )
    recorder.add_annotation(
        _make_arm_annotation("arm3", HcwCategory.LOCATE, 0.0, 60.0, "srl")
    )

    comparison = compare_srl_to_baselines(
        recorder,
        unit_id="u00",
        srl_arm_id="arm3",
        baseline_arm_ids=("arm1",),
        verified_outcomes={"arm1": 5, "arm3": 4},
    )

    assert comparison.verdict == "NOT_MET"
    assert "SRL verified outcomes are lower than baseline arm1" in comparison.gaps


def test_compare_srl_to_baselines_fails_closed_on_zero_hcw_denominator() -> None:
    recorder = HcwRecorder()
    recorder.add_annotation(
        _make_arm_annotation("arm1", HcwCategory.AUTH, 0.0, 60.0, "b1-auth")
    )
    recorder.add_annotation(
        _make_arm_annotation("arm3", HcwCategory.AUTH, 0.0, 60.0, "srl-auth")
    )

    comparison = compare_srl_to_baselines(
        recorder,
        unit_id="u00",
        srl_arm_id="arm3",
        baseline_arm_ids=("arm1",),
        verified_outcomes={"arm1": 1, "arm3": 1},
    )

    assert comparison.verdict == "INVALID"
    assert comparison.gaps == (
        "SRL arm has zero comparable HCW minutes",
        "baseline arm arm1 has zero comparable HCW minutes",
    )


def test_add_annotation_rejects_negative_duration() -> None:
    recorder = HcwRecorder()
    bad = _make_annotation(HcwCategory.OTHER, 10.0, 5.0)
    with pytest.raises(ValueError, match="end_seconds .* must be >="):
        recorder.add_annotation(bad)


def test_run_rater_prompt_prints_and_returns_sample(
    capsys: pytest.CaptureFixture[str],
) -> None:
    transcript = ["operator: tests failed", "model: I will inspect the diff"]
    sample = run_rater_prompt("arm3", "u00", "event-01", transcript)

    captured = capsys.readouterr()
    assert "R-SRL-1 HCW rater prompt" in captured.out
    assert "arm_id: arm3" in captured.out
    assert "unit_id: u00" in captured.out
    assert "event_id: event-01" in captured.out
    assert "tests failed" in captured.out

    assert sample.arm_id == "arm3"
    assert sample.unit_id == "u00"
    assert sample.event_id == "event-01"
    assert sample.category == HcwCategory.OTHER
    assert sample.duration_seconds() == pytest.approx(30.0)
