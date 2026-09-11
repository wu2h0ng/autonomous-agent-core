"""M2 TUI headless controller: SurfaceClient protocol state machine.

Textual-free on purpose (frozen D2 boundary): the controller drives the
E1/E2/E3 substrate through the SurfaceClient port so the whole interaction
model — subscription-first streaming, gap frames, stall detection, durable
turn commits, operator-only permission modes, human-only approvals, honest
usage display — is hermetically testable without a terminal.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Literal, Protocol

from agent_os_contracts import (
    ApprovalDisposition,
    SurfaceBeginTurnResponse,
    SurfaceEventBatch,
    SurfaceSessionSnapshot,
    SurfaceStreamBatch,
    SurfaceStreamBinding,
    SurfaceStreamFrameKind,
    SurfaceStreamSubscription,
    SurfaceTurnResponse,
    TaskEventType,
    PermissionMode,
)

from apps.cli.surface_client import SurfaceStreamStaleError

MODE_ORDER: tuple[PermissionMode, ...] = (
    "ASK",
    "ACCEPT_READ_ONLY",
    "ACCEPT_IN_WORKSPACE",
)

STATUS_IDLE = "idle"
STATUS_STREAMING = "streaming"
STATUS_STALLED = "stalled"
STATUS_AWAITING_APPROVAL = "awaiting_approval"


@dataclass
class ChatMessage:
    role: str
    content: str
    interrupted: bool = False


class SurfaceClientPort(Protocol):
    """Narrow protocol surface the controller consumes."""

    def subscribe_stream(self, session_id: str) -> SurfaceStreamSubscription: ...

    def submit_turn(
        self,
        session_id: str,
        text: str,
        stream: SurfaceStreamBinding,
    ) -> SurfaceBeginTurnResponse: ...

    def stream_frames(
        self,
        session_id: str,
        *,
        stream_id: str,
        runtime_boot_id: str,
        after_sequence: int = 0,
        wait_ms: int = 0,
        last_event_id: int | None = None,
    ) -> SurfaceStreamBatch: ...

    def events(
        self,
        task_id: str,
        *,
        after_sequence: int = 0,
        wait_ms: int = 0,
    ) -> SurfaceEventBatch: ...

    def set_permission_mode(
        self,
        session_id: str,
        mode: PermissionMode,
        *,
        expected_event_sequence: int | None = None,
        idempotency_key: str | None = None,
    ) -> SurfaceSessionSnapshot: ...

    def get_session(self, session_id: str) -> SurfaceSessionSnapshot: ...

    def decide_approval(
        self,
        session_id: str,
        action_digest: str,
        disposition: Literal[ApprovalDisposition.APPROVE, ApprovalDisposition.REJECT],
        reason: str,
        *,
        expected_event_sequence: int | None = None,
        idempotency_key: str | None = None,
    ) -> SurfaceTurnResponse: ...


class TuiController:
    """Drives one TUI chat session over the SurfaceClient protocol."""

    def __init__(
        self,
        *,
        client: SurfaceClientPort,
        session_id: str,
        task_id: str,
        clock: Callable[[], float] = time.monotonic,
        stall_seconds: float = 30.0,
    ) -> None:
        self._client = client
        self.session_id = session_id
        self.task_id = task_id
        self._clock = clock
        self._stall_seconds = stall_seconds

        self.messages: list[ChatMessage] = []
        self.mode: PermissionMode = "ASK"
        self.status: str = STATUS_IDLE
        self.tokens_total = 0
        self.turns = 0
        self.pending_preview: str | None = None

        self._stream_id: str | None = None
        self._runtime_boot_id: str | None = None
        self._frame_cursor = 0
        self._durable_cursor = 0
        self._turn_id: str | None = None
        self._current: ChatMessage | None = None
        self._last_activity: float | None = None

    # -- turns ------------------------------------------------------------
    def submit(self, text: str) -> None:
        if not text.strip():
            raise ValueError("empty turn text")
        if self.status in {STATUS_STREAMING, STATUS_STALLED}:
            raise RuntimeError("one in-flight turn at a time")
        self.messages.append(ChatMessage(role="user", content=text))
        # E1 frozen order: subscribe first, then bind the turn to the stream.
        subscription = self._client.subscribe_stream(self.session_id)
        self._stream_id = subscription.stream_id
        self._runtime_boot_id = subscription.runtime_boot_id
        self._frame_cursor = 0
        response = self._client.submit_turn(
            self.session_id,
            text,
            SurfaceStreamBinding(
                runtime_boot_id=subscription.runtime_boot_id,
                stream_id=subscription.stream_id,
            ),
        )
        self._turn_id = response.turn_id
        self._current = None
        self._last_activity = self._clock()
        self.status = STATUS_STREAMING

    def poll_stream(self) -> None:
        """One incremental read: transient frames, then durable events."""
        if self.status not in {STATUS_STREAMING, STATUS_STALLED}:
            return
        assert self._stream_id is not None and self._runtime_boot_id is not None
        try:
            batch = self._client.stream_frames(
                self.session_id,
                stream_id=self._stream_id,
                runtime_boot_id=self._runtime_boot_id,
                after_sequence=self._frame_cursor,
            )
        except SurfaceStreamStaleError:
            # Generation gone: resubscribe, never replay; durable events
            # remain the recovery source for the committed turn.
            subscription = self._client.subscribe_stream(self.session_id)
            self._stream_id = subscription.stream_id
            self._runtime_boot_id = subscription.runtime_boot_id
            self._frame_cursor = 0
            self._drain_durable()
            return
        self._frame_cursor = batch.next_sequence
        for frame in batch.frames:
            self._last_activity = self._clock()
            if frame.kind is SurfaceStreamFrameKind.CHUNK:
                delta = str(frame.payload.get("delta") or "")
                if self._current is None:
                    self._current = ChatMessage(role="assistant", content="")
                    self.messages.append(self._current)
                self._current.content += delta
            elif frame.kind is SurfaceStreamFrameKind.GAP:
                if self._current is not None:
                    self._current.interrupted = True
            # STREAM_END: the durable turn commit stays authoritative.
        self._drain_durable()

    def _drain_durable(self) -> None:
        batch = self._client.events(self.task_id, after_sequence=self._durable_cursor)
        self._durable_cursor = batch.next_sequence
        for event in batch.events:
            if event.event_type is TaskEventType.SESSION_TURN_COMPLETED:
                payload = json.loads(event.payload_json)
                if payload.get("turn_id") != self._turn_id:
                    continue
                self.tokens_total += int(payload.get("total_tokens") or 0)
                self.turns += 1
                self.status = STATUS_IDLE
                self._current = None
                self._turn_id = None
            elif event.event_type is TaskEventType.SESSION_APPROVAL_PENDING:
                payload = json.loads(event.payload_json)
                self.pending_preview = str(payload.get("preview") or "")
                self.status = STATUS_AWAITING_APPROVAL

    def tick(self) -> None:
        """Stall detection: quiet stream beyond the frozen threshold."""
        if self.status != STATUS_STREAMING or self._last_activity is None:
            return
        if self._clock() - self._last_activity > self._stall_seconds:
            self.status = STATUS_STALLED

    # -- operator-only controls (E2) ---------------------------------------
    def cycle_mode(self) -> PermissionMode:
        index = MODE_ORDER.index(self.mode)
        return self.set_mode(MODE_ORDER[(index + 1) % len(MODE_ORDER)])

    def set_mode(self, mode: PermissionMode) -> PermissionMode:
        snapshot = self._client.set_permission_mode(
            self.session_id,
            mode,
            idempotency_key=f"tui-mode:{self.session_id}:{uuid.uuid4()}",
        )
        self.mode = snapshot.permission_mode
        return self.mode

    # -- human-only approval (E2: never auto) ------------------------------
    def approve(self, reason: str) -> None:
        self._decide(ApprovalDisposition.APPROVE, reason)

    def reject(self, reason: str) -> None:
        self._decide(ApprovalDisposition.REJECT, reason)

    def _decide(
        self,
        disposition: Literal[ApprovalDisposition.APPROVE, ApprovalDisposition.REJECT],
        reason: str,
    ) -> None:
        if self.status != STATUS_AWAITING_APPROVAL:
            raise RuntimeError("no pending approval")
        snapshot = self._client.get_session(self.session_id)
        if snapshot.pending_approval is None:
            raise RuntimeError("pending approval vanished")
        response = self._client.decide_approval(
            self.session_id,
            snapshot.pending_approval.action_digest,
            disposition,
            reason,
            idempotency_key=f"tui-decide:{self.session_id}:{uuid.uuid4()}",
        )
        self.pending_preview = None
        self.tokens_total += response.total_tokens
        self.turns += 1
        self.status = STATUS_IDLE
        self._current = None
        self._turn_id = None

    # -- display -----------------------------------------------------------
    def usage_line(self) -> str:
        # E3: token counts are exact; cost is honestly UNKNOWN — the surface
        # projection carries no pricing source, so no dollar figure may ever
        # appear here.
        return f"tokens {self.tokens_total} · cost UNKNOWN"

    def status_line(self) -> str:
        return f"[{self.mode}] {self.status}"
