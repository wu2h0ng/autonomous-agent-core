"""Closing out a durable chat turn whose owning runtime process is gone.

A `SESSION_TURN_STARTED` event without its `SESSION_TURN_COMPLETED` is the
session's one open turn. When the process that wrote the start event died
mid-turn, nothing will ever complete it: the provider call that would have
produced the turn's outcome died with that process, and the kernel's own
in-process recovery (`AgentLoop.resume_turn`, for a turn interrupted inside a
live process) has no durable stream to re-enter. The session reported ACTIVE
and refused every later turn, with no operator route out.

The record written here follows the repository's existing precedent for an
ambiguous outcome (`UNKNOWN_REQUIRES_REVIEW`, the `unknown_requires_review`
turn commit in `AgentLoop._complete_turn`): the turn is closed, never as a
success, with the reason named. Three things are true and are all recorded:

* the turn never reported an outcome, so its `stop_reason` is
  `unknown_requires_review` - never `completed`;
* the operator declared it dead, and that declaration is durable evidence
  (`declared_by`, `declared_at`, `reason`);
* the runtime generation that started the turn and the one that closed it are
  both named, so the record can be audited against the daemon generations that
  actually existed.

Nothing here widens authority: no approval is granted or consumed, no policy
or C7 input changes, and no capability is dispatched. The write is refused
unless the exact durable turn is open and the projector will accept the
completion it produces.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEAD_TURN_REASON_CODE = "TURN_OWNER_PROCESS_GONE"
"""Why the closed turn is dead: the runtime process that owned it is gone."""

DEAD_TURN_RECOVERY_FIELD = "dead_turn_recovery"
"""Payload key of the typed recovery record on the completion event."""

DEAD_TURN_STOP_REASON = "unknown_requires_review"
"""The frozen stop reason an ambiguous turn is closed with; never `completed`."""


def dead_turn_recovery_notice(block: Mapping[str, Any]) -> str:
    """Render the operator-facing notice from the typed durable record.

    The record is the truth; this is one rendering of it (the terminal renders
    its own wording from the same fields). Nothing is stated that the record
    does not carry.
    """

    turn_id = str(block.get("turn_id", "unknown-turn"))
    owner_boot = block.get("owner_runtime_boot_id")
    owner_pid = block.get("owner_runtime_pid")
    owner = (
        f"{owner_boot} (pid {owner_pid})"
        if isinstance(owner_boot, str) and owner_boot
        else "a runtime that recorded no generation"
    )
    recovered_by = block.get("recovered_by_runtime_boot_id", "unknown-runtime")
    recovered_pid = block.get("recovered_by_runtime_pid", 0)
    declared_by = block.get("declared_by", "unknown")
    declared_at = block.get("declared_at", "unknown")
    reason = block.get("reason", "")
    counters = (
        "step and token counters were recorded"
        if block.get("counters_recorded") is True
        else "no step or token counters survived for it"
    )
    return (
        f"turn {turn_id} was abandoned as an unknown outcome: it was started by "
        f"{owner}, and closed by {recovered_by} (pid {recovered_pid}) after that "
        f"runtime was gone. Its model call died with that process, so it is "
        f"recorded as {DEAD_TURN_STOP_REASON} - not a successful completion - and "
        f"{counters}. Declared dead by {declared_by} at {declared_at}: {reason}. "
        f"The session accepts new turns again."
    )
