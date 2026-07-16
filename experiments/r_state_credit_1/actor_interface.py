"""Neutral actor interface for R-STATE-CREDIT-1 Phase 2.

The interface is provider-neutral: a stub actor is included for local
qualification, and the same interface can be implemented by a provider-backed
actor later.  No provider call, model inference, or external side effect occurs
in this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from experiments.r_state_credit_1.action_grammar import ActorAction
from experiments.r_state_credit_1.contracts import canonical_json


@dataclass(frozen=True, slots=True)
class ActorRequest:
    """Neutral request delivered to an actor at a checkpoint.

    Contains only the arm-rendered representation bytes of the released
    observation prefix, a neutral session label, and the frozen valid action
    grammar.  No arm identity, family identifier, turn index, checkpoint
    ordinal, sealed label, correct action, or future event is present.
    """

    representation: str
    valid_actions: tuple[ActorAction, ...]
    session_label: str

    def __post_init__(self) -> None:
        if not isinstance(self.representation, str) or not self.representation:
            raise ValueError("representation must be non-empty text")
        if not isinstance(self.valid_actions, tuple) or not self.valid_actions:
            raise ValueError("valid_actions must be a non-empty tuple")
        if any(
            not isinstance(action, ActorAction) for action in self.valid_actions
        ):
            raise ValueError("valid_actions must contain ActorAction values")
        if len(self.valid_actions) != len(
            {action.value for action in self.valid_actions}
        ):
            raise ValueError("valid_actions must not contain duplicates")
        if not isinstance(self.session_label, str) or not self.session_label:
            raise ValueError("session_label must be non-empty text")

    def to_mapping(self) -> dict[str, object]:
        """Return a closed mapping for canonical serialization."""
        return {
            "representation": self.representation,
            "valid_actions": tuple(action.value for action in self.valid_actions),
            "session_label": self.session_label,
        }

    def to_canonical_json(self) -> str:
        """Return deterministic compact JSON for byte-budget measurement."""
        return canonical_json(self.to_mapping())


@dataclass(frozen=True, slots=True)
class ActorResponse:
    """Neutral response from an actor.

    Contains only the chosen action and optional free-text notes.
    """

    action: ActorAction
    notes: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, ActorAction):
            raise ValueError("action must be ActorAction")
        if self.notes is not None and (
            not isinstance(self.notes, str) or not self.notes.strip()
        ):
            raise ValueError("notes must be non-empty text when provided")

    def to_mapping(self) -> dict[str, object]:
        """Return a closed mapping for canonical serialization."""
        result: dict[str, object] = {"action": self.action.value}
        if self.notes is not None:
            result["notes"] = self.notes
        return result


class Actor(Protocol):
    """Provider-neutral actor protocol."""

    def act(self, request: ActorRequest) -> ActorResponse: ...


class StubActor:
    """Deterministic event-class lookup actor for local qualification.

    Reads the shared ``latest`` observation block inside the arm-rendered
    representation and maps its event class to an action.  It deliberately
    ignores the representation of history, so it must fail the sealed-referee
    paired discrimination cases.  No provider call or model inference occurs.
    """

    # Priority order used when the rule-based choice is not in valid_actions.
    _PRIORITY: tuple[ActorAction, ...] = (
        ActorAction.RECOVER_ROLLBACK,
        ActorAction.RECOVER_ROLL_FORWARD,
        ActorAction.REVIEW,
        ActorAction.VERIFY_EFFECT,
        ActorAction.ABSTAIN,
        ActorAction.CONTINUE,
    )

    def act(self, request: ActorRequest) -> ActorResponse:
        """Return a deterministic action from ``request.valid_actions``."""
        chosen = self._choose(request)
        if chosen not in request.valid_actions:
            chosen = next(
                action for action in self._PRIORITY
                if action in request.valid_actions
            )
        return ActorResponse(action=chosen)

    def _choose(self, request: ActorRequest) -> ActorAction:
        """Event-class lookup over the shared latest observation block."""
        try:
            data = json.loads(request.representation)
        except ValueError:
            return ActorAction.ABSTAIN
        latest = data.get("latest") if isinstance(data, dict) else None
        if not isinstance(latest, dict):
            return ActorAction.ABSTAIN
        event_class = latest.get("event_class")
        payload: Any = latest.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        if event_class == "DETERMINISTIC_RECOVERY":
            recovery_action = payload.get("recovery_action")
            if recovery_action == "ROLLBACK":
                return ActorAction.RECOVER_ROLLBACK
            if recovery_action == "ROLL_FORWARD":
                return ActorAction.RECOVER_ROLL_FORWARD
            return ActorAction.REVIEW

        review_classes = {
            "ALIAS_REBIND",
            "OBJECT_VERSION_CHANGE",
            "SIMULTANEOUS_CONFLICTING_EVIDENCE",
            "PRECONDITION_REFUTATION",
            "OUT_OF_ORDER_TRANSACTION",
            "HALF_OPEN_VALID_TIME_BOUNDARY",
            "LATE_REFUTATION",
            "TRANSITIVE_INVALIDATION",
            "ASSERTION_SUPERSESSION",
            "DELAYED_DEPENDENT_ACTION",
        }
        if event_class in review_classes:
            return ActorAction.REVIEW

        verify_classes = {
            "PROCESS_RESTART",
            "ACTION_DISPATCH",
            "INTERRUPTION_BEFORE_EFFECT_VERIFICATION",
            "RECEIPT_LOSS",
        }
        if event_class in verify_classes:
            return ActorAction.VERIFY_EFFECT

        abstain_classes = {
            "PENDING_COMMITMENT",
            "PROTECTED_STATE_AT_BOUND",
            "REPRESENTATION_PRESSURE",
        }
        if event_class in abstain_classes:
            return ActorAction.ABSTAIN

        return ActorAction.CONTINUE
