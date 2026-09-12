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
from typing import Any, Callable, Literal, Protocol

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


TodoItem = dict[str, str]


@dataclass
class ActivityItem:
    action_id: str
    capability_id: str
    status: str
    preview: str = ""


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
        self.todos: list[TodoItem] = []
        self.activity: list[ActivityItem] = []

        self._stream_id: str | None = None
        self._runtime_boot_id: str | None = None
        self._frame_cursor = 0
        self._durable_cursor = 0
        self._turn_id: str | None = None
        self._current: ChatMessage | None = None
        self._last_activity: float | None = None
        self._completed_outputs: dict[str, dict[str, Any]] = {}
        self._pending_turn_completions: dict[str, tuple[int, str]] = {}
        self._activity_by_action: dict[str, ActivityItem] = {}

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
        self._apply_pending_turn_completion()

    def refresh_events(self) -> None:
        """Refresh non-streaming side panels from the durable task event log."""
        self._drain_durable()

    def _drain_durable(self) -> None:
        batch = self._client.events(self.task_id, after_sequence=self._durable_cursor)
        self._durable_cursor = batch.next_sequence
        for event in batch.events:
            if event.event_type is TaskEventType.ACTION_PROPOSED:
                payload = json.loads(event.payload_json)
                self._record_activity_proposed(payload)
            elif event.event_type is TaskEventType.SESSION_TURN_COMPLETED:
                payload = json.loads(event.payload_json)
                turn_id = payload.get("turn_id")
                if not isinstance(turn_id, str):
                    continue
                if turn_id != self._turn_id:
                    self._pending_turn_completions[turn_id] = (
                        int(payload.get("total_tokens") or 0),
                        str(payload.get("stop_reason") or "completed"),
                    )
                    continue
                self._complete_turn(total_tokens=int(payload.get("total_tokens") or 0))
            elif event.event_type is TaskEventType.SESSION_APPROVAL_PENDING:
                payload = json.loads(event.payload_json)
                self.pending_preview = str(payload.get("preview") or "")
                self.status = STATUS_AWAITING_APPROVAL
                self._record_activity_pending(payload)
            elif event.event_type is TaskEventType.NODE_COMPLETED:
                payload = json.loads(event.payload_json)
                action_id = payload.get("action_id")
                output = payload.get("output")
                if isinstance(action_id, str) and isinstance(output, dict):
                    self._completed_outputs[action_id] = output
            elif event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED:
                payload = json.loads(event.payload_json)
                self._record_activity_receipt(payload)
                self._apply_todo_receipt(payload)

    def _record_activity_proposed(self, payload: dict[str, Any]) -> None:
        action = payload.get("action")
        if not isinstance(action, dict):
            return
        action_id = action.get("action_id")
        capability_id = action.get("capability_id")
        if not isinstance(action_id, str) or not isinstance(capability_id, str):
            return
        self._upsert_activity(
            ActivityItem(
                action_id=action_id,
                capability_id=capability_id,
                status="proposed",
            )
        )

    def _record_activity_pending(self, payload: dict[str, Any]) -> None:
        action_digest = payload.get("action_digest")
        capability_id = payload.get("capability_id")
        proposal_id = payload.get("proposal_id")
        preview = payload.get("preview")
        if not isinstance(capability_id, str):
            return
        self._upsert_activity(
            ActivityItem(
                action_id=(
                    action_digest
                    if isinstance(action_digest, str)
                    else str(proposal_id or capability_id)
                ),
                capability_id=capability_id,
                status="waiting approval",
                preview=preview if isinstance(preview, str) else "",
            )
        )

    def _record_activity_receipt(self, payload: dict[str, Any]) -> None:
        receipt = payload.get("receipt")
        if not isinstance(receipt, dict):
            return
        action_id = receipt.get("action_id")
        capability_id = receipt.get("connector_id")
        status = receipt.get("status")
        if not isinstance(action_id, str) or not isinstance(capability_id, str):
            return
        rendered_status = "succeeded" if status == "SUCCEEDED" else "failed"
        existing = self._activity_by_action.get(action_id)
        self._upsert_activity(
            ActivityItem(
                action_id=action_id,
                capability_id=capability_id,
                status=rendered_status,
                preview=existing.preview if existing is not None else "",
            )
        )

    def _upsert_activity(self, item: ActivityItem) -> None:
        existing = self._activity_by_action.get(item.action_id)
        self._activity_by_action[item.action_id] = item
        if existing is None:
            self.activity.append(item)
            return
        for index, current in enumerate(self.activity):
            if current.action_id == item.action_id:
                self.activity[index] = item
                return

    def _apply_todo_receipt(self, payload: dict[str, Any]) -> None:
        receipt = payload.get("receipt")
        if not isinstance(receipt, dict):
            return
        if (
            receipt.get("connector_id") != "session.todo_write"
            or receipt.get("status") != "SUCCEEDED"
        ):
            return
        action_id = receipt.get("action_id")
        if not isinstance(action_id, str):
            return
        output = self._completed_outputs.get(action_id)
        if output is None:
            return
        todos = _todo_output(output)
        if todos is not None:
            self.todos = todos

    def _apply_pending_turn_completion(self) -> None:
        if self._turn_id is None:
            return
        pending = self._pending_turn_completions.pop(self._turn_id, None)
        if pending is None:
            return
        total_tokens, _stop_reason = pending
        self._complete_turn(total_tokens=total_tokens)

    def _complete_turn(self, *, total_tokens: int) -> None:
        self.tokens_total += total_tokens
        self.turns += 1
        self.status = STATUS_IDLE
        self._current = None
        self._turn_id = None

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
        # Refresh the tracked event sequence first: the controller learns
        # durable progress through events(), which does not advance the
        # client's per-session sequence cursor used by typed commands.
        fresh = self._client.get_session(self.session_id)
        self.mode = fresh.permission_mode
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


def _todo_output(output: dict[str, Any]) -> list[TodoItem] | None:
    if output.get("ok") is not True:
        return None
    raw_todos = output.get("todos")
    if not isinstance(raw_todos, list):
        return None
    todos: list[TodoItem] = []
    for item in raw_todos:
        if not isinstance(item, dict):
            return None
        identifier = item.get("id")
        content = item.get("content")
        status = item.get("status")
        if (
            not isinstance(identifier, str)
            or not isinstance(content, str)
            or status not in {"pending", "in_progress", "done"}
        ):
            return None
        todos.append({"id": identifier, "content": content, "status": status})
    if output.get("count") != len(todos):
        return None
    return todos
