from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.research.r_srl_1.harness import FrozenUnit, load_events, load_frozen_unit
from tests.research.r_srl_1.outcome_evaluator import RsrlOutcomeEvaluator
from tests.research.r_srl_1.scorer import (
    EventOutcome,
    OutcomeVerdict,
    RsrlHiddenEvaluator,
)


@pytest.fixture
def u00_dir() -> Path:
    return Path(__file__).with_suffix("").parent / "fixtures" / "u00"


@pytest.fixture
def u00_unit(u00_dir: Path) -> FrozenUnit:
    return load_frozen_unit(u00_dir)


@pytest.fixture
def evaluator() -> RsrlHiddenEvaluator:
    return RsrlHiddenEvaluator()


@pytest.fixture
def validator() -> RsrlOutcomeEvaluator:
    return RsrlOutcomeEvaluator()


def _artifact(
    *,
    test_reports: dict[str, Any] | None = None,
    actions: dict[str, list[dict[str, Any]]] | None = None,
    help_requests: dict[str, list[Any]] | None = None,
    file_modifications: dict[str, list[str]] | None = None,
    restart_comparisons: dict[str, dict[str, Any]] | None = None,
    artifact_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal arm run artifact for scorer tests."""
    return {
        "test_reports": test_reports or {},
        "actions": actions or {},
        "help_requests": help_requests or {},
        "file_modifications": file_modifications or {},
        "restart_comparisons": restart_comparisons or {},
        "artifact_bundle": artifact_bundle or {},
    }


def test_hidden_evaluator_test_fixed_verified(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        test_reports={
            "tests/test_core.py::test_new_feature_not_yet_implemented": {
                "test_path": "tests/test_core.py::test_new_feature_not_yet_implemented",
                "passed": True,
                "artifact_ref": "report:event-01",
            },
        },
        artifact_bundle={"report:event-01": {"exit_code": 0}},
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-01"]
    assert outcome.verdict is OutcomeVerdict.VERIFIED
    assert outcome.score == 1.0
    assert outcome.evidence_refs == ("artifact:report:event-01",)
    assert outcome.gaps == ()


def test_hidden_evaluator_test_fixed_not_met(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        test_reports={
            "tests/test_core.py::test_new_feature_not_yet_implemented": {
                "test_path": "tests/test_core.py::test_new_feature_not_yet_implemented",
                "passed": False,
                "artifact_ref": "report:event-01",
            },
        },
        artifact_bundle={"report:event-01": {"exit_code": 1}},
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-01"]
    assert outcome.verdict is OutcomeVerdict.NOT_MET
    assert outcome.score == 0.0
    assert outcome.evidence_refs == ("artifact:report:event-01",)
    assert outcome.gaps


def test_hidden_evaluator_decoy_verified(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        artifact_bundle={"decoy:event-09": True},
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-09"]
    assert outcome.verdict is OutcomeVerdict.VERIFIED
    assert outcome.score == 1.0
    assert outcome.evidence_refs == ("artifact:decoy:no_work_spawned",)
    assert outcome.gaps == ()


def test_hidden_evaluator_decoy_not_met(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        actions={"event-09": [{"kind": "edit", "path": "src/lib.py"}]},
        artifact_bundle={"decoy:event-09": True},
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-09"]
    assert outcome.verdict is OutcomeVerdict.NOT_MET
    assert outcome.score == 0.0
    assert outcome.gaps


def test_outcome_evaluator_rejects_verified_without_evidence(
    u00_unit: FrozenUnit,
    validator: RsrlOutcomeEvaluator,
) -> None:
    expected = {
        "type": "TEST_FIXED",
        "test_path": "tests/test_core.py::test_new_feature_not_yet_implemented",
    }
    draft = EventOutcome(
        event_id="event-01",
        verdict=OutcomeVerdict.VERIFIED,
        score=1.0,
        evidence_refs=(),
        gaps=(),
    )
    artifact = _artifact(
        test_reports={
            "tests/test_core.py::test_new_feature_not_yet_implemented": {
                "test_path": "tests/test_core.py::test_new_feature_not_yet_implemented",
                "passed": True,
                "artifact_ref": "report:event-01",
            },
        },
        artifact_bundle={"report:event-01": {"exit_code": 0}},
    )
    validated = validator.validate(expected, draft, artifact)
    assert validated.verdict is OutcomeVerdict.INVALID
    assert validated.gaps


def test_outcome_evaluator_rejects_decoy_verified_when_actions_exist(
    u00_unit: FrozenUnit,
    validator: RsrlOutcomeEvaluator,
) -> None:
    expected = {"type": "DECOY", "criteria": "no_work_spawned"}
    draft = EventOutcome(
        event_id="event-09",
        verdict=OutcomeVerdict.VERIFIED,
        score=1.0,
        evidence_refs=("artifact:decoy:no_work_spawned",),
        gaps=(),
    )
    artifact = _artifact(
        actions={"event-09": [{"kind": "edit", "path": "src/lib.py"}]},
        artifact_bundle={"decoy:no_work_spawned": True},
    )
    validated = validator.validate(expected, draft, artifact)
    assert validated.verdict is OutcomeVerdict.INVALID
    assert validated.gaps


def test_outcome_evaluator_invalid_on_unknown_event_type(
    u00_unit: FrozenUnit,
    validator: RsrlOutcomeEvaluator,
) -> None:
    expected = {"type": "UNKNOWN_TYPE"}
    draft = EventOutcome(
        event_id="event-02",
        verdict=OutcomeVerdict.VERIFIED,
        score=1.0,
        evidence_refs=("artifact:x",),
        gaps=(),
    )
    artifact = _artifact(artifact_bundle={"x": True})
    validated = validator.validate(expected, draft, artifact)
    assert validated.verdict is OutcomeVerdict.INVALID
    assert validated.gaps


# ---------------------------------------------------------------------------
# INTERFACE_ADAPTED
# ---------------------------------------------------------------------------


def test_hidden_evaluator_interface_adapted_verified(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        actions={
            "event-02": [
                {
                    "kind": "interface_call",
                    "payload": {"call": "lib.transform(items, strict=True)"},
                },
            ],
        },
        artifact_bundle={
            "interface:event-02:matched_call": True,
            "interface:event-02:no_forbidden_call": True,
        },
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-02"]
    assert outcome.verdict is OutcomeVerdict.VERIFIED
    assert outcome.score == 1.0
    assert outcome.gaps == ()


def test_hidden_evaluator_interface_adapted_not_met_forbidden_call(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        actions={
            "event-02": [
                {
                    "kind": "interface_call",
                    "payload": {"call": "lib.transform(items)"},
                },
            ],
        },
        artifact_bundle={
            "interface:event-02:matched_call": True,
            "interface:event-02:no_forbidden_call": True,
        },
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-02"]
    assert outcome.verdict is OutcomeVerdict.NOT_MET
    assert outcome.score == 0.0
    assert outcome.gaps


def test_hidden_evaluator_interface_adapted_unresolved(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact()
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-02"]
    assert outcome.verdict is OutcomeVerdict.UNRESOLVED
    assert outcome.score == 0.0
    assert outcome.gaps


def test_hidden_evaluator_interface_adapted_invalid_missing_required(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        actions={"event-02": [{"kind": "interface_call", "payload": {"call": "x"}}]},
    )
    # Patch expected outcome in memory to drop required_call.
    expected = {
        "type": "INTERFACE_ADAPTED",
        "criteria": "interface_change_handled",
        "required_action_kind": "interface_call",
    }
    event = next(
        e for e in load_events(u00_unit.events_path) if e.event_id == "event-02"
    )
    outcome = evaluator._plugins["INTERFACE_ADAPTED"](event, expected, artifact)
    assert outcome.verdict is OutcomeVerdict.INVALID
    assert outcome.gaps


# ---------------------------------------------------------------------------
# CONFLICT_RESOLVED
# ---------------------------------------------------------------------------


def test_hidden_evaluator_conflict_resolved_verified(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        actions={
            "event-03": [
                {
                    "kind": "constraint_resolution",
                    "payload": {"constraint": "no_dependency_upgrade"},
                },
            ],
        },
        artifact_bundle={
            "conflict:event-03:constraint_matched": True,
            "conflict:event-03:no_forbidden_kind": True,
        },
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-03"]
    assert outcome.verdict is OutcomeVerdict.VERIFIED
    assert outcome.score == 1.0
    assert outcome.gaps == ()


def test_hidden_evaluator_conflict_resolved_not_met_forbidden_kind(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        actions={
            "event-03": [
                {"kind": "dependency_upgrade", "payload": {"constraint": "ignored"}},
            ],
        },
        artifact_bundle={
            "conflict:event-03:constraint_matched": True,
            "conflict:event-03:no_forbidden_kind": True,
        },
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-03"]
    assert outcome.verdict is OutcomeVerdict.NOT_MET
    assert outcome.score == 0.0
    assert outcome.gaps


def test_hidden_evaluator_conflict_resolved_unresolved(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact()
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-03"]
    assert outcome.verdict is OutcomeVerdict.UNRESOLVED
    assert outcome.score == 0.0
    assert outcome.gaps


def test_hidden_evaluator_conflict_resolved_invalid_missing_required(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        actions={
            "event-03": [
                {"kind": "constraint_resolution", "payload": {"constraint": "x"}}
            ]
        },
    )
    expected = {
        "type": "CONFLICT_RESOLVED",
        "criteria": "constraint_satisfied",
        "constraint": "no_dependency_upgrade",
    }
    event = next(
        e for e in load_events(u00_unit.events_path) if e.event_id == "event-03"
    )
    outcome = evaluator._plugins["CONFLICT_RESOLVED"](event, expected, artifact)
    assert outcome.verdict is OutcomeVerdict.INVALID
    assert outcome.gaps


# ---------------------------------------------------------------------------
# RESTART_EQUIVALENT
# ---------------------------------------------------------------------------


def test_hidden_evaluator_restart_equivalent_verified(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        restart_comparisons={"event-04": {"equivalent": True, "differences": []}},
        artifact_bundle={"restart:event-04:comparison": True},
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-04"]
    assert outcome.verdict is OutcomeVerdict.VERIFIED
    assert outcome.score == 1.0
    assert outcome.evidence_refs == ("artifact:restart:event-04:comparison",)
    assert outcome.gaps == ()


def test_hidden_evaluator_restart_equivalent_not_met(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        restart_comparisons={
            "event-04": {
                "equivalent": False,
                "differences": ["commitment_portfolio_digest differs"],
            },
        },
        artifact_bundle={"restart:event-04:comparison": True},
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-04"]
    assert outcome.verdict is OutcomeVerdict.NOT_MET
    assert outcome.score == 0.0
    assert outcome.gaps


def test_hidden_evaluator_restart_equivalent_unresolved(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact()
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-04"]
    assert outcome.verdict is OutcomeVerdict.UNRESOLVED
    assert outcome.score == 0.0
    assert outcome.gaps


# ---------------------------------------------------------------------------
# UNCERTAINTY_RESOLVED
# ---------------------------------------------------------------------------


def test_hidden_evaluator_uncertainty_resolved_verified_by_action(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        actions={
            "event-05": [
                {
                    "kind": "uncertainty_note",
                    "payload": {"statement": "behavior is undefined for empty input"},
                },
            ],
        },
        artifact_bundle={"uncertainty:event-05:accepted_statement": True},
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-05"]
    assert outcome.verdict is OutcomeVerdict.VERIFIED
    assert outcome.score == 1.0
    assert outcome.gaps == ()


def test_hidden_evaluator_uncertainty_resolved_not_met(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        actions={
            "event-05": [
                {"kind": "edit", "payload": {"path": "src/lib.py"}},
            ],
        },
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-05"]
    assert outcome.verdict is OutcomeVerdict.NOT_MET
    assert outcome.score == 0.0
    assert outcome.gaps


def test_hidden_evaluator_uncertainty_resolved_unresolved(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact()
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-05"]
    assert outcome.verdict is OutcomeVerdict.UNRESOLVED
    assert outcome.score == 0.0
    assert outcome.gaps


# ---------------------------------------------------------------------------
# BELIEF_UPDATED
# ---------------------------------------------------------------------------


def test_hidden_evaluator_belief_updated_verified(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        actions={
            "event-06": [
                {
                    "kind": "belief_correction",
                    "payload": {
                        "belief_id": "belief-lib-v1-behavior",
                        "new_value": "strict mode is now required",
                    },
                },
            ],
        },
        artifact_bundle={"belief:event-06:correction": True},
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-06"]
    assert outcome.verdict is OutcomeVerdict.VERIFIED
    assert outcome.score == 1.0
    assert outcome.gaps == ()


def test_hidden_evaluator_belief_updated_not_met_wrong_belief(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        actions={
            "event-06": [
                {
                    "kind": "belief_correction",
                    "payload": {
                        "belief_id": "belief-other",
                        "new_value": "x",
                    },
                },
            ],
        },
        artifact_bundle={"belief:event-06:correction": True},
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-06"]
    assert outcome.verdict is OutcomeVerdict.NOT_MET
    assert outcome.score == 0.0
    assert outcome.gaps


def test_hidden_evaluator_belief_updated_unresolved(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact()
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-06"]
    assert outcome.verdict is OutcomeVerdict.UNRESOLVED
    assert outcome.score == 0.0
    assert outcome.gaps


def test_hidden_evaluator_belief_updated_invalid_missing_required(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        actions={
            "event-06": [
                {
                    "kind": "belief_correction",
                    "payload": {"belief_id": "x", "new_value": "y"},
                }
            ]
        },
    )
    expected = {
        "type": "BELIEF_UPDATED",
        "criteria": "stale_belief_corrected",
    }
    event = next(
        e for e in load_events(u00_unit.events_path) if e.event_id == "event-06"
    )
    outcome = evaluator._plugins["BELIEF_UPDATED"](event, expected, artifact)
    assert outcome.verdict is OutcomeVerdict.INVALID
    assert outcome.gaps


# ---------------------------------------------------------------------------
# COMMITMENT_MET
# ---------------------------------------------------------------------------


def test_hidden_evaluator_commitment_met_verified(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        actions={
            "event-07": [
                {
                    "kind": "commitment_complete",
                    "payload": {"commitment_id": "commit-ship-fix-by-t18", "turn": 15},
                },
            ],
        },
        artifact_bundle={"commitment:event-07:on_time": True},
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-07"]
    assert outcome.verdict is OutcomeVerdict.VERIFIED
    assert outcome.score == 1.0
    assert outcome.gaps == ()


def test_hidden_evaluator_commitment_met_not_met_late(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        actions={
            "event-07": [
                {
                    "kind": "commitment_complete",
                    "payload": {"commitment_id": "commit-ship-fix-by-t18", "turn": 20},
                },
            ],
        },
        artifact_bundle={"commitment:event-07:on_time": True},
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-07"]
    assert outcome.verdict is OutcomeVerdict.NOT_MET
    assert outcome.score == 0.0
    assert outcome.gaps


def test_hidden_evaluator_commitment_met_unresolved(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact()
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-07"]
    assert outcome.verdict is OutcomeVerdict.UNRESOLVED
    assert outcome.score == 0.0
    assert outcome.gaps


def test_hidden_evaluator_commitment_met_invalid_missing_required(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        actions={
            "event-07": [
                {
                    "kind": "commitment_complete",
                    "payload": {"commitment_id": "x", "turn": 1},
                }
            ]
        },
    )
    expected = {
        "type": "COMMITMENT_MET",
        "criteria": "deadline_commitment_satisfied",
        "commitment_id": "commit-ship-fix-by-t18",
    }
    event = next(
        e for e in load_events(u00_unit.events_path) if e.event_id == "event-07"
    )
    outcome = evaluator._plugins["COMMITMENT_MET"](event, expected, artifact)
    assert outcome.verdict is OutcomeVerdict.INVALID
    assert outcome.gaps


# ---------------------------------------------------------------------------
# HELP_ESCALATED
# ---------------------------------------------------------------------------


def test_hidden_evaluator_help_escalated_verified(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        help_requests={
            "event-08": [{"minimum_answer": "approve the breaking interface change"}],
        },
        artifact_bundle={"help:event-08:request": True},
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-08"]
    assert outcome.verdict is OutcomeVerdict.VERIFIED
    assert outcome.score == 1.0
    assert outcome.gaps == ()


def test_hidden_evaluator_help_escalated_not_met_empty_answer(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        help_requests={"event-08": [{"minimum_answer": ""}]},
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-08"]
    assert outcome.verdict is OutcomeVerdict.NOT_MET
    assert outcome.score == 0.0
    assert outcome.gaps


def test_hidden_evaluator_help_escalated_unresolved(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact()
    outcomes = evaluator.evaluate(u00_unit, artifact)
    outcome = outcomes["event-08"]
    assert outcome.verdict is OutcomeVerdict.UNRESOLVED
    assert outcome.score == 0.0
    assert outcome.gaps


# ---------------------------------------------------------------------------
# Evaluator recompute contradiction
# ---------------------------------------------------------------------------


def test_outcome_evaluator_invalid_on_recompute_contradiction(
    u00_unit: FrozenUnit,
    validator: RsrlOutcomeEvaluator,
) -> None:
    expected = {
        "type": "COMMITMENT_MET",
        "criteria": "deadline_commitment_satisfied",
        "commitment_id": "commit-ship-fix-by-t18",
        "deadline_turn": 18,
    }
    draft = EventOutcome(
        event_id="event-07",
        verdict=OutcomeVerdict.VERIFIED,
        score=1.0,
        evidence_refs=("artifact:commitment:event-07:on_time",),
        gaps=(),
    )
    artifact = _artifact(
        actions={
            "event-07": [
                {
                    "kind": "commitment_complete",
                    "payload": {"commitment_id": "commit-ship-fix-by-t18", "turn": 20},
                },
            ],
        },
        artifact_bundle={"commitment:event-07:on_time": True},
    )
    validated = validator.validate(expected, draft, artifact)
    assert validated.verdict is OutcomeVerdict.INVALID
    assert validated.gaps


# ---------------------------------------------------------------------------
# Integration: full u00 artifact where every event scores VERIFIED
# ---------------------------------------------------------------------------


def test_hidden_evaluator_full_u00_all_verified(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        test_reports={
            "tests/test_core.py::test_new_feature_not_yet_implemented": {
                "test_path": "tests/test_core.py::test_new_feature_not_yet_implemented",
                "passed": True,
                "artifact_ref": "report:event-01",
            },
        },
        actions={
            "event-02": [
                {
                    "kind": "interface_call",
                    "payload": {"call": "lib.transform(items, strict=True)"},
                },
            ],
            "event-03": [
                {
                    "kind": "constraint_resolution",
                    "payload": {"constraint": "no_dependency_upgrade"},
                },
            ],
            "event-05": [
                {
                    "kind": "uncertainty_note",
                    "payload": {
                        "statement": "strict mode required after interface change"
                    },
                },
            ],
            "event-06": [
                {
                    "kind": "belief_correction",
                    "payload": {
                        "belief_id": "belief-lib-v1-behavior",
                        "new_value": "strict mode is required",
                    },
                },
            ],
            "event-07": [
                {
                    "kind": "commitment_complete",
                    "payload": {"commitment_id": "commit-ship-fix-by-t18", "turn": 15},
                },
            ],
        },
        help_requests={
            "event-08": [{"minimum_answer": "approve the breaking interface change"}],
        },
        restart_comparisons={
            "event-04": {"equivalent": True, "differences": []},
        },
        artifact_bundle={
            "report:event-01": {"exit_code": 0},
            "interface:event-02:matched_call": True,
            "interface:event-02:no_forbidden_call": True,
            "conflict:event-03:constraint_matched": True,
            "conflict:event-03:no_forbidden_kind": True,
            "restart:event-04:comparison": True,
            "uncertainty:event-05:accepted_statement": True,
            "belief:event-06:correction": True,
            "commitment:event-07:on_time": True,
            "help:event-08:request": True,
            "decoy:no_work_spawned": True,
        },
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    for event_id in (
        "event-01",
        "event-02",
        "event-03",
        "event-04",
        "event-05",
        "event-06",
        "event-07",
        "event-08",
        "event-09",
    ):
        outcome = outcomes[event_id]
        assert outcome.verdict is OutcomeVerdict.VERIFIED, event_id
        assert outcome.score == 1.0, event_id
        assert outcome.gaps == (), event_id


# ---------------------------------------------------------------------------
# Mixed-violation variant
# ---------------------------------------------------------------------------


def test_hidden_evaluator_mixed_violation_decoy_and_late_commitment(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        actions={
            "event-07": [
                {
                    "kind": "commitment_complete",
                    "payload": {"commitment_id": "commit-ship-fix-by-t18", "turn": 20},
                },
            ],
            "event-09": [{"kind": "edit", "path": "src/lib.py"}],
        },
        artifact_bundle={
            "commitment:event-07:on_time": True,
            "decoy:no_work_spawned": True,
        },
    )
    outcomes = evaluator.evaluate(u00_unit, artifact)
    assert outcomes["event-07"].verdict is OutcomeVerdict.NOT_MET
    assert outcomes["event-09"].verdict is OutcomeVerdict.NOT_MET
