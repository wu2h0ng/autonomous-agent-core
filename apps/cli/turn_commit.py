"""E1 bounded stall detection over the durable projection (M2).

Frozen source: GC §E1 — after a transient `stream_end`, a turn finalizes only
from durable truth. If no durable commit arrives within a bounded threshold,
the consumer renders the single typed state `STALLED_PENDING_DURABLE_STATE`:
a transient client state, never a durable Task event, never inferred
completion, overruled only by the durable projection. The threshold is
finite, positive, configurable and test-injectable (30s named default).
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal, Protocol

from agent_os_contracts import TaskEventType
from agent_os_core import STALL_THRESHOLD_DEFAULT_SECONDS

STALLED_PENDING_DURABLE_STATE = "STALLED_PENDING_DURABLE_STATE"
"""The single typed stall state; a transient client state only."""

TurnCommitOutcome = Literal["COMMITTED", "STALLED_PENDING_DURABLE_STATE"]


class _DurableReader(Protocol):
    """The minimal durable-read surface the watcher needs (duck-typed so the
    clock/sleeper/events are all test-injectable)."""

    def get_session(self, session_id: str) -> Any: ...

    def events(self, task_id: str, **kwargs: Any) -> Any: ...


def _open_turn_ids(events: Any) -> set[str]:
    started: set[str] = set()
    completed: set[str] = set()
    for event in events:
        try:
            payload = json.loads(event.payload_json)
        except (TypeError, ValueError):
            continue
        turn_id = payload.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id:
            continue
        if event.event_type is TaskEventType.SESSION_TURN_STARTED:
            started.add(turn_id)
        elif event.event_type is TaskEventType.SESSION_TURN_COMPLETED:
            completed.add(turn_id)
    return started - completed


def await_turn_commit(
    client: _DurableReader,
    session_id: str,
    *,
    stall_threshold_seconds: float = STALL_THRESHOLD_DEFAULT_SECONDS,
    poll_interval_seconds: float = 0.5,
    clock: Any = time.monotonic,
    sleeper: Any = time.sleep,
) -> TurnCommitOutcome:
    """Poll durable truth until the session's open turn commits or the
    bounded stall threshold renders `STALLED_PENDING_DURABLE_STATE`.

    Never inspects transient stream frames: completion is only ever derived
    from the durable projection (SESSION_TURN_STARTED without its
    SESSION_TURN_COMPLETED stays open).
    """
    if stall_threshold_seconds <= 0:
        raise ValueError("stall threshold must be positive")
    if poll_interval_seconds <= 0:
        raise ValueError("poll interval must be positive")
    snapshot = client.get_session(session_id)
    task_id = snapshot.session.task_id
    deadline = clock() + stall_threshold_seconds
    while True:
        batch = client.events(task_id)
        if not _open_turn_ids(batch.events):
            return "COMMITTED"
        remaining = deadline - clock()
        if remaining <= 0:
            return STALLED_PENDING_DURABLE_STATE
        sleeper(min(poll_interval_seconds, remaining))
