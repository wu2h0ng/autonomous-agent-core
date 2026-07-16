from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.research.r_srl_1.harness import FrozenUnit, load_frozen_unit
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
    artifact_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal arm run artifact for scorer tests."""
    return {
        "test_reports": test_reports or {},
        "actions": actions or {},
        "help_requests": help_requests or {},
        "file_modifications": file_modifications or {},
        "artifact_bundle": artifact_bundle or {},
    }


def test_hidden_evaluator_test_fixed_verified(
    u00_unit: FrozenUnit,
    evaluator: RsrlHiddenEvaluator,
) -> None:
    artifact = _artifact(
        test_reports={
            "tests/test_lib.py::test_new_feature": {
                "test_path": "tests/test_lib.py::test_new_feature",
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
            "tests/test_lib.py::test_new_feature": {
                "test_path": "tests/test_lib.py::test_new_feature",
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
        "test_path": "tests/test_lib.py::test_new_feature",
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
            "tests/test_lib.py::test_new_feature": {
                "test_path": "tests/test_lib.py::test_new_feature",
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
