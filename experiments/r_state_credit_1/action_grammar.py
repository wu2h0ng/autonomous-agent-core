"""Frozen action grammar for the R-STATE-CREDIT-1 actor interface."""

from __future__ import annotations

from enum import Enum
from typing import Any, Iterable


class ActorAction(str, Enum):
    """Frozen action grammar available to the actor.

    No arm-specific values or policy hints are permitted.
    """

    REVIEW = "REVIEW"
    VERIFY_EFFECT = "VERIFY_EFFECT"
    ABSTAIN = "ABSTAIN"
    CONTINUE = "CONTINUE"
    RECOVER_ROLLBACK = "RECOVER_ROLLBACK"
    RECOVER_ROLL_FORWARD = "RECOVER_ROLL_FORWARD"


ALL_ACTIONS: tuple[ActorAction, ...] = tuple(ActorAction)


def validate_action(value: Any) -> ActorAction:
    """Return an ``ActorAction`` or raise ``ValueError``."""
    if isinstance(value, ActorAction):
        return value
    if isinstance(value, str):
        return ActorAction(value)
    raise ValueError(f"not a valid ActorAction: {value!r}")


def validate_actions(values: Iterable[Any]) -> tuple[ActorAction, ...]:
    """Validate and deduplicate an iterable of candidate actions."""
    actions: list[ActorAction] = []
    seen: set[str] = set()
    for value in values:
        action = validate_action(value)
        if action.value not in seen:
            actions.append(action)
            seen.add(action.value)
    if not actions:
        raise ValueError("at least one ActorAction is required")
    return tuple(actions)
