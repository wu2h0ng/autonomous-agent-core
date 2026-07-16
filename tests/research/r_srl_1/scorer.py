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
