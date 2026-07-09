from __future__ import annotations

from collections.abc import Sequence
from threading import RLock
from typing import Protocol

from agent_os_contracts import TaskEvent, TaskEventDraft

from .errors import ConcurrentWriteError, DuplicateEventError, EventStreamError


class TaskEventStore(Protocol):
    def read(self, task_id: str) -> tuple[TaskEvent, ...]: ...

    def append(
        self,
        task_id: str,
        *,
        expected_sequence: int,
        drafts: Sequence[TaskEventDraft],
    ) -> tuple[TaskEvent, ...]: ...


class InMemoryTaskEventStore:
    """Port adapter for tests/local composition; not a durability implementation."""

    def __init__(self) -> None:
        self._streams: dict[str, list[TaskEvent]] = {}
        self._event_ids: set[str] = set()
        self._lock = RLock()

    def read(self, task_id: str) -> tuple[TaskEvent, ...]:
        with self._lock:
            return tuple(self._streams.get(task_id, ()))

    def append(
        self,
        task_id: str,
        *,
        expected_sequence: int,
        drafts: Sequence[TaskEventDraft],
    ) -> tuple[TaskEvent, ...]:
        if not drafts:
            raise EventStreamError("append requires at least one event draft")
        with self._lock:
            stream = self._streams.setdefault(task_id, [])
            actual_sequence = len(stream)
            if actual_sequence != expected_sequence:
                raise ConcurrentWriteError(
                    f"expected sequence {expected_sequence}, actual {actual_sequence}"
                )
            batch_event_ids: set[str] = set()
            for draft in drafts:
                if draft.task_id != task_id:
                    raise EventStreamError(
                        f"event {draft.event_id} belongs to {draft.task_id}, not {task_id}"
                    )
                if (
                    draft.event_id in self._event_ids
                    or draft.event_id in batch_event_ids
                ):
                    raise DuplicateEventError(f"duplicate event id: {draft.event_id}")
                batch_event_ids.add(draft.event_id)

            appended = tuple(
                TaskEvent(**draft.model_dump(), sequence=expected_sequence + offset)
                for offset, draft in enumerate(drafts, start=1)
            )
            stream.extend(appended)
            self._event_ids.update(event.event_id for event in appended)
            return appended
