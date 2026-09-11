"""E1 transient session-stream registry (M2).

Frozen source: GC §E1 stream channel + buffer/gap/consumer policy. Frames are
transient display events bound to (runtime_boot_id, stream_id, turn_id,
frame_sequence); they are never durable Task events. Cursors bind
(runtime_boot_id, stream_id, frame_sequence). `runtime_boot_id` identifies the
daemon process generation: a stale generation fails typed `SurfaceStreamGone`
and can never collide with the new one. Buffers are bounded; overflow marks
the slow consumer disconnected instead of silently dropping frames; gap frames
are synthesized on the read path, never enqueued, and so cannot be evicted.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from threading import RLock
from uuid import uuid4

from agent_os_contracts import SurfaceStreamFrame, SurfaceStreamFrameKind

STALL_THRESHOLD_DEFAULT_SECONDS = 30.0
"""Bounded-stall default: a stream ending without a durable turn commit renders
the single typed `STALLED_PENDING_DURABLE_STATE` after this interval. Named
constant, configurable and test-injectable; never a durable Task event."""

DEFAULT_STREAM_BUFFER_CAPACITY = 1024


class SurfaceStreamGone(RuntimeError):
    """The referenced stream is dead: stale generation, unknown stream, or a
    cursor bound to a different stream_id."""


@dataclass(frozen=True)
class StreamCursor:
    """Transient cursor binding; never interchangeable across streams or
    generations."""

    runtime_boot_id: str
    stream_id: str
    frame_sequence: int


@dataclass
class _StreamState:
    buffer: deque[SurfaceStreamFrame] = field(default_factory=deque)
    capacity: int = DEFAULT_STREAM_BUFFER_CAPACITY
    next_sequence: int = 1
    disconnected: bool = False
    bound_turns: list[str] = field(default_factory=list)


class SessionStreamRegistry:
    """In-process transient stream authority for one daemon generation.

    All durable truth remains the Task event stream; this registry holds only
    display frames and dies with the process (a new generation carries a new
    `runtime_boot_id`, so stale cursors fail typed `SurfaceStreamGone`).
    """

    def __init__(self, runtime_boot_id: str) -> None:
        if not runtime_boot_id.strip():
            raise ValueError("runtime_boot_id must be non-empty")
        self._runtime_boot_id = runtime_boot_id
        self._streams: dict[tuple[str, str], _StreamState] = {}
        self._lock = RLock()

    @property
    def runtime_boot_id(self) -> str:
        return self._runtime_boot_id

    def subscribe(self, session_id: str) -> str:
        """Mint a new stream under the current generation (explicit new
        subscription; reconnections with a valid same-generation cursor keep
        the original stream_id)."""
        if not session_id.strip():
            raise ValueError("session_id must be non-empty")
        stream_id = uuid4().hex[:12]
        with self._lock:
            self._streams[(session_id, stream_id)] = _StreamState()
        return stream_id

    def configure_buffer(self, session_id: str, stream_id: str, capacity: int) -> None:
        if isinstance(capacity, bool) or capacity <= 0:
            raise ValueError("capacity must be a positive integer")
        with self._lock:
            state = self._require_stream(session_id, stream_id)
            state.capacity = capacity
            while len(state.buffer) > capacity:
                state.buffer.popleft()

    def is_live(self, session_id: str, runtime_boot_id: str, stream_id: str) -> bool:
        with self._lock:
            return (
                runtime_boot_id == self._runtime_boot_id
                and (session_id, stream_id) in self._streams
            )

    def publish(
        self,
        session_id: str,
        stream_id: str,
        kind: SurfaceStreamFrameKind,
        turn_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> SurfaceStreamFrame:
        """Append one transient frame, assigning the next frame_sequence.

        On overflow the oldest frame is evicted and the stream is marked
        disconnected (the SSE layer drops the slow consumer); readers of the
        evicted range receive synthesized gap frames, never silent holes.
        """
        with self._lock:
            state = self._require_stream(session_id, stream_id)
            frame = SurfaceStreamFrame(
                kind=kind,
                runtime_boot_id=self._runtime_boot_id,
                stream_id=stream_id,
                turn_id=turn_id,
                frame_sequence=state.next_sequence,
                payload=dict(payload or {}),
            )
            state.next_sequence += 1
            if len(state.buffer) >= state.capacity:
                state.buffer.popleft()
                state.disconnected = True
            state.buffer.append(frame)
            return frame

    def read(
        self,
        session_id: str,
        cursor: StreamCursor,
        stream_id: str | None = None,
    ) -> list[SurfaceStreamFrame]:
        """Read frames after the cursor, synthesizing a priority gap control
        frame when the cursor falls below the earliest retained sequence.
        Gap frames are synthesized here, never stored."""
        with self._lock:
            if cursor.runtime_boot_id != self._runtime_boot_id:
                raise SurfaceStreamGone(
                    "cursor generation is stale; resubscribe under the current boot"
                )
            target = stream_id or cursor.stream_id
            if target != cursor.stream_id:
                raise SurfaceStreamGone(
                    "cursors are not interchangeable across streams"
                )
            state = self._require_stream(session_id, target)
            retained = list(state.buffer)
            newer = [f for f in retained if f.frame_sequence > cursor.frame_sequence]
            if not newer:
                return []
            earliest = retained[0].frame_sequence
            if cursor.frame_sequence < earliest - 1:
                gap = SurfaceStreamFrame(
                    kind=SurfaceStreamFrameKind.GAP,
                    runtime_boot_id=self._runtime_boot_id,
                    stream_id=target,
                    turn_id=None,
                    frame_sequence=cursor.frame_sequence + 1,
                    gap_from=cursor.frame_sequence + 1,
                    gap_to=earliest - 1,
                    payload={},
                )
                return [gap, *newer]
            return newer

    def reconnect(self, session_id: str, cursor: StreamCursor) -> StreamCursor:
        """Validate a same-generation cursor and keep its stream_id."""
        with self._lock:
            if cursor.runtime_boot_id != self._runtime_boot_id:
                raise SurfaceStreamGone(
                    "cursor generation is stale; resubscribe under the current boot"
                )
            self._require_stream(session_id, cursor.stream_id)
            return StreamCursor(
                self._runtime_boot_id, cursor.stream_id, cursor.frame_sequence
            )

    def bind_turn(self, session_id: str, stream_id: str, turn_id: str) -> None:
        with self._lock:
            state = self._require_stream(session_id, stream_id)
            state.bound_turns.append(turn_id)

    def turns_bound(self, session_id: str, stream_id: str) -> list[str]:
        with self._lock:
            return list(self._require_stream(session_id, stream_id).bound_turns)

    def is_disconnected(self, session_id: str, stream_id: str) -> bool:
        with self._lock:
            return self._require_stream(session_id, stream_id).disconnected

    def retained_sequences(self, session_id: str, stream_id: str) -> list[int]:
        with self._lock:
            return [
                f.frame_sequence
                for f in self._require_stream(session_id, stream_id).buffer
            ]

    def _require_stream(self, session_id: str, stream_id: str) -> _StreamState:
        state = self._streams.get((session_id, stream_id))
        if state is None:
            raise SurfaceStreamGone(
                f"stream {stream_id!r} is not live for session {session_id!r}"
            )
        return state
