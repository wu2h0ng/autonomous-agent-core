from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from agent_os_contracts import (
    ActionContract,
    AgentRun,
    ApprovalDisposition,
    CorrectionEpochVector,
    PendingSurfaceApproval,
    ProviderMessage,
    ProviderMessageRole,
    ProviderToolProposal,
    RunStatus,
    SessionRef,
    TaskEvent,
    TaskEventType,
    content_digest,
)

from .errors import AgentOSCoreError
from .event_store import TaskEventStore


class SessionProjectionError(AgentOSCoreError):
    """The durable session event stream cannot be projected safely."""


@dataclass(frozen=True)
class SessionLoopConfig:
    max_steps_per_turn: int
    max_provider_retries: int
    max_turn_tokens: int
    max_context_chars: int
    loop_detection_threshold: int
    system_prompt: str

    def __post_init__(self) -> None:
        positive_limits = (
            self.max_steps_per_turn,
            self.max_turn_tokens,
            self.max_context_chars,
            self.loop_detection_threshold,
        )
        if any(type(value) is not int or value <= 0 for value in positive_limits):
            raise ValueError("session loop configuration limits must be positive")
        if (
            type(self.max_provider_retries) is not int
            or self.max_provider_retries < 0
        ):
            raise ValueError(
                "session loop provider retries must be a non-negative integer"
            )
        if not isinstance(self.system_prompt, str) or not self.system_prompt:
            raise ValueError("session loop system prompt must be non-empty")

    def payload(self) -> dict[str, object]:
        return {
            "max_steps_per_turn": self.max_steps_per_turn,
            "max_provider_retries": self.max_provider_retries,
            "max_turn_tokens": self.max_turn_tokens,
            "max_context_chars": self.max_context_chars,
            "loop_detection_threshold": self.loop_detection_threshold,
            "system_prompt": self.system_prompt,
        }

    def digest(self) -> str:
        return content_digest(self.payload())

    @classmethod
    def from_open_payload(cls, payload: Mapping[str, Any]) -> SessionLoopConfig:
        raw_config = payload.get("agent_loop_config")
        if not isinstance(raw_config, dict):
            raise SessionProjectionError("session configuration payload is missing")
        expected_keys = {
            "max_steps_per_turn",
            "max_provider_retries",
            "max_turn_tokens",
            "max_context_chars",
            "loop_detection_threshold",
            "system_prompt",
        }
        if set(raw_config) != expected_keys:
            raise SessionProjectionError("session configuration fields are invalid")
        try:
            config = cls(**raw_config)
        except (TypeError, ValueError) as exc:
            raise SessionProjectionError(
                f"session configuration values are invalid: {exc}"
            ) from exc
        if payload.get("agent_loop_config_digest") != config.digest():
            raise SessionProjectionError("session configuration digest mismatch")
        return config


@dataclass(frozen=True)
class ProjectedApprovalContinuation:
    action: ActionContract
    proposal: ProviderToolProposal
    preview: str
    turn_id: str
    assistant_message_index: int
    proposal_index: int
    steps: int
    total_tokens: int
    seen_action_digests: tuple[tuple[str, int], ...]
    configuration_snapshot_id: str
    configuration_snapshot_digest: str
    provider_profile_id: str
    provider_profile_digest: str
    requested_at: datetime

    @property
    def surface(self) -> PendingSurfaceApproval:
        return PendingSurfaceApproval(
            action_digest=self.action.action_digest(),
            capability_id=self.action.capability_id,
            proposal_id=self.proposal.proposal_id,
            preview=self.preview,
            requested_at=self.requested_at,
        )


@dataclass(frozen=True)
class ProjectedResolvedContinuation:
    """Exact durable cursor after an approval TOOL/resolution batch commits."""

    turn_id: str
    assistant_message_index: int
    assistant_message_digest: str
    next_proposal_index: int
    steps: int
    total_tokens: int
    seen_action_digests: tuple[tuple[str, int], ...]
    configuration_snapshot_id: str
    configuration_snapshot_digest: str
    provider_profile_id: str
    provider_profile_digest: str
    source_action_digest: str
    source_approval_id: str
    disposition: ApprovalDisposition
    tool_message_index: int
    resolved_at: datetime


@dataclass(frozen=True)
class ProjectedSession:
    ref: SessionRef
    envelope_id: str
    expected_outcome_id: str
    loop_config: SessionLoopConfig
    history: tuple[ProviderMessage, ...]
    next_message_index: int
    opened_sequence: int
    last_sequence: int
    closed: bool
    pending_approval: PendingSurfaceApproval | None
    pending_continuation: ProjectedApprovalContinuation | None
    resolved_continuation: ProjectedResolvedContinuation | None
    resumable_turn_id: str | None


class SessionProjector:
    def __init__(self, event_store: TaskEventStore) -> None:
        self._event_store = event_store

    def project(self, task_id: str, session_id: str) -> ProjectedSession:
        if not task_id.strip() or not session_id.strip():
            raise SessionProjectionError("task_id and session_id must be non-empty")
        events = self._event_store.read(task_id)
        session_events: list[TaskEvent] = []
        session_run_id: str | None = None
        for event in events:
            try:
                payload = event.decoded_payload()
            except (TypeError, ValueError) as exc:
                raise SessionProjectionError(
                    f"invalid event payload at sequence {event.sequence}: {exc}"
                ) from exc
            if payload.get("session_id") == session_id:
                session_events.append(event)
                if event.event_type is TaskEventType.SESSION_OPENED:
                    raw_session = payload.get("session")
                    if isinstance(raw_session, dict):
                        raw_run_id = raw_session.get("run_id")
                        if isinstance(raw_run_id, str):
                            session_run_id = raw_run_id
        if not session_events:
            raise SessionProjectionError("session not found")
        if session_run_id is not None:
            for event in events:
                if event.event_type is not TaskEventType.RUN_CANCELLED:
                    continue
                payload = event.decoded_payload()
                raw_run = payload.get("run")
                if (
                    isinstance(raw_run, dict)
                    and raw_run.get("run_id") == session_run_id
                ):
                    session_events.append(event)
        session_events.sort(key=lambda event: event.sequence)
        return _strict_project(tuple(session_events))


def _strict_project(events: Sequence[TaskEvent]) -> ProjectedSession:
    ref: SessionRef | None = None
    envelope_id: str | None = None
    expected_outcome_id: str | None = None
    loop_config: SessionLoopConfig | None = None
    opened_sequence: int | None = None
    last_sequence = 0
    closed = False
    run_cancelled = False
    history: list[ProviderMessage] = []
    pending_continuation: ProjectedApprovalContinuation | None = None
    resolved_continuation: ProjectedResolvedContinuation | None = None
    outstanding_tool_calls: dict[str, tuple[str, str]] = {}
    seen_tool_call_ids: set[str] = set()
    user_turns: dict[str, str] = {}
    started_turns: set[str] = set()
    completed_turns: set[str] = set()
    open_turn_id: str | None = None

    for event in events:
        try:
            payload = event.decoded_payload()
            last_sequence = event.sequence

            if event.event_type is TaskEventType.RUN_CANCELLED:
                if ref is None:
                    raise SessionProjectionError(
                        "session Run cancelled before session open"
                    )
                if set(payload) != {"run"}:
                    raise SessionProjectionError(
                        "session Run cancellation fields are invalid"
                    )
                cancelled_run = AgentRun.model_validate(payload["run"])
                if (
                    cancelled_run.status is not RunStatus.CANCELLED
                    or cancelled_run.task_id != ref.task_id
                    or cancelled_run.run_id != ref.run_id
                    or cancelled_run.tenant_id != ref.tenant_id
                    or cancelled_run.workspace_id != ref.workspace_id
                ):
                    raise SessionProjectionError(
                        "session Run cancellation binding mismatch"
                    )
                pending_continuation = None
                resolved_continuation = None
                outstanding_tool_calls.clear()
                open_turn_id = None
                run_cancelled = True
                continue

            _required_str(payload, "session_id")
            if run_cancelled:
                raise SessionProjectionError(
                    "session event recorded after Run cancellation"
                )

            if event.event_type is TaskEventType.SESSION_OPENED:
                if ref is not None:
                    raise SessionProjectionError("duplicate open for session")
                session = SessionRef.model_validate(payload["session"])
                _validate_open_scope(payload, session, event)
                ref = session
                envelope_id = _required_str(payload, "envelope_id")
                expected_outcome_id = _required_str(payload, "expected_outcome_id")
                loop_config = SessionLoopConfig.from_open_payload(payload)
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
                if message.role is ProviderMessageRole.SYSTEM:
                    if turn_id is not None:
                        raise SessionProjectionError(
                            "durable system message cannot have a turn binding"
                        )
                elif message.role is ProviderMessageRole.USER:
                    if turn_id is None:
                        raise SessionProjectionError(
                            "durable user message has invalid turn binding"
                        )
                    if turn_id in user_turns:
                        raise SessionProjectionError(
                            "durable turn has more than one user message"
                        )
                    if open_turn_id is not None:
                        raise SessionProjectionError(
                            "session has more than one open turn"
                        )
                    user_turns[turn_id] = message.content
                elif message.role in {
                    ProviderMessageRole.ASSISTANT,
                    ProviderMessageRole.TOOL,
                }:
                    if turn_id is None:
                        role = message.role.value.lower()
                        raise SessionProjectionError(
                            f"durable {role} message has invalid turn binding"
                        )
                    if turn_id != open_turn_id:
                        raise SessionProjectionError("session message turn mismatch")
                history.append(message)
                continue

            if event.event_type is TaskEventType.SESSION_APPROVAL_PENDING:
                if closed:
                    raise SessionProjectionError("approval recorded after close")
                if pending_continuation is not None:
                    raise SessionProjectionError(
                        "more than one unresolved pending approval"
                    )
                if open_turn_id is None:
                    raise SessionProjectionError(
                        "pending approval requires an exact open turn"
                    )
                next_pending = _project_pending_approval(
                    payload,
                    ref=ref,
                    envelope_id=envelope_id,
                    expected_outcome_id=expected_outcome_id,
                    history=history,
                    outstanding_tool_calls=outstanding_tool_calls,
                    open_turn_id=open_turn_id,
                )
                if resolved_continuation is not None:
                    if next_pending.turn_id != resolved_continuation.turn_id:
                        raise SessionProjectionError(
                            "pending approval does not supersede the resolved turn"
                        )
                    resolved_continuation = None
                pending_continuation = next_pending
                continue

            if event.event_type is TaskEventType.SESSION_APPROVAL_RESOLVED:
                if closed:
                    raise SessionProjectionError("approval resolved after close")
                if pending_continuation is None:
                    raise SessionProjectionError(
                        "approval resolution has no exact pending approval"
                    )
                resolved_continuation = _project_approval_resolution(
                    payload,
                    pending=pending_continuation,
                    history=history,
                    outstanding_tool_calls=outstanding_tool_calls,
                    open_turn_id=open_turn_id,
                )
                pending_continuation = None
                continue

            if event.event_type is TaskEventType.SESSION_CLOSED:
                if closed:
                    raise SessionProjectionError("duplicate close for session")
                if pending_continuation is not None:
                    raise SessionProjectionError(
                        "cannot close with an unresolved pending approval"
                    )
                if open_turn_id is not None:
                    raise SessionProjectionError("cannot close with an open turn")
                closed = True
                continue

            if event.event_type is TaskEventType.SESSION_TURN_STARTED:
                if closed:
                    raise SessionProjectionError("session event recorded after close")
                turn_id = _required_str(payload, "turn_id")
                user_text = _required_str(payload, "user_text")
                if turn_id in started_turns:
                    raise SessionProjectionError("duplicate session turn start")
                if user_turns.get(turn_id) != user_text:
                    raise SessionProjectionError(
                        "session turn start does not bind one exact user message"
                    )
                if open_turn_id is not None:
                    raise SessionProjectionError("session has more than one open turn")
                started_turns.add(turn_id)
                open_turn_id = turn_id
                continue

            if event.event_type is TaskEventType.SESSION_TURN_COMPLETED:
                if closed:
                    raise SessionProjectionError("session event recorded after close")
                turn_id = _required_str(payload, "turn_id")
                if pending_continuation is not None:
                    raise SessionProjectionError(
                        "cannot complete a turn with unresolved approval"
                    )
                if outstanding_tool_calls:
                    raise SessionProjectionError(
                        "cannot complete a turn with unanswered tool calls"
                    )
                if turn_id != open_turn_id or turn_id in completed_turns:
                    raise SessionProjectionError(
                        "session turn completion has no exact open turn"
                    )
                completed_turns.add(turn_id)
                open_turn_id = None
                resolved_continuation = None
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
        or loop_config is None
        or opened_sequence is None
    ):
        raise SessionProjectionError("session open event is missing")
    orphaned_user_turns = set(user_turns) - started_turns
    if orphaned_user_turns:
        raise SessionProjectionError(
            "durable user message has no matching turn start"
        )
    if (
        pending_continuation is not None
        and pending_continuation.proposal.proposal_id not in outstanding_tool_calls
    ):
        raise SessionProjectionError(
            "pending approval has a TOOL reply without an atomic resolution"
        )
    return ProjectedSession(
        ref=ref,
        envelope_id=envelope_id,
        expected_outcome_id=expected_outcome_id,
        loop_config=loop_config,
        history=tuple(history),
        next_message_index=len(history),
        opened_sequence=opened_sequence,
        last_sequence=last_sequence,
        closed=closed,
        pending_approval=(
            pending_continuation.surface
            if pending_continuation is not None
            else None
        ),
        pending_continuation=pending_continuation,
        resolved_continuation=resolved_continuation,
        resumable_turn_id=open_turn_id,
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
    open_turn_id: str,
) -> ProjectedApprovalContinuation:
    expected_fields = {
        "session_id",
        "task_id",
        "run_id",
        "tenant_id",
        "workspace_id",
        "turn_id",
        "provider_proposal",
        "action",
        "preview",
        "action_digest",
        "assistant_message_index",
        "proposal_index",
        "steps",
        "total_tokens",
        "seen_action_digests",
        "configuration_snapshot_id",
        "configuration_snapshot_digest",
        "provider_profile_id",
        "provider_profile_digest",
        "c7_epochs",
        "requested_at",
    }
    if set(payload) != expected_fields:
        raise SessionProjectionError("pending approval fields are invalid")
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
    proposal_index = _required_non_negative_int(payload, "proposal_index")
    if proposal_index >= len(assistant.tool_calls):
        raise SessionProjectionError("pending approval proposal index is invalid")
    bound_call = assistant.tool_calls[proposal_index]
    if (
        assistant.role is not ProviderMessageRole.ASSISTANT
        or bound_call.tool_call_id != proposal.proposal_id
        or bound_call.capability_id != proposal.capability_id
        or bound_call.arguments_json != proposal.arguments_json
        or proposal.proposal_id not in outstanding_tool_calls
    ):
        raise SessionProjectionError("pending approval provider tool binding mismatch")
    turn_id = _required_str(payload, "turn_id")
    if turn_id != open_turn_id:
        raise SessionProjectionError("pending approval turn binding mismatch")
    steps = _required_non_negative_int(payload, "steps")
    total_tokens = _required_non_negative_int(payload, "total_tokens")
    if steps <= 0:
        raise SessionProjectionError("pending approval step count must be positive")
    seen_value = payload["seen_action_digests"]
    if not isinstance(seen_value, dict):
        raise SessionProjectionError("pending approval loop state is invalid")
    seen: list[tuple[str, int]] = []
    for fingerprint, count in seen_value.items():
        if (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count <= 0
        ):
            raise SessionProjectionError("pending approval loop state is invalid")
        seen.append((fingerprint, count))
    expected_fingerprint = _proposal_fingerprint(proposal)
    if dict(seen).get(expected_fingerprint, 0) <= 0:
        raise SessionProjectionError("pending approval loop state omits proposal")
    try:
        c7_epochs = CorrectionEpochVector.model_validate(payload["c7_epochs"])
    except ValidationError as exc:
        raise SessionProjectionError("pending approval C7 epochs are invalid") from exc
    if c7_epochs != action.observed_correction_epochs:
        raise SessionProjectionError("pending approval C7 epoch mismatch")
    requested = PendingSurfaceApproval(
        action_digest=action_digest,
        capability_id=action.capability_id,
        proposal_id=proposal.proposal_id,
        preview=_required_str(payload, "preview"),
        requested_at=payload["requested_at"],
    ).requested_at
    return ProjectedApprovalContinuation(
        action=action,
        proposal=proposal,
        preview=_required_str(payload, "preview"),
        turn_id=turn_id,
        assistant_message_index=assistant_message_index,
        proposal_index=proposal_index,
        steps=steps,
        total_tokens=total_tokens,
        seen_action_digests=tuple(sorted(seen)),
        configuration_snapshot_id=_required_str(
            payload, "configuration_snapshot_id"
        ),
        configuration_snapshot_digest=_required_str(
            payload, "configuration_snapshot_digest"
        ),
        provider_profile_id=_required_str(payload, "provider_profile_id"),
        provider_profile_digest=_required_str(payload, "provider_profile_digest"),
        requested_at=requested,
    )


def _project_approval_resolution(
    payload: Mapping[str, Any],
    *,
    pending: ProjectedApprovalContinuation,
    history: Sequence[ProviderMessage],
    outstanding_tool_calls: Mapping[str, tuple[str, str]],
    open_turn_id: str | None,
) -> ProjectedResolvedContinuation:
    expected_fields = {
        "session_id",
        "task_id",
        "run_id",
        "tenant_id",
        "workspace_id",
        "turn_id",
        "action_digest",
        "proposal_id",
        "approval_id",
        "disposition",
        "tool_message_index",
        "assistant_message_index",
        "assistant_message_digest",
        "next_proposal_index",
        "steps",
        "total_tokens",
        "seen_action_digests",
        "configuration_snapshot_id",
        "configuration_snapshot_digest",
        "provider_profile_id",
        "provider_profile_digest",
        "resolved_at",
    }
    if set(payload) != expected_fields:
        raise SessionProjectionError("approval resolution fields are invalid")
    disposition = ApprovalDisposition(payload["disposition"])
    if disposition not in {
        ApprovalDisposition.APPROVE,
        ApprovalDisposition.REJECT,
    }:
        raise SessionProjectionError("approval resolution disposition is invalid")
    if (
        _required_str(payload, "turn_id") != pending.turn_id
        or open_turn_id != pending.turn_id
        or _required_str(payload, "action_digest")
        != pending.action.action_digest()
        or _required_str(payload, "proposal_id") != pending.proposal.proposal_id
    ):
        raise SessionProjectionError("approval resolution binding mismatch")
    tool_message_index = _required_non_negative_int(payload, "tool_message_index")
    if tool_message_index != len(history) - 1:
        raise SessionProjectionError("approval resolution TOOL index mismatch")
    tool = history[tool_message_index]
    if (
        tool.role is not ProviderMessageRole.TOOL
        or tool.tool_call_id != pending.proposal.proposal_id
        or pending.proposal.proposal_id in outstanding_tool_calls
    ):
        raise SessionProjectionError("approval resolution TOOL binding mismatch")
    assistant_message_index = _required_non_negative_int(
        payload, "assistant_message_index"
    )
    if assistant_message_index != pending.assistant_message_index:
        raise SessionProjectionError(
            "approval resolution assistant binding mismatch"
        )
    assistant = history[assistant_message_index]
    assistant_message_digest = _required_str(payload, "assistant_message_digest")
    if (
        assistant.role is not ProviderMessageRole.ASSISTANT
        or content_digest(assistant.model_dump(mode="json"))
        != assistant_message_digest
    ):
        raise SessionProjectionError("approval resolution assistant digest mismatch")
    next_proposal_index = _required_non_negative_int(
        payload, "next_proposal_index"
    )
    if (
        next_proposal_index != pending.proposal_index + 1
        or next_proposal_index > len(assistant.tool_calls)
    ):
        raise SessionProjectionError("approval resolution continuation cursor mismatch")
    steps = _required_non_negative_int(payload, "steps")
    total_tokens = _required_non_negative_int(payload, "total_tokens")
    if steps != pending.steps or total_tokens != pending.total_tokens:
        raise SessionProjectionError("approval resolution loop counters mismatch")
    seen_value = payload["seen_action_digests"]
    if not isinstance(seen_value, dict):
        raise SessionProjectionError("approval resolution loop state is invalid")
    seen: list[tuple[str, int]] = []
    for fingerprint, count in seen_value.items():
        if (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count <= 0
        ):
            raise SessionProjectionError("approval resolution loop state is invalid")
        seen.append((fingerprint, count))
    if tuple(sorted(seen)) != pending.seen_action_digests:
        raise SessionProjectionError("approval resolution loop state mismatch")
    bindings = {
        "configuration_snapshot_id": pending.configuration_snapshot_id,
        "configuration_snapshot_digest": pending.configuration_snapshot_digest,
        "provider_profile_id": pending.provider_profile_id,
        "provider_profile_digest": pending.provider_profile_digest,
    }
    if any(payload.get(key) != value for key, value in bindings.items()):
        raise SessionProjectionError(
            "approval resolution configuration/provider binding mismatch"
        )
    resolved_at = PendingSurfaceApproval(
        action_digest=pending.action.action_digest(),
        capability_id=pending.action.capability_id,
        proposal_id=pending.proposal.proposal_id,
        preview=pending.preview,
        requested_at=payload["resolved_at"],
    ).requested_at
    return ProjectedResolvedContinuation(
        turn_id=pending.turn_id,
        assistant_message_index=assistant_message_index,
        assistant_message_digest=assistant_message_digest,
        next_proposal_index=next_proposal_index,
        steps=steps,
        total_tokens=total_tokens,
        seen_action_digests=tuple(sorted(seen)),
        configuration_snapshot_id=pending.configuration_snapshot_id,
        configuration_snapshot_digest=pending.configuration_snapshot_digest,
        provider_profile_id=pending.provider_profile_id,
        provider_profile_digest=pending.provider_profile_digest,
        source_action_digest=pending.action.action_digest(),
        source_approval_id=_required_str(payload, "approval_id"),
        disposition=disposition,
        tool_message_index=tool_message_index,
        resolved_at=resolved_at,
    )


def _required_non_negative_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SessionProjectionError(f"{key} must be a non-negative integer")
    return value


def _proposal_fingerprint(proposal: ProviderToolProposal) -> str:
    import hashlib

    return hashlib.sha256(
        f"{proposal.capability_id}\n{proposal.arguments_json}".encode("utf-8")
    ).hexdigest()
