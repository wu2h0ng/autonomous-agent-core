from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent_os_contracts import TaskEventDraft, TaskEventType
from agent_os_core import (
    ConcurrentWriteError,
    DuplicateEventError,
    EventStreamError,
    InMemoryTaskEventStore,
)


NOW = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)


def _draft(event_id: str, *, task_id: str = "task-1") -> TaskEventDraft:
    return TaskEventDraft.build(
        event_id=event_id,
        task_id=task_id,
        event_type=TaskEventType.TASK_CREATED,
        payload={"goal_id": "goal-1"},
        occurred_at=NOW,
    )


def test_append_assigns_monotonic_sequences() -> None:
    store = InMemoryTaskEventStore()

    first = store.append("task-1", expected_sequence=0, drafts=(_draft("event-1"),))
    second = store.append("task-1", expected_sequence=1, drafts=(_draft("event-2"),))

    assert [event.sequence for event in (*first, *second)] == [1, 2]
    assert store.read("task-1") == (*first, *second)


def test_append_rejects_stale_expected_sequence() -> None:
    store = InMemoryTaskEventStore()
    store.append("task-1", expected_sequence=0, drafts=(_draft("event-1"),))

    with pytest.raises(ConcurrentWriteError, match="expected sequence 0"):
        store.append("task-1", expected_sequence=0, drafts=(_draft("event-2"),))


def test_append_rejects_duplicate_event_id() -> None:
    store = InMemoryTaskEventStore()
    store.append("task-1", expected_sequence=0, drafts=(_draft("event-1"),))

    with pytest.raises(DuplicateEventError, match="event-1"):
        store.append("task-1", expected_sequence=1, drafts=(_draft("event-1"),))


def test_append_rejects_duplicate_event_ids_within_batch() -> None:
    store = InMemoryTaskEventStore()

    with pytest.raises(DuplicateEventError, match="event-1"):
        store.append(
            "task-1",
            expected_sequence=0,
            drafts=(_draft("event-1"), _draft("event-1")),
        )

    assert store.read("task-1") == ()


def test_append_rejects_draft_for_another_task() -> None:
    store = InMemoryTaskEventStore()

    with pytest.raises(EventStreamError, match="task-2"):
        store.append(
            "task-1",
            expected_sequence=0,
            drafts=(_draft("event-1", task_id="task-2"),),
        )


def test_read_returns_immutable_snapshot() -> None:
    store = InMemoryTaskEventStore()
    appended = store.append("task-1", expected_sequence=0, drafts=(_draft("event-1"),))

    snapshot = store.read("task-1")

    assert isinstance(snapshot, tuple)
    assert snapshot == appended
    assert store.read("missing") == ()


def test_event_payload_is_canonical_and_defensively_decoded() -> None:
    payload = {"b": 2, "a": {"value": 1}}
    draft = TaskEventDraft.build(
        event_id="event-1",
        task_id="task-1",
        event_type=TaskEventType.TASK_CREATED,
        payload=payload,
        occurred_at=NOW,
    )

    payload["a"]["value"] = 99
    decoded = draft.decoded_payload()
    decoded["a"]["value"] = 42

    assert draft.payload_json == '{"a":{"value":1},"b":2}'
    assert draft.decoded_payload() == {"a": {"value": 1}, "b": 2}
