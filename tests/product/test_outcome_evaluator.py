from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from agent_os_contracts import ExpectedOutcome, OutcomeStatus
from agent_os_core import DeterministicOutcomeEvaluator, ValidatedTestReport


FROZEN_AT = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)


def _expected(**updates: Any) -> ExpectedOutcome:
    values: dict[str, Any] = {
        "expected_outcome_id": "expected-1",
        "task_id": "task-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "evaluator_type": "pytest",
        "evaluator_version": "1",
        "evidence_requirements": ("test-report",),
        "failure_semantics": ("non-zero exit",),
        "threshold": 1.0,
        "observation_window_seconds": 60,
        "frozen_at": FROZEN_AT,
    }
    values.update(updates)
    return ExpectedOutcome(**values)


def _evaluate(
    expected: ExpectedOutcome,
    *,
    trusted: bool = True,
    **updates: Any,
):
    values: dict[str, Any] = {
        "task_id": "task-1",
        "run_id": "run-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "evidence_refs": ("artifact:test-report",),
        "test_exit_code": 0,
        "now": FROZEN_AT + timedelta(seconds=30),
    }
    values.update(updates)
    evidence_refs = tuple(values["evidence_refs"])
    exit_code = values["test_exit_code"]
    if trusted and isinstance(exit_code, int):
        report = ValidatedTestReport(
            artifact_ids=evidence_refs,
            exit_code=exit_code,
            node_id="tests",
            action_id="action-tests",
            receipt_id="receipt-tests",
            completed_sequence=10,
            completed_at=FROZEN_AT + timedelta(seconds=20),
        )

        def resolve(_task_id: str, _run_id: str) -> ValidatedTestReport:
            return report

        evaluator = DeterministicOutcomeEvaluator(resolve)
    else:
        evaluator = DeterministicOutcomeEvaluator()
    return evaluator.evaluate(expected, **values)


def test_score_below_frozen_threshold_is_not_verified() -> None:
    outcome = _evaluate(_expected(threshold=2.0))

    assert outcome.status is OutcomeStatus.NOT_MET
    assert outcome.score == 1.0


def test_reproduced_false_verified_attack_fails_closed() -> None:
    outcome = _evaluate(
        _expected(
            threshold=999.0,
            evidence_requirements=("test-report", "independent-review"),
        ),
        trusted=False,
        evidence_refs=("artifact:" + "a" * 64,),
    )

    assert outcome.status is OutcomeStatus.INVALID
    assert outcome.score is None
    assert "unsupported evidence requirements" in outcome.unresolved_gaps


def test_unknown_evaluator_identity_is_invalid() -> None:
    outcome = _evaluate(_expected(evaluator_type="unknown"))

    assert outcome.status is OutcomeStatus.INVALID
    assert "unsupported evaluator" in outcome.unresolved_gaps


def test_missing_required_test_report_is_unresolved() -> None:
    outcome = _evaluate(_expected(), evidence_refs=())

    assert outcome.status is OutcomeStatus.UNRESOLVED
    assert "missing required evidence: test-report" in outcome.unresolved_gaps


def test_observation_after_frozen_window_is_unresolved() -> None:
    outcome = _evaluate(_expected(), now=FROZEN_AT + timedelta(seconds=61))

    assert outcome.status is OutcomeStatus.UNRESOLVED
    assert "observation window expired" in outcome.unresolved_gaps


def test_unsupported_failure_semantics_is_invalid() -> None:
    outcome = _evaluate(_expected(failure_semantics=("model says it is good",)))

    assert outcome.status is OutcomeStatus.INVALID
    assert "unsupported failure semantics" in outcome.unresolved_gaps


def test_scope_mismatch_is_invalid() -> None:
    outcome = _evaluate(_expected(), task_id="task-other")

    assert outcome.status is OutcomeStatus.INVALID
    assert "expected outcome scope mismatch" in outcome.unresolved_gaps


def test_forged_artifact_cannot_produce_verified_without_trusted_resolver() -> None:
    outcome = _evaluate(
        _expected(),
        trusted=False,
        evidence_refs=("artifact:" + "a" * 64,),
    )

    assert outcome.status is OutcomeStatus.UNRESOLVED
    assert "test-report evidence is not bound to the durable event chain" in (
        outcome.unresolved_gaps
    )


def test_missing_runtime_exit_code_is_not_defaulted_to_failure() -> None:
    report = ValidatedTestReport(
        artifact_ids=("artifact:" + "b" * 64,),
        exit_code=0,
        node_id="tests",
        action_id="action-tests",
        receipt_id="receipt-tests",
        completed_sequence=10,
        completed_at=FROZEN_AT + timedelta(seconds=20),
    )

    def resolve(_task_id: str, _run_id: str) -> ValidatedTestReport:
        return report

    outcome = DeterministicOutcomeEvaluator(resolve).evaluate(
        _expected(),
        task_id="task-1",
        run_id="run-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        evidence_refs=report.artifact_ids,
        test_exit_code=None,
        now=FROZEN_AT + timedelta(seconds=30),
    )

    assert outcome.status is OutcomeStatus.UNRESOLVED
    assert "missing pytest exit code" in outcome.unresolved_gaps


def test_evaluator_uses_injected_clock_when_caller_omits_now() -> None:
    report = ValidatedTestReport(
        artifact_ids=("artifact:" + "c" * 64,),
        exit_code=0,
        node_id="tests",
        action_id="action-tests",
        receipt_id="receipt-tests",
        completed_sequence=10,
        completed_at=FROZEN_AT + timedelta(seconds=20),
    )

    evaluator = DeterministicOutcomeEvaluator(
        lambda _task_id, _run_id: report,
        clock=lambda: FROZEN_AT + timedelta(seconds=30),
    )
    outcome = evaluator.evaluate(
        _expected(),
        task_id="task-1",
        run_id="run-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        evidence_refs=report.artifact_ids,
        test_exit_code=0,
    )

    assert outcome.status is OutcomeStatus.VERIFIED
    assert outcome.observed_at == FROZEN_AT + timedelta(seconds=30)
