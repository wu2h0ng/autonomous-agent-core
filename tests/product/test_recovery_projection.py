from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent_os_contracts import TaskEvent, TaskEventDraft, TaskEventType
from agent_os_core import build_recovery_snapshot


NOW = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)


def _events(
    *items: tuple[TaskEventType, dict[str, object]],
    task_id: str = "task:recovery",
) -> tuple[TaskEvent, ...]:
    events: list[TaskEvent] = []
    causation_id: str | None = None
    for sequence, (event_type, payload) in enumerate(items, start=1):
        draft = TaskEventDraft.build(
            event_id=f"event:{sequence}",
            task_id=task_id,
            event_type=event_type,
            payload=payload,
            occurred_at=NOW,
            correlation_id="run:recovery",
            causation_id=causation_id,
        )
        events.append(TaskEvent(**draft.model_dump(), sequence=sequence))
        causation_id = draft.event_id
    return tuple(events)


def test_recovery_snapshot_counts_only_event_derived_facts() -> None:
    events = _events(
        (TaskEventType.RUN_STARTED, {"run": {"run_id": "run:recovery"}}),
        (TaskEventType.RUN_RESUMED, {"run": {"run_id": "run:recovery"}}),
        (TaskEventType.WAIT_REGISTERED, {"run": {"run_id": "run:recovery"}}),
        (TaskEventType.WAIT_SATISFIED, {"run": {"run_id": "run:recovery"}}),
        (TaskEventType.RUN_PLAN_REBOUND, {"run": {"run_id": "run:recovery"}}),
        (
            TaskEventType.ACTION_RECEIPT_RECORDED,
            {"receipt": {"idempotency_key": "run:recovery:read"}},
        ),
        (
            TaskEventType.ACTION_RECEIPT_RECORDED,
            {"receipt": {"idempotency_key": "run:recovery:read"}},
        ),
        (
            TaskEventType.ACTION_RECEIPT_RECORDED,
            {"receipt": {"idempotency_key": "run:recovery:apply"}},
        ),
        (
            TaskEventType.ACTION_COMPENSATED,
            {"compensation": {"status": "COMPENSATED"}},
        ),
        (
            TaskEventType.OUTCOME_OBSERVED,
            {"outcome": {"status": "NOT_MET", "run_id": "run:recovery"}},
        ),
    )

    snapshot = build_recovery_snapshot(events)

    assert snapshot.task_id == "task:recovery"
    assert snapshot.run_id == "run:recovery"
    assert snapshot.event_sequence == events[-1].sequence
    assert snapshot.run_resumed_count == 1
    assert snapshot.wait_registered_count == 1
    assert snapshot.signal_satisfied_count == 1
    assert snapshot.replan_count == 1
    assert snapshot.compensation_count == 1
    assert snapshot.action_receipt_count == 3
    assert snapshot.unique_logical_action_count == 2
    assert snapshot.outcome_status == "NOT_MET"


def test_recovery_snapshot_rejects_empty_or_mixed_task_stream() -> None:
    with pytest.raises(ValueError, match="at least one"):
        build_recovery_snapshot(())

    mixed = _events(
        (TaskEventType.RUN_STARTED, {"run": {"run_id": "run:recovery"}}),
    ) + _events(
        (TaskEventType.RUN_RESUMED, {"run": {"run_id": "run:other"}}),
        task_id="task:other",
    )
    with pytest.raises(ValueError, match="one task"):
        build_recovery_snapshot(mixed)
