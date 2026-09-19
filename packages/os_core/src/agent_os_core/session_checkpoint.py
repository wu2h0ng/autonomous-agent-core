"""Append-only session checkpoints and forward replay recovery (P0).

This is the forward form of checkpoint/rewind the evidence spine allows (see
``docs/product/GC-CHECKPOINT-REWIND-2026-09-18.md``): a checkpoint is an
append-only, operator-named marker that *references* the existing event stream
``(sequence, turn_id, state_digest)`` rather than copying a second snapshot.

Recovery after a crash is therefore **forward**, never a time travel: a new
process re-projects the session by reading the stream *from* the checkpoint
sequence onward. Prior events are never deleted, rewritten or re-sequenced.

Nothing here creates a second source of truth: ``state_digest`` is a binding
fingerprint over the projected state at the checkpoint point, so a replay that
starts at the wrong stream detects the mismatch instead of silently drifting.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_os_contracts import TaskEventType


@dataclass(frozen=True)
class SessionCheckpoint:
    """One durable, operator-named checkpoint marker on the session stream."""

    sequence: int
    turn_id: str | None
    label: str
    state_digest: str
    event_id: str


@dataclass(frozen=True)
class ForwardReplay:
    """The result of re-projecting the stream forward from a checkpoint.

    This is the recovered session state after a crash: it is computed purely
    by reading durable events, so it is identical in every process that opens
    the same database.
    """

    from_sequence: int
    event_count: int
    message_count: int
    last_event_type: str | None
    turn_ids_seen: tuple[str, ...]


def list_checkpoints(events: object, task_id: str) -> tuple[SessionCheckpoint, ...]:
    """Every checkpoint marker for ``task_id`` in stream order."""

    out: list[SessionCheckpoint] = []
    for event in events.read(task_id):
        if event.event_type is not TaskEventType.SESSION_CHECKPOINT_RECORDED:
            continue
        payload = event.decoded_payload()
        out.append(
            SessionCheckpoint(
                sequence=int(payload["sequence"]),
                turn_id=payload.get("turn_id"),
                label=str(payload["label"]),
                state_digest=str(payload["state_digest"]),
                event_id=event.event_id,
            )
        )
    return tuple(out)


def replay_forward(events: object, task_id: str, from_sequence: int) -> ForwardReplay:
    """Re-project the stream forward from ``from_sequence`` (inclusive).

    Counts session messages and records the last event type and the turn ids
    seen. This is what a fresh process reconstructs after a crash: no state is
    copied out of the old process, only the durable events are read.
    """

    message_count = 0
    last_event_type: str | None = None
    turn_ids: list[str] = []
    event_count = 0
    for event in events.read(task_id):
        if event.sequence < from_sequence:
            continue
        event_count += 1
        last_event_type = event.event_type.value
        if event.event_type is TaskEventType.SESSION_MESSAGE_RECORDED:
            message_count += 1
        if event.event_type is TaskEventType.SESSION_TURN_STARTED:
            turn_id = event.decoded_payload().get("turn_id")
            if turn_id is not None:
                turn_ids.append(str(turn_id))
    return ForwardReplay(
        from_sequence=from_sequence,
        event_count=event_count,
        message_count=message_count,
        last_event_type=last_event_type,
        turn_ids_seen=tuple(turn_ids),
    )


def project_state_digest(
    message_count: int,
    last_event_type: str | None,
) -> str:
    """A small, order-independent-enough fingerprint of projected state.

    Deliberately a cheap binding fingerprint (not a cryptographic snapshot): it
    only proves "the replay landed on the same projected state the operator
    marked", not a full content hash. It never carries prompt text.
    """

    import hashlib

    material = f"{message_count}\x1f{last_event_type or ''}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
