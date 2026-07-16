from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from agent_os_contracts import SrlEnvironmentEvent

from tests.research.r_srl_1.harness import FrozenUnit, load_events


class OutcomeVerdict(str, Enum):
    VERIFIED = "VERIFIED"
    NOT_MET = "NOT_MET"
    UNRESOLVED = "UNRESOLVED"
    INVALID = "INVALID"


@dataclass(frozen=True)
class EventOutcome:
    event_id: str
    verdict: OutcomeVerdict
    score: float
    evidence_refs: tuple[str, ...]
    gaps: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.score not in {0.0, 1.0}:
            raise ValueError("R-SRL-1 event outcome score must be 0.0 or 1.0")


Plugin = Callable[[SrlEnvironmentEvent, dict[str, Any], dict[str, Any]], EventOutcome]


def _verified(
    event_id: str,
    evidence_refs: tuple[str, ...],
) -> EventOutcome:
    return EventOutcome(
        event_id=event_id,
        verdict=OutcomeVerdict.VERIFIED,
        score=1.0,
        evidence_refs=evidence_refs,
        gaps=(),
    )


def _not_met(
    event_id: str,
    gaps: tuple[str, ...],
    evidence_refs: tuple[str, ...] = (),
) -> EventOutcome:
    return EventOutcome(
        event_id=event_id,
        verdict=OutcomeVerdict.NOT_MET,
        score=0.0,
        evidence_refs=evidence_refs,
        gaps=gaps,
    )


def _unresolved(
    event_id: str,
    gaps: tuple[str, ...],
    evidence_refs: tuple[str, ...] = (),
) -> EventOutcome:
    return EventOutcome(
        event_id=event_id,
        verdict=OutcomeVerdict.UNRESOLVED,
        score=0.0,
        evidence_refs=evidence_refs,
        gaps=gaps,
    )


def _invalid(
    event_id: str,
    gaps: tuple[str, ...],
    evidence_refs: tuple[str, ...] = (),
) -> EventOutcome:
    return EventOutcome(
        event_id=event_id,
        verdict=OutcomeVerdict.INVALID,
        score=0.0,
        evidence_refs=evidence_refs,
        gaps=gaps,
    )


def _get_test_reports(artifact: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return normalized test_path -> report mapping from the artifact.

    Supports both ``dict`` and ``list`` report containers.
    """
    reports = artifact.get("test_reports", {})
    if isinstance(reports, dict):
        return {str(k): v for k, v in reports.items() if isinstance(v, dict)}
    if isinstance(reports, list):
        result: dict[str, dict[str, Any]] = {}
        for item in reports:
            if isinstance(item, dict) and "test_path" in item:
                result[str(item["test_path"])] = item
        return result
    return {}


def evaluate_test_fixed(
    event: SrlEnvironmentEvent,
    expected: dict[str, Any],
    artifact: dict[str, Any],
) -> EventOutcome:
    """Score TEST_FIXED outcomes from durable test reports.

    VERIFIED: a passing report exists for ``test_path``.
    NOT_MET: a failing report exists for ``test_path``.
    UNRESOLVED: no report exists for ``test_path``.
    INVALID: inconsistent reports (conflicting pass/fail for the same path).
    """
    event_id = event.event_id
    test_path = str(expected.get("test_path", ""))
    if not test_path:
        return _invalid(
            event_id,
            ("expected outcome missing required test_path",),
        )

    reports = _get_test_reports(artifact)
    report = reports.get(test_path)
    if report is None:
        return _unresolved(
            event_id,
            (f"no test report found for {test_path}",),
        )

    passed = report.get("passed")
    artifact_ref = report.get("artifact_ref")
    if not isinstance(artifact_ref, str) or not artifact_ref:
        return _invalid(
            event_id,
            ("test report missing durable artifact_ref",),
        )

    # Detect inconsistency: multiple reports for the same path with conflicting results.
    seen_pass_values: set[bool] = set()
    for item in reports.values():
        if item.get("test_path") == test_path and isinstance(item.get("passed"), bool):
            seen_pass_values.add(item["passed"])
    if len(seen_pass_values) > 1:
        return _invalid(
            event_id,
            (f"conflicting test reports for {test_path}",),
        )

    evidence = (f"artifact:{artifact_ref}",)
    if passed is True:
        return _verified(event_id, evidence)
    if passed is False:
        return _not_met(
            event_id,
            (f"test report indicates {test_path} did not pass",),
            evidence,
        )
    return _invalid(
        event_id,
        ("test report missing boolean passed field",),
    )


def _event_records(artifact: dict[str, Any], key: str, event_id: str) -> list[Any]:
    """Return records for ``event_id`` from a dict-of-lists artifact field."""
    container = artifact.get(key, {})
    if isinstance(container, dict):
        return list(container.get(event_id, []))
    return []


def evaluate_decoy(
    event: SrlEnvironmentEvent,
    expected: dict[str, Any],
    artifact: dict[str, Any],
) -> EventOutcome:
    """Score DECOY outcomes: no work may be spawned for this event.

    VERIFIED: zero actions, zero help requests, and zero file modifications.
    NOT_MET: any work spawned for the event.
    """
    event_id = event.event_id
    actions = _event_records(artifact, "actions", event_id)
    help_requests = _event_records(artifact, "help_requests", event_id)
    file_modifications = _event_records(artifact, "file_modifications", event_id)

    spawned: list[str] = []
    if actions:
        spawned.append(f"{len(actions)} action(s) recorded")
    if help_requests:
        spawned.append(f"{len(help_requests)} help request(s) recorded")
    if file_modifications:
        spawned.append(f"{len(file_modifications)} file modification(s) recorded")

    if spawned:
        return _not_met(
            event_id,
            (f"decoy event spawned work: {', '.join(spawned)}",),
        )

    return _verified(
        event_id,
        ("artifact:decoy:no_work_spawned",),
    )


# ---------------------------------------------------------------------------
# Additional fail-closed R-SRL-1 outcome plugins
# ---------------------------------------------------------------------------


def _get_action_kind(action: Any) -> str:
    """Return the action kind string, or empty if malformed."""
    if isinstance(action, dict):
        kind = action.get("kind")
        if isinstance(kind, str):
            return kind
    return ""


def _get_action_payload(action: Any) -> dict[str, Any]:
    """Return the action payload dict, or empty if malformed."""
    if isinstance(action, dict):
        payload = action.get("payload")
        if isinstance(payload, dict):
            return payload
    return {}


def _required_string(expected: dict[str, Any], key: str) -> str | None:
    """Return a required string value, or None if missing/not a string."""
    value = expected.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _required_int(expected: dict[str, Any], key: str) -> int | None:
    """Return a required int value, or None if missing/not an int."""
    value = expected.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def evaluate_interface_adapted(
    event: SrlEnvironmentEvent,
    expected: dict[str, Any],
    artifact: dict[str, Any],
) -> EventOutcome:
    """Score INTERFACE_ADAPTED outcomes.

    VERIFIED: a matching action kind and payload.call, with no forbidden call.
    NOT_MET: forbidden call present, or actions exist but none match.
    UNRESOLVED: no actions recorded for the event.
    INVALID: required keys missing or wrong-typed.
    """
    event_id = event.event_id
    required_action_kind = _required_string(expected, "required_action_kind")
    required_call = _required_string(expected, "required_call")
    if required_action_kind is None or required_call is None:
        return _invalid(
            event_id,
            ("expected outcome missing required_action_kind or required_call",),
        )

    forbidden_call = expected.get("forbidden_call")
    if forbidden_call is not None and not isinstance(forbidden_call, str):
        return _invalid(
            event_id,
            ("expected outcome forbidden_call must be a string",),
        )

    actions = _event_records(artifact, "actions", event_id)
    if not actions:
        return _unresolved(
            event_id,
            ("no actions recorded for INTERFACE_ADAPTED",),
        )

    matched = False
    for action in actions:
        payload = _get_action_payload(action)
        if (
            _get_action_kind(action) == required_action_kind
            and payload.get("call") == required_call
        ):
            matched = True
        if forbidden_call and payload.get("call") == forbidden_call:
            return _not_met(
                event_id,
                (f"forbidden call {forbidden_call!r} was invoked",),
            )

    if matched:
        return _verified(
            event_id,
            (
                f"artifact:interface:{event_id}:matched_call",
                f"artifact:interface:{event_id}:no_forbidden_call",
            ),
        )

    return _not_met(
        event_id,
        (
            f"no action matched required kind {required_action_kind!r} and call {required_call!r}",
        ),
    )


def evaluate_conflict_resolved(
    event: SrlEnvironmentEvent,
    expected: dict[str, Any],
    artifact: dict[str, Any],
) -> EventOutcome:
    """Score CONFLICT_RESOLVED outcomes.

    VERIFIED: matching constraint action kind with payload.constraint match,
              no forbidden-kind action present.
    NOT_MET: forbidden-kind action present, or actions exist but none match.
    UNRESOLVED: no actions recorded for the event.
    INVALID: required keys missing or wrong-typed.
    """
    event_id = event.event_id
    constraint = _required_string(expected, "constraint")
    required_action_kind = _required_string(expected, "required_action_kind")
    if constraint is None or required_action_kind is None:
        return _invalid(
            event_id,
            ("expected outcome missing constraint or required_action_kind",),
        )

    forbidden_action_kind = expected.get("forbidden_action_kind")
    if forbidden_action_kind is not None and not isinstance(forbidden_action_kind, str):
        return _invalid(
            event_id,
            ("expected outcome forbidden_action_kind must be a string",),
        )

    actions = _event_records(artifact, "actions", event_id)
    if not actions:
        return _unresolved(
            event_id,
            ("no actions recorded for CONFLICT_RESOLVED",),
        )

    matched = False
    for action in actions:
        kind = _get_action_kind(action)
        payload = _get_action_payload(action)
        if kind == required_action_kind and payload.get("constraint") == constraint:
            matched = True
        if forbidden_action_kind and kind == forbidden_action_kind:
            return _not_met(
                event_id,
                (f"forbidden action kind {forbidden_action_kind!r} was recorded",),
            )

    if matched:
        return _verified(
            event_id,
            (
                f"artifact:conflict:{event_id}:constraint_matched",
                f"artifact:conflict:{event_id}:no_forbidden_kind",
            ),
        )

    return _not_met(
        event_id,
        (
            f"no action matched kind {required_action_kind!r} and constraint {constraint!r}",
        ),
    )


def evaluate_restart_equivalent(
    event: SrlEnvironmentEvent,
    expected: dict[str, Any],
    artifact: dict[str, Any],
) -> EventOutcome:
    """Score RESTART_EQUIVALENT outcomes from a restart comparator record.

    VERIFIED: comparison reports equivalent == True.
    NOT_MET: comparison reports equivalent == False.
    UNRESOLVED: no comparison record for the event.
    INVALID: equivalent present but not a bool.
    """
    event_id = event.event_id
    comparisons = artifact.get("restart_comparisons")
    if not isinstance(comparisons, dict):
        return _unresolved(
            event_id,
            ("no restart_comparisons recorded",),
        )

    record = comparisons.get(event_id)
    if not isinstance(record, dict):
        return _unresolved(
            event_id,
            (f"no restart comparison record for {event_id}",),
        )

    equivalent = record.get("equivalent")
    if equivalent is True:
        return _verified(
            event_id,
            (f"artifact:restart:{event_id}:comparison",),
        )
    if equivalent is False:
        differences = record.get("differences", [])
        if isinstance(differences, list):
            gaps = tuple(str(d) for d in differences)
        else:
            gaps = ("restart comparison reported non-bool differences",)
        return _not_met(
            event_id,
            gaps if gaps else ("restart comparison reported not equivalent",),
            evidence_refs=(f"artifact:restart:{event_id}:comparison",),
        )

    return _invalid(
        event_id,
        ("restart comparison equivalent field is not a bool",),
    )


def evaluate_uncertainty_resolved(
    event: SrlEnvironmentEvent,
    expected: dict[str, Any],
    artifact: dict[str, Any],
) -> EventOutcome:
    """Score UNCERTAINTY_RESOLVED outcomes.

    VERIFIED: accepted-kind action with non-empty statement, or help request recorded.
    NOT_MET: actions exist but none qualify and no help request.
    UNRESOLVED: nothing recorded for the event.
    """
    event_id = event.event_id
    accepted_action_kinds = expected.get(
        "accepted_action_kinds", ["uncertainty_note", "risk_assessment"]
    )
    if not isinstance(accepted_action_kinds, (list, tuple)) or not all(
        isinstance(k, str) for k in accepted_action_kinds
    ):
        return _invalid(
            event_id,
            ("expected outcome accepted_action_kinds must be a list of strings",),
        )
    accepted = set(accepted_action_kinds)

    actions = _event_records(artifact, "actions", event_id)
    help_requests = _event_records(artifact, "help_requests", event_id)

    if not actions and not help_requests:
        return _unresolved(
            event_id,
            ("no actions or help requests recorded for UNCERTAINTY_RESOLVED",),
        )

    for action in actions:
        if _get_action_kind(action) in accepted:
            payload = _get_action_payload(action)
            statement = payload.get("statement")
            if isinstance(statement, str) and statement:
                return _verified(
                    event_id,
                    (f"artifact:uncertainty:{event_id}:accepted_statement",),
                )

    if help_requests:
        for request in help_requests:
            minimum_answer = _get_minimum_answer(request)
            if isinstance(minimum_answer, str) and minimum_answer:
                return _verified(
                    event_id,
                    (f"artifact:help:{event_id}:request",),
                )

    return _not_met(
        event_id,
        ("no accepted uncertainty action or qualified help request recorded",),
    )


def _get_minimum_answer(request: Any) -> Any:
    """Return minimum_answer from an SrlHelpRequest or plain dict."""
    if isinstance(request, dict):
        return request.get("minimum_answer")
    return getattr(request, "minimum_answer", None)


def evaluate_belief_updated(
    event: SrlEnvironmentEvent,
    expected: dict[str, Any],
    artifact: dict[str, Any],
) -> EventOutcome:
    """Score BELIEF_UPDATED outcomes.

    VERIFIED: correction action for stale_belief_id with non-empty new_value.
    NOT_MET: correction for a different belief_id, or actions exist but no correction.
    UNRESOLVED: no actions recorded for the event.
    INVALID: stale_belief_id missing or wrong-typed.
    """
    event_id = event.event_id
    stale_belief_id = _required_string(expected, "stale_belief_id")
    if stale_belief_id is None:
        return _invalid(
            event_id,
            ("expected outcome missing stale_belief_id",),
        )

    correction_action_kind = expected.get("correction_action_kind", "belief_correction")
    if not isinstance(correction_action_kind, str):
        return _invalid(
            event_id,
            ("expected outcome correction_action_kind must be a string",),
        )

    actions = _event_records(artifact, "actions", event_id)
    if not actions:
        return _unresolved(
            event_id,
            ("no actions recorded for BELIEF_UPDATED",),
        )

    for action in actions:
        if _get_action_kind(action) == correction_action_kind:
            payload = _get_action_payload(action)
            belief_id = payload.get("belief_id")
            new_value = payload.get("new_value")
            if (
                belief_id == stale_belief_id
                and isinstance(new_value, str)
                and new_value
            ):
                return _verified(
                    event_id,
                    (f"artifact:belief:{event_id}:correction",),
                )
            if belief_id != stale_belief_id:
                return _not_met(
                    event_id,
                    (
                        f"correction recorded for {belief_id!r}, expected {stale_belief_id!r}",
                    ),
                )

    return _not_met(
        event_id,
        (f"no {correction_action_kind!r} action recorded",),
    )


def evaluate_commitment_met(
    event: SrlEnvironmentEvent,
    expected: dict[str, Any],
    artifact: dict[str, Any],
) -> EventOutcome:
    """Score COMMITMENT_MET outcomes.

    VERIFIED: commitment_complete action with matching commitment_id and turn <= deadline_turn.
    NOT_MET: completion after deadline, or actions exist but no completion.
    UNRESOLVED: no actions recorded for the event.
    INVALID: commitment_id or deadline_turn missing/wrong-typed.
    """
    event_id = event.event_id
    commitment_id = _required_string(expected, "commitment_id")
    deadline_turn = _required_int(expected, "deadline_turn")
    if commitment_id is None or deadline_turn is None:
        return _invalid(
            event_id,
            ("expected outcome missing commitment_id or deadline_turn",),
        )

    actions = _event_records(artifact, "actions", event_id)
    if not actions:
        return _unresolved(
            event_id,
            ("no actions recorded for COMMITMENT_MET",),
        )

    for action in actions:
        if _get_action_kind(action) == "commitment_complete":
            payload = _get_action_payload(action)
            if payload.get("commitment_id") == commitment_id:
                try:
                    turn = int(payload.get("turn"))  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    return _not_met(
                        event_id,
                        ("commitment_complete action has non-integer turn",),
                    )
                if turn <= deadline_turn:
                    return _verified(
                        event_id,
                        (f"artifact:commitment:{event_id}:on_time",),
                    )
                return _not_met(
                    event_id,
                    (
                        f"commitment completed at turn {turn}, deadline was {deadline_turn}",
                    ),
                )

    return _not_met(
        event_id,
        (f"no commitment_complete action recorded for {commitment_id!r}",),
    )


def evaluate_help_escalated(
    event: SrlEnvironmentEvent,
    expected: dict[str, Any],
    artifact: dict[str, Any],
) -> EventOutcome:
    """Score HELP_ESCALATED outcomes.

    VERIFIED: help request recorded with non-empty minimum_answer.
    NOT_MET: no help request but actions exist, or help requests all empty.
    UNRESOLVED: nothing recorded for the event.
    """
    event_id = event.event_id
    help_requests = _event_records(artifact, "help_requests", event_id)
    actions = _event_records(artifact, "actions", event_id)

    if help_requests:
        for request in help_requests:
            minimum_answer = _get_minimum_answer(request)
            if isinstance(minimum_answer, str) and minimum_answer:
                return _verified(
                    event_id,
                    (f"artifact:help:{event_id}:request",),
                )
        return _not_met(
            event_id,
            ("help request(s) recorded but minimum_answer is empty",),
        )

    if actions:
        return _not_met(
            event_id,
            ("actions recorded but no help request was emitted",),
        )

    return _unresolved(
        event_id,
        ("no help request or action recorded for HELP_ESCALATED",),
    )


def load_expected_outcomes(expected_outcomes_path: Path) -> dict[str, dict[str, Any]]:
    raw: dict[str, Any] = yaml.safe_load(
        expected_outcomes_path.read_text(encoding="utf-8")
    )
    if not isinstance(raw, dict):
        raise ValueError(
            f"expected_outcomes.yaml must contain a mapping: {expected_outcomes_path}"
        )
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


class RsrlHiddenEvaluator:
    """Hidden automated scorer for R-SRL-1 units.

    Dispatches per-event outcome evaluation to typed plugins keyed by the
    ``type`` field in ``expected_outcomes.yaml``.  Plugins receive only the
    event, expected outcome mapping, and arm run artifact; they never receive
    model narration or arm-internal state.
    """

    DEFAULT_PLUGINS: Mapping[str, Plugin] = {
        "TEST_FIXED": evaluate_test_fixed,
        "DECOY": evaluate_decoy,
        "INTERFACE_ADAPTED": evaluate_interface_adapted,
        "CONFLICT_RESOLVED": evaluate_conflict_resolved,
        "RESTART_EQUIVALENT": evaluate_restart_equivalent,
        "UNCERTAINTY_RESOLVED": evaluate_uncertainty_resolved,
        "BELIEF_UPDATED": evaluate_belief_updated,
        "COMMITMENT_MET": evaluate_commitment_met,
        "HELP_ESCALATED": evaluate_help_escalated,
    }

    def __init__(self, plugins: Mapping[str, Plugin] | None = None) -> None:
        self._plugins = (
            dict(plugins) if plugins is not None else dict(self.DEFAULT_PLUGINS)
        )

    def evaluate(
        self,
        unit: FrozenUnit,
        artifact: dict[str, Any],
    ) -> dict[str, EventOutcome]:
        events = load_events(unit.events_path)
        expected_outcomes = load_expected_outcomes(unit.expected_outcomes_path)
        outcomes: dict[str, EventOutcome] = {}
        for event in events:
            expected = expected_outcomes.get(event.event_id, {})
            event_type = str(expected.get("type", ""))
            plugin = self._plugins.get(event_type)
            if plugin is None:
                outcomes[event.event_id] = _invalid(
                    event.event_id,
                    (f"unknown expected outcome type: {event_type}",),
                )
            else:
                outcomes[event.event_id] = plugin(event, expected, artifact)
        return outcomes
