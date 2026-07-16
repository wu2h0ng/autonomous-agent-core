from __future__ import annotations

import pytest

from tests.research.r_srl_1.hcw_recorder import (
    HcwAnnotation,
    HcwCategory,
    HcwRecorder,
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
