from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from agent_os_contracts import (
    ActionContract,
    PendingSurfaceApproval,
    ProviderMessage,
    ProviderMessageRole,
    ProviderToolProposal,
    SessionRef,
    TaskEvent,
    TaskEventType,
)

from .errors import AgentOSCoreError
from .event_store import TaskEventStore


class SessionProjectionError(AgentOSCoreError):
    """The durable session event stream cannot be projected safely."""


@dataclass(frozen=True)
class ProjectedSession:
    ref: SessionRef
    envelope_id: str
    expected_outcome_id: str
    history: tuple[ProviderMessage, ...]
    next_message_index: int
    opened_sequence: int
    last_sequence: int
    closed: bool
    pending_approval: PendingSurfaceApproval | None


class SessionProjector:
    def __init__(self, event_store: TaskEventStore) -> None:
        self._event_store = event_store

    def project(self, task_id: str, session_id: str) -> ProjectedSession:
        if not task_id.strip() or not session_id.strip():
            raise SessionProjectionError("task_id and session_id must be non-empty")
        events = self._event_store.read(task_id)
        session_events: list[TaskEvent] = []
        for event in events:
            try:
                payload = event.decoded_payload()
            except (TypeError, ValueError) as exc:
                raise SessionProjectionError(
                    f"invalid event payload at sequence {event.sequence}: {exc}"
                ) from exc
            if payload.get("session_id") == session_id:
                session_events.append(event)
        if not session_events:
            raise SessionProjectionError("session not found")
        return _strict_project(tuple(session_events))


def _strict_project(events: Sequence[TaskEvent]) -> ProjectedSession:
    ref: SessionRef | None = None
    envelope_id: str | None = None
    expected_outcome_id: str | None = None
    opened_sequence: int | None = None
    last_sequence = 0
    closed = False
    history: list[ProviderMessage] = []
    pending_approval: PendingSurfaceApproval | None = None
    outstanding_tool_calls: dict[str, tuple[str, str]] = {}
    seen_tool_call_ids: set[str] = set()

    for event in events:
        try:
            payload = event.decoded_payload()
            _required_str(payload, "session_id")
            last_sequence = event.sequence

            if event.event_type is TaskEventType.SESSION_OPENED:
                if ref is not None:
                    raise SessionProjectionError("duplicate open for session")
                session = SessionRef.model_validate(payload["session"])
                _validate_open_scope(payload, session, event)
                ref = session
                envelope_id = _required_str(payload, "envelope_id")
                expected_outcome_id = _required_str(payload, "expected_outcome_id")
                opened_sequence = event.sequence
                continue

            if ref is None:
                raise SessionProjectionError("session event occurred before open")
            _validate_event_scope(payload, ref, event)

            if event.event_type is TaskEventType.SESSION_MESSAGE_RECORDED:
                if closed:
                    raise SessionProjectionError("message recorded after close")
                message_index = payload["message_index"]
                if (
                    isinstance(message_index, bool)
                    or not isinstance(message_index, int)
                    or message_index != len(history)
                ):
                    raise SessionProjectionError(
                        "session message indexes must be contiguous from zero"
                    )
                turn_id = payload.get("turn_id")
                if turn_id is not None and (
                    not isinstance(turn_id, str) or not turn_id.strip()
                ):
                    raise SessionProjectionError("invalid message turn binding")
                try:
                    message = ProviderMessage.model_validate(payload["message"])
                except (KeyError, ValidationError) as exc:
                    raise SessionProjectionError(f"invalid message payload: {exc}") from exc
                _apply_tool_binding(
                    message,
                    outstanding_tool_calls=outstanding_tool_calls,
                    seen_tool_call_ids=seen_tool_call_ids,
                )
                history.append(message)
                continue

            if event.event_type is TaskEventType.SESSION_APPROVAL_PENDING:
                if closed:
                    raise SessionProjectionError("approval recorded after close")
                if pending_approval is not None:
                    raise SessionProjectionError(
                        "more than one unresolved pending approval"
                    )
                pending_approval = _project_pending_approval(
                    payload,
                    ref=ref,
                    envelope_id=envelope_id,
                    expected_outcome_id=expected_outcome_id,
                    history=history,
                    outstanding_tool_calls=outstanding_tool_calls,
                )
                continue

            if event.event_type is TaskEventType.SESSION_CLOSED:
                if closed:
                    raise SessionProjectionError("duplicate close for session")
                if pending_approval is not None:
                    raise SessionProjectionError(
                        "cannot close with an unresolved pending approval"
                    )
                closed = True
                continue

            if event.event_type in {
                TaskEventType.SESSION_TURN_STARTED,
                TaskEventType.SESSION_TURN_COMPLETED,
            }:
                if closed:
                    raise SessionProjectionError("session event recorded after close")
                continue

            raise SessionProjectionError(
                f"unsupported session event: {event.event_type.value}"
            )
        except SessionProjectionError:
            raise
        except (KeyError, TypeError, ValidationError, ValueError) as exc:
            raise SessionProjectionError(
                f"invalid {event.event_type.value} payload: {exc}"
            ) from exc

    if (
        ref is None
        or envelope_id is None
        or expected_outcome_id is None
        or opened_sequence is None
    ):
        raise SessionProjectionError("session open event is missing")
    return ProjectedSession(
        ref=ref,
        envelope_id=envelope_id,
        expected_outcome_id=expected_outcome_id,
        history=tuple(history),
        next_message_index=len(history),
        opened_sequence=opened_sequence,
        last_sequence=last_sequence,
        closed=closed,
        pending_approval=pending_approval,
    )


def _required_str(payload: Mapping[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise SessionProjectionError(f"{key} must be a non-empty string")
    return value


def _validate_event_scope(
    payload: Mapping[str, Any],
    ref: SessionRef,
    event: TaskEvent,
) -> None:
    if event.task_id != ref.task_id or payload.get("session_id") != ref.session_id:
        raise SessionProjectionError("session scope mismatch")
    expected = {
        "task_id": ref.task_id,
        "run_id": ref.run_id,
        "tenant_id": ref.tenant_id,
        "workspace_id": ref.workspace_id,
    }
    for key, expected_value in expected.items():
        if key in payload and payload[key] != expected_value:
            raise SessionProjectionError("session scope mismatch")
    if "session" in payload:
        session = SessionRef.model_validate(payload["session"])
        if session != ref:
            raise SessionProjectionError("session scope mismatch")


def _validate_open_scope(
    payload: Mapping[str, Any],
    session: SessionRef,
    event: TaskEvent,
) -> None:
    expected = {
        "session_id": session.session_id,
        "task_id": session.task_id,
        "run_id": session.run_id,
        "tenant_id": session.tenant_id,
        "workspace_id": session.workspace_id,
    }
    if event.task_id != session.task_id or any(
        payload.get(key) != expected_value for key, expected_value in expected.items()
    ):
        raise SessionProjectionError("session scope mismatch")


def _apply_tool_binding(
    message: ProviderMessage,
    *,
    outstanding_tool_calls: dict[str, tuple[str, str]],
    seen_tool_call_ids: set[str],
) -> None:
    if message.role is ProviderMessageRole.ASSISTANT:
        for tool_call in message.tool_calls:
            if tool_call.tool_call_id in seen_tool_call_ids:
                raise SessionProjectionError("duplicate provider tool binding")
            seen_tool_call_ids.add(tool_call.tool_call_id)
            outstanding_tool_calls[tool_call.tool_call_id] = (
                tool_call.capability_id,
                tool_call.arguments_json,
            )
        return
    if message.role is ProviderMessageRole.TOOL:
        if message.tool_call_id not in outstanding_tool_calls:
            raise SessionProjectionError("invalid provider tool binding")
        del outstanding_tool_calls[message.tool_call_id]


def _project_pending_approval(
    payload: Mapping[str, Any],
    *,
    ref: SessionRef,
    envelope_id: str | None,
    expected_outcome_id: str | None,
    history: Sequence[ProviderMessage],
    outstanding_tool_calls: Mapping[str, tuple[str, str]],
) -> PendingSurfaceApproval:
    action = ActionContract.model_validate(payload["action"])
    proposal = ProviderToolProposal.model_validate(payload["provider_proposal"])
    action_digest = _required_str(payload, "action_digest")
    if action.action_digest() != action_digest:
        raise SessionProjectionError("pending action digest mismatch")
    if (
        action.task_id != ref.task_id
        or action.run_id != ref.run_id
        or action.tenant_id != ref.tenant_id
        or action.workspace_id != ref.workspace_id
    ):
        raise SessionProjectionError("pending action scope mismatch")
    if (
        action.candidate_envelope_id != envelope_id
        or action.expected_outcome_id != expected_outcome_id
    ):
        raise SessionProjectionError("pending action session binding mismatch")
    if (
        proposal.capability_id != action.capability_id
        or proposal.arguments_json != action.arguments_json
    ):
        raise SessionProjectionError("pending action proposal binding mismatch")
    assistant_message_index = payload["assistant_message_index"]
    if (
        isinstance(assistant_message_index, bool)
        or not isinstance(assistant_message_index, int)
        or assistant_message_index < 0
        or assistant_message_index >= len(history)
    ):
        raise SessionProjectionError("pending approval assistant binding mismatch")
    assistant = history[assistant_message_index]
    matching_calls = tuple(
        call
        for call in assistant.tool_calls
        if call.tool_call_id == proposal.proposal_id
        and call.capability_id == proposal.capability_id
        and call.arguments_json == proposal.arguments_json
    )
    if (
        assistant.role is not ProviderMessageRole.ASSISTANT
        or len(matching_calls) != 1
        or proposal.proposal_id not in outstanding_tool_calls
    ):
        raise SessionProjectionError("pending approval provider tool binding mismatch")
    return PendingSurfaceApproval(
        action_digest=action_digest,
        capability_id=action.capability_id,
        proposal_id=proposal.proposal_id,
        preview=_required_str(payload, "preview"),
        requested_at=payload["requested_at"],
    )
