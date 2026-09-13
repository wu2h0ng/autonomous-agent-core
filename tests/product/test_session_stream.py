"""E1 session-stream buffer tests (M2, test-first).

Frozen source: GC §E1 buffer/gap/consumer policy — bounded buffer per
session-stream; slow-consumer overflow disconnects instead of silently
dropping; gap frames are synthesized on the read path, never enqueued, and
cannot themselves be evicted; every cursor binds
(runtime_boot_id, stream_id, frame_sequence); stale generations fail typed
STREAM_GONE; cursors are not interchangeable across streams; same-generation
reconnect keeps the original stream_id.
"""

from __future__ import annotations

import pytest
from agent_os_contracts import SurfaceStreamFrameKind

from agent_os_core import (
    SessionStreamRegistry,
    StreamCursor,
    SurfaceStreamGone,
)


@pytest.fixture
def registry() -> SessionStreamRegistry:
    return SessionStreamRegistry(runtime_boot_id="boot-1")


def _publish(
    registry: SessionStreamRegistry,
    stream_id: str,
    count: int,
    *,
    turn_id: str = "turn-1",
) -> list[int]:
    sequences = []
    for _ in range(count):
        frame = registry.publish(
            "sess-1", stream_id, SurfaceStreamFrameKind.CHUNK, turn_id, {"delta": "x"}
        )
        sequences.append(frame.frame_sequence)
    return sequences


class TestPublishAndRead:
    def test_read_from_zero_returns_contiguous_frames(
        self, registry: SessionStreamRegistry
    ) -> None:
        stream_id = registry.subscribe("sess-1")
        _publish(registry, stream_id, 3)
        frames = registry.read("sess-1", StreamCursor("boot-1", stream_id, 0))
        assert [f.frame_sequence for f in frames] == [1, 2, 3]
        assert all(f.kind is SurfaceStreamFrameKind.CHUNK for f in frames)

    def test_read_from_cursor_returns_only_newer_frames(
        self, registry: SessionStreamRegistry
    ) -> None:
        stream_id = registry.subscribe("sess-1")
        _publish(registry, stream_id, 3)
        frames = registry.read("sess-1", StreamCursor("boot-1", stream_id, 2))
        assert [f.frame_sequence for f in frames] == [3]


class TestGapSynthesis:
    def test_gap_synthesized_when_cursor_below_earliest_retained(
        self, registry: SessionStreamRegistry
    ) -> None:
        stream_id = registry.subscribe("sess-1")
        registry.configure_buffer("sess-1", stream_id, capacity=3)
        _publish(registry, stream_id, 5)
        frames = registry.read("sess-1", StreamCursor("boot-1", stream_id, 0))
        assert frames[0].kind is SurfaceStreamFrameKind.GAP
        assert frames[0].gap_from == 1
        assert frames[0].gap_to == 2
        assert [f.frame_sequence for f in frames[1:]] == [3, 4, 5]

    def test_gap_frames_are_never_buffer_residents(
        self, registry: SessionStreamRegistry
    ) -> None:
        stream_id = registry.subscribe("sess-1")
        registry.configure_buffer("sess-1", stream_id, capacity=2)
        _publish(registry, stream_id, 5)
        registry.read("sess-1", StreamCursor("boot-1", stream_id, 0))
        assert registry.retained_sequences("sess-1", stream_id) == [4, 5]
        # A second read from the same old cursor synthesizes the gap again:
        # the gap frame was never stored.
        again = registry.read("sess-1", StreamCursor("boot-1", stream_id, 0))
        assert again[0].kind is SurfaceStreamFrameKind.GAP
        assert again[0].gap_from == 1 and again[0].gap_to == 3

    def test_no_silent_holes_after_overflow(
        self, registry: SessionStreamRegistry
    ) -> None:
        stream_id = registry.subscribe("sess-1")
        registry.configure_buffer("sess-1", stream_id, capacity=2)
        _publish(registry, stream_id, 6)
        frames = registry.read("sess-1", StreamCursor("boot-1", stream_id, 0))
        gap = frames[0]
        assert gap.kind is SurfaceStreamFrameKind.GAP
        assert gap.gap_from == 1 and gap.gap_to == 4
        live = [f.frame_sequence for f in frames[1:]]
        assert live == [5, 6]
        assert live == list(range(gap.gap_to + 1, gap.gap_to + 1 + len(live)))


class TestSlowConsumerDisconnect:
    def test_overflow_marks_stream_disconnected(
        self, registry: SessionStreamRegistry
    ) -> None:
        stream_id = registry.subscribe("sess-1")
        registry.configure_buffer("sess-1", stream_id, capacity=2)
        _publish(registry, stream_id, 3)
        assert registry.is_disconnected("sess-1", stream_id) is True

    def test_within_watermark_stays_connected(
        self, registry: SessionStreamRegistry
    ) -> None:
        stream_id = registry.subscribe("sess-1")
        registry.configure_buffer("sess-1", stream_id, capacity=2)
        _publish(registry, stream_id, 2)
        assert registry.is_disconnected("sess-1", stream_id) is False


class TestGenerationAndCursorBinding:
    def test_stale_generation_cursor_fails_stream_gone(
        self, registry: SessionStreamRegistry
    ) -> None:
        stream_id = registry.subscribe("sess-1")
        _publish(registry, stream_id, 1)
        with pytest.raises(SurfaceStreamGone):
            registry.read("sess-1", StreamCursor("boot-0", stream_id, 0))

    def test_cursors_not_interchangeable_across_streams(
        self, registry: SessionStreamRegistry
    ) -> None:
        stream_a = registry.subscribe("sess-1")
        stream_b = registry.subscribe("sess-1")
        _publish(registry, stream_a, 1)
        with pytest.raises(SurfaceStreamGone):
            registry.read("sess-1", StreamCursor("boot-1", stream_a, 0), stream_id=stream_b)

    def test_same_generation_reconnect_keeps_stream_id(
        self, registry: SessionStreamRegistry
    ) -> None:
        stream_id = registry.subscribe("sess-1")
        _publish(registry, stream_id, 2)
        reconnected = registry.reconnect("sess-1", StreamCursor("boot-1", stream_id, 1))
        assert reconnected.stream_id == stream_id
        frames = registry.read("sess-1", reconnected)
        assert [f.frame_sequence for f in frames] == [2]

    def test_new_subscription_mints_new_stream_id(
        self, registry: SessionStreamRegistry
    ) -> None:
        first = registry.subscribe("sess-1")
        second = registry.subscribe("sess-1")
        assert first != second
