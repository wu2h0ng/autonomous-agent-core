"""M2 textual TUI headless controller tests (test-first).

The controller drives the SurfaceClient protocol (E1/E2/E3 substrate) with
no textual import, so the full interaction state machine is testable with a
hermetic fake client.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from agent_os_contracts import (
    SurfaceBeginTurnResponse,
    SurfaceStreamBatch,
    SurfaceStreamFrame,
    SurfaceStreamFrameKind,
    SurfaceStreamSubscription,
    SurfaceEventBatch,
    TaskEvent,
)

from apps.cli.tui_controller import (
    MODE_ORDER,
    ChatMessage,
    SurfaceStreamStaleError,
    TuiController,
)


class _FakeStreamClient:
    def __init__(self, frames: list[SurfaceStreamFrame] | None = None) -> None:
        self.frames = list(frames or [])
        self.durable_events: list[TaskEvent] = []
        self.mode_calls: list[str] = []
        self.approval_calls: list[tuple[str, str]] = []
        self._mode: Any = "ASK"
        self._pending: Any = None
        self.subscriptions = 0
        self.begun: list[str] = []
        self.durable_cursor = 0

    # -- port -----------------------------------------------------------
    def subscribe_stream(self, session_id: str) -> SurfaceStreamSubscription:
        assert session_id == "session:1"
        self.subscriptions += 1
        return SurfaceStreamSubscription(
            stream_id=f"stream-{self.subscriptions}",
            runtime_boot_id="boot:1",
        )

    def submit_turn(
        self,
        session_id: str,
        text: str,
        stream: Any,
    ) -> SurfaceBeginTurnResponse:
        assert session_id == "session:1"
        self.begun.append(text)
        return SurfaceBeginTurnResponse(turn_id="turn:1", stream_id=stream.stream_id)

    def stream_frames(
        self,
        session_id: str,
        *,
        stream_id: str,
        runtime_boot_id: str,
        after_sequence: int = 0,
        wait_ms: int = 0,
        last_event_id: int | None = None,
    ) -> SurfaceStreamBatch:
        del runtime_boot_id, wait_ms
        cursor = last_event_id if last_event_id is not None else after_sequence
        taken = [f for f in self.frames if f.frame_sequence > cursor]
        self.frames = self.frames[len(taken) :]
        next_cursor = taken[-1].frame_sequence if taken else cursor
        return SurfaceStreamBatch(
            session_id=session_id,
            after_sequence=cursor,
            next_sequence=next_cursor,
            frames=tuple(taken),
        )

    def events(
        self,
        task_id: str,
        *,
        after_sequence: int = 0,
        wait_ms: int = 0,
    ) -> SurfaceEventBatch:
        del wait_ms
        assert task_id == "task:1"
        taken = [e for e in self.durable_events if e.sequence > after_sequence]
        next_seq = taken[-1].sequence if taken else after_sequence
        return SurfaceEventBatch(
            protocol_version="1.1",
            task_id=task_id,
            after_sequence=after_sequence,
            next_sequence=next_seq,
            events=tuple(taken),
        )

    def set_permission_mode(self, session_id: str, mode: Any, **kwargs: Any) -> Any:
        assert session_id == "session:1"
        self.mode_calls.append(mode)
        self._mode = mode
        return self._snapshot()

    def get_session(self, session_id: str) -> Any:
        assert session_id == "session:1"
        return self._snapshot()

    def decide_approval(
        self,
        session_id: str,
        action_digest: str,
        disposition: Any,
        reason: str,
        **kwargs: Any,
    ) -> Any:
        assert session_id == "session:1"
        self.approval_calls.append((action_digest, disposition))
        self._pending = None
        return self._turn_response(total_tokens=9)

    # -- scripting helpers ----------------------------------------------
    def _snapshot(self) -> Any:
        from agent_os_contracts import (
            SessionRef,
            SurfaceSessionSnapshot,
            SurfaceSessionStatus,
        )

        return SurfaceSessionSnapshot(
            protocol_version="1.1",
            session=SessionRef(
                session_id="session:1",
                task_id="task:1",
                run_id="run:1",
                tenant_id="tenant:local",
                workspace_id="workspace:local",
            ),
            envelope_id="envelope:1",
            expected_outcome_id="expected:1",
            status=SurfaceSessionStatus.ACTIVE,
            event_sequence=1,
            message_count=2,
            pending_approval=self._pending,
            permission_mode=self._mode,
            updated_at=datetime.now(timezone.utc),
        )

    def _turn_response(self, total_tokens: int) -> Any:
        from agent_os_contracts import SurfaceTurnResponse

        return SurfaceTurnResponse(
            protocol_version="1.1",
            snapshot=self._snapshot(),
            turn_id="turn:1",
            text="done",
            stop_reason="completed",
            total_tokens=total_tokens,
        )

    def queue_turn_completed(
        self, total_tokens: int, stop_reason: str = "completed"
    ) -> None:
        self.durable_cursor += 1
        self.durable_events.append(
            _event(
                self.durable_cursor,
                "SESSION_TURN_COMPLETED",
                {
                    "turn_id": "turn:1",
                    "session_id": "session:1",
                    "stop_reason": stop_reason,
                    "steps": [],
                    "total_tokens": total_tokens,
                },
            )
        )

    def queue_approval_pending(self) -> None:
        from agent_os_contracts import PendingSurfaceApproval

        self.durable_cursor += 1
        self.durable_events.append(
            _event(
                self.durable_cursor,
                "SESSION_APPROVAL_PENDING",
                {
                    "action_digest": "digest:1",
                    "capability_id": "workspace.shell",
                    "proposal_id": "proposal:1",
                    "preview": "run: pytest",
                    "requested_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        )
        self._pending = PendingSurfaceApproval(
            action_digest="digest:1",
            capability_id="workspace.shell",
            proposal_id="proposal:1",
            preview="run: pytest",
            requested_at=datetime.now(timezone.utc),
        )


def _event(sequence: int, event_type: str, payload: dict[str, Any]) -> TaskEvent:
    from agent_os_contracts import TaskEventType

    return TaskEvent(
        sequence=sequence,
        event_id=f"event:{sequence}",
        task_id="task:1",
        event_type=TaskEventType[event_type],
        payload_json=json.dumps(payload),
        occurred_at=datetime.now(timezone.utc),
    )


def _frame(
    seq: int, kind: SurfaceStreamFrameKind, payload: dict[str, Any]
) -> SurfaceStreamFrame:
    return SurfaceStreamFrame(
        kind=kind,
        runtime_boot_id="boot:1",
        stream_id="stream-1",
        turn_id="turn:1",
        frame_sequence=seq,
        payload=payload,
    )


class _ManualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _controller(
    client: _FakeStreamClient, clock: _ManualClock | None = None
) -> TuiController:
    return TuiController(
        client=client,  # type: ignore[arg-type]
        session_id="session:1",
        task_id="task:1",
        clock=clock if clock is not None else _ManualClock(),
        stall_seconds=30.0,
    )


def test_submit_streams_deltas_and_commits_tokens() -> None:
    client = _FakeStreamClient(
        frames=[
            _frame(1, SurfaceStreamFrameKind.CHUNK, {"delta": "Hel"}),
            _frame(2, SurfaceStreamFrameKind.CHUNK, {"delta": "lo"}),
            _frame(3, SurfaceStreamFrameKind.STREAM_END, {}),
        ]
    )
    client.queue_turn_completed(total_tokens=42)
    clock = _ManualClock()
    controller = _controller(client, clock)

    controller.submit("say hello")
    assert controller.status == "streaming"
    assert client.subscriptions == 1  # subscription-first, then turn
    assert client.begun == ["say hello"]

    controller.poll_stream()
    assert controller.messages == [
        ChatMessage(role="user", content="say hello"),
        ChatMessage(role="assistant", content="Hello"),
    ]

    controller.poll_stream()  # drain durable turn commit
    assert controller.status == "idle"
    assert controller.tokens_total == 42
    assert controller.turns == 1
    assert "42" in controller.usage_line()


def test_gap_frame_marks_stream_interrupted() -> None:
    gap = SurfaceStreamFrame(
        kind=SurfaceStreamFrameKind.GAP,
        runtime_boot_id="boot:1",
        stream_id="stream-1",
        turn_id=None,
        frame_sequence=2,
        gap_from=1,
        gap_to=2,
    )
    client = _FakeStreamClient(
        frames=[
            _frame(1, SurfaceStreamFrameKind.CHUNK, {"delta": "Par"}),
            gap,
            _frame(3, SurfaceStreamFrameKind.STREAM_END, {}),
        ]
    )
    client.queue_turn_completed(total_tokens=5)
    controller = _controller(client)
    controller.submit("go")
    controller.poll_stream()
    assistant = controller.messages[-1]
    assert assistant.content == "Par"
    assert assistant.interrupted is True


def test_stall_detection_after_quiet_period() -> None:
    client = _FakeStreamClient(
        frames=[_frame(1, SurfaceStreamFrameKind.CHUNK, {"delta": "slow"})]
    )
    clock = _ManualClock()
    controller = _controller(client, clock)
    controller.submit("go")
    controller.poll_stream()
    assert controller.status == "streaming"

    clock.advance(31.0)
    controller.tick()
    assert controller.status == "stalled"
    assert "stalled" in controller.status_line().lower()


def test_mode_cycle_sends_operator_command() -> None:
    client = _FakeStreamClient()
    controller = _controller(client)
    assert controller.mode == "ASK"

    next_mode = controller.cycle_mode()
    assert next_mode == MODE_ORDER[1]
    assert client.mode_calls == [MODE_ORDER[1]]
    assert controller.mode == MODE_ORDER[1]
    assert controller.mode == "ACCEPT_READ_ONLY"


def test_approval_pending_waits_for_human_decision() -> None:
    client = _FakeStreamClient(
        frames=[_frame(1, SurfaceStreamFrameKind.STREAM_END, {})]
    )
    client.queue_approval_pending()
    controller = _controller(client)
    controller.submit("run tests")

    controller.poll_stream()
    assert controller.status == "awaiting_approval"
    assert controller.pending_preview == "run: pytest"
    # No auto-approval: the model can never answer for the human.
    assert client.approval_calls == []

    controller.approve(reason="yes, run it")
    assert client.approval_calls == [("digest:1", "APPROVE")]
    assert controller.status == "idle"
    assert controller.tokens_total == 9


def test_usage_line_never_shows_pseudo_zero_cost() -> None:
    client = _FakeStreamClient()
    controller = _controller(client)
    line = controller.usage_line()
    assert "UNKNOWN" in line
    assert "$0" not in line
    assert "0.00" not in line


def test_stream_stale_resubscribes_and_recovers_from_durable() -> None:
    class _StaleThenLive(_FakeStreamClient):
        stale_raises = 1

        def stream_frames(self, *args: Any, **kwargs: Any) -> SurfaceStreamBatch:
            if self.stale_raises > 0:
                self.stale_raises -= 1
                raise SurfaceStreamStaleError("generation gone")
            return super().stream_frames(*args, **kwargs)

    client = _StaleThenLive(frames=[_frame(1, SurfaceStreamFrameKind.STREAM_END, {})])
    client.queue_turn_completed(total_tokens=7)
    controller = _controller(client)
    controller.submit("go")

    controller.poll_stream()  # first read hits 410/stale
    assert client.subscriptions == 2  # resubscribed under the new generation
    controller.poll_stream()
    assert controller.status == "idle"
    assert controller.tokens_total == 7
