from __future__ import annotations

import copy
from typing import Any


class ProtocolError(ValueError):
    pass


def _exact_object(value: object, fields: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ProtocolError(f"{label} requires exact fields {sorted(fields)}")
    if any(not isinstance(key, str) for key in value):
        raise ProtocolError(f"{label} keys must be strings")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProtocolError(f"{label} must be a non-negative integer")
    return value


def parse_action_proposal(
    payload: object, expected_version: int, authorized_actions: tuple[str, ...]
) -> dict[str, object]:
    proposal = _exact_object(
        payload, {"kind", "state_version", "action"}, "action proposal"
    )
    if proposal["kind"] != "action_proposal":
        raise ProtocolError("action proposal kind mismatch")
    version = _integer(proposal["state_version"], "state_version")
    if version != expected_version:
        raise ProtocolError("stale action proposal state version")
    action = proposal["action"]
    if not isinstance(action, str) or action not in authorized_actions:
        raise ProtocolError("unauthorized action proposal")
    return dict(proposal)


def parse_transition_batch(
    payload: object, *, expected_version: int, max_operations: int
) -> dict[str, object]:
    batch = _exact_object(
        payload, {"kind", "state_version", "operations"}, "transition batch"
    )
    if batch["kind"] != "transition_batch":
        raise ProtocolError("transition batch kind mismatch")
    version = _integer(batch["state_version"], "state_version")
    if version != expected_version:
        raise ProtocolError("stale transition batch state version")
    operations = batch["operations"]
    if not isinstance(operations, list):
        raise ProtocolError("transition operations must be a list")
    if len(operations) > max_operations:
        raise ProtocolError("transition operation budget exceeded before apply")
    parsed: list[dict[str, object]] = []
    for operation in operations:
        op = _exact_object(operation, {"op", "event_digest"}, "transition")
        if op["op"] not in {"record_feedback", "invalidate_feedback"}:
            raise ProtocolError("unsupported transition operation")
        digest = op["event_digest"]
        if not isinstance(digest, str) or len(digest) != 64:
            raise ProtocolError("transition event digest must be sha256-shaped")
        parsed.append(dict(op))
    return {
        "kind": "transition_batch",
        "state_version": version,
        "operations": parsed,
    }


def apply_transition_batch(
    state: dict[str, Any],
    payload: object,
    *,
    expected_version: int,
    max_operations: int,
    authoritative_feedback: dict[str, object] | None = None,
    authorized_correction: str | None = None,
) -> dict[str, Any]:
    batch = parse_transition_batch(
        payload,
        expected_version=expected_version,
        max_operations=max_operations,
    )
    candidate = copy.deepcopy(state)
    candidate.setdefault("events", [])
    candidate.setdefault("invalidated", [])
    for operation in batch["operations"]:
        digest = operation["event_digest"]
        if operation["op"] == "record_feedback":
            if authoritative_feedback is None or digest != authoritative_feedback.get(
                "event_digest"
            ):
                raise ProtocolError("transition is not bound to evaluator feedback")
            if any(
                event.get("event_digest") == digest for event in candidate["events"]
            ):
                raise ProtocolError("duplicate feedback transition")
            candidate["events"].append(copy.deepcopy(authoritative_feedback))
        elif authorized_correction != digest:
            raise ProtocolError("transition is not bound to evaluator correction")
        elif not any(
            event.get("event_digest") == digest for event in candidate["events"]
        ):
            raise ProtocolError("correction references unknown feedback")
        elif digest not in candidate["invalidated"]:
            candidate["invalidated"].append(digest)
    candidate["version"] = expected_version + 1
    state.clear()
    state.update(candidate)
    return state
