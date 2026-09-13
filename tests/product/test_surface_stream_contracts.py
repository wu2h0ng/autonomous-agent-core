"""E1 transient-stream contract tests (M2, test-first).

Frozen source: GC §E1 — chunks are transient display events, never durable Task
events; every frame binds (runtime_boot_id, stream_id, turn_id,
frame_sequence); begin-turn is the only turn_id source.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    SurfaceBeginTurnCommand,
    SurfaceBeginTurnResponse,
    SurfaceClientRef,
    SurfaceStreamBinding,
    SurfaceStreamFrame,
    SurfaceStreamFrameKind,
)


def _client() -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="tui-1",
        client_type="CLI",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        device_id="device:local",
    )


def _binding() -> SurfaceStreamBinding:
    return SurfaceStreamBinding(runtime_boot_id="boot-1", stream_id="stream-1")


def _begin_turn(**overrides: object) -> SurfaceBeginTurnCommand:
    values: dict[str, object] = {
        "protocol_version": SURFACE_PROTOCOL_VERSION,
        "client": _client(),
        "session_id": "sess-1",
        "text": "edit the file",
        "stream": _binding(),
        "expected_event_sequence": 0,
        "idempotency_key": "key-1",
        "requested_at": datetime.now(timezone.utc),
    }
    values.update(overrides)
    return SurfaceBeginTurnCommand(**values)  # type: ignore[arg-type]


class TestStreamBinding:
    def test_binding_requires_non_empty_boot_id_and_stream_id(self) -> None:
        with pytest.raises(ValidationError):
            SurfaceStreamBinding(runtime_boot_id="", stream_id="stream-1")
        with pytest.raises(ValidationError):
            SurfaceStreamBinding(runtime_boot_id="boot-1", stream_id="  ")


class TestBeginTurnCommand:
    def test_valid_command_constructs(self) -> None:
        command = _begin_turn()
        assert command.stream.runtime_boot_id == "boot-1"
        assert command.stream.stream_id == "stream-1"

    def test_client_never_mints_turn_id(self) -> None:
        command = _begin_turn()
        assert not hasattr(command, "turn_id")

    def test_command_requires_stream_binding(self) -> None:
        with pytest.raises(ValidationError):
            _begin_turn(stream=None)

    def test_replay_equality_same_digest_inputs(self) -> None:
        at = datetime.now(timezone.utc)
        first = _begin_turn(requested_at=at)
        second = _begin_turn(requested_at=at)
        assert first.model_dump(mode="json") == second.model_dump(mode="json")


class TestBeginTurnResponse:
    def test_response_carries_authoritative_ids(self) -> None:
        response = SurfaceBeginTurnResponse(turn_id="turn-1", stream_id="stream-1")
        assert response.turn_id == "turn-1"
        assert response.stream_id == "stream-1"

    def test_response_ids_are_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            SurfaceBeginTurnResponse(turn_id="", stream_id="stream-1")
        with pytest.raises(ValidationError):
            SurfaceBeginTurnResponse(turn_id="turn-1", stream_id="")


class TestStreamFrame:
    def _frame(self, **overrides: object) -> SurfaceStreamFrame:
        values: dict[str, object] = {
            "kind": SurfaceStreamFrameKind.CHUNK,
            "runtime_boot_id": "boot-1",
            "stream_id": "stream-1",
            "turn_id": "turn-1",
            "frame_sequence": 1,
            "payload": {"delta": "hel"},
        }
        values.update(overrides)
        return SurfaceStreamFrame(**values)  # type: ignore[arg-type]

    def test_chunk_requires_turn_binding(self) -> None:
        with pytest.raises(ValidationError):
            self._frame(turn_id=None)

    def test_every_frame_carries_four_part_binding(self) -> None:
        frame = self._frame()
        assert frame.runtime_boot_id == "boot-1"
        assert frame.stream_id == "stream-1"
        assert frame.turn_id == "turn-1"
        assert frame.frame_sequence == 1

    def test_frame_sequence_is_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            self._frame(frame_sequence=-1)

    def test_gap_frame_carries_gap_range(self) -> None:
        gap = self._frame(
            kind=SurfaceStreamFrameKind.GAP,
            turn_id=None,
            gap_from=4,
            gap_to=7,
        )
        assert gap.gap_from == 4
        assert gap.gap_to == 7

    def test_gap_frame_requires_gap_range(self) -> None:
        with pytest.raises(ValidationError):
            self._frame(kind=SurfaceStreamFrameKind.GAP, turn_id=None)

    def test_gap_range_must_be_ordered(self) -> None:
        with pytest.raises(ValidationError):
            self._frame(
                kind=SurfaceStreamFrameKind.GAP,
                turn_id=None,
                gap_from=7,
                gap_to=4,
            )

    def test_stream_end_closes_a_turn(self) -> None:
        with pytest.raises(ValidationError):
            self._frame(kind=SurfaceStreamFrameKind.STREAM_END, turn_id=None)

    def test_chunk_is_never_a_durable_task_event(self) -> None:
        from agent_os_contracts import TaskEvent

        assert not issubclass(SurfaceStreamFrame, TaskEvent)
