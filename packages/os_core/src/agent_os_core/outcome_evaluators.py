"""Outcome evaluator registry: dispatch by evaluator_type.

The pytest path is extracted from the former monolithic
DeterministicOutcomeEvaluator. New evaluators (e.g. predicate:conjunction)
register here without touching the pytest path.

Behavior-preserving refactor (implementation-cast step 3): the pytest
evaluator's logic is moved verbatim; existing tests must remain green.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, ClassVar, Protocol
from uuid import uuid4

from agent_os_contracts import ExpectedOutcome, ObservedOutcome, OutcomeStatus


# ---------------------------------------------------------------------------
# Structural protocol for validated test reports (avoids circular import with
# task_service.ValidatedTestReport, which satisfies this structurally).
# ---------------------------------------------------------------------------


class _TestReport(Protocol):
    artifact_ids: tuple[str, ...]
    exit_code: int
    completed_at: datetime


TestReportResolver = Callable[..., Any]


# ---------------------------------------------------------------------------
# Evaluator protocol
# ---------------------------------------------------------------------------


class OutcomeEvaluator(Protocol):
    """One evaluator handles one evaluator_type prefix."""

    evaluator_type: ClassVar[str]

    def contract_error(self, expected: ExpectedOutcome) -> str | None:
        """Validate the ExpectedOutcome's type/version/evidence/failure fields.

        Returns an error string (used as the INVALID unresolved_gap and as the
        record_outcome rejection message) or None if supported.
        """
        ...

    def evaluate(
        self,
        expected: ExpectedOutcome,
        *,
        task_id: str,
        run_id: str,
        tenant_id: str,
        workspace_id: str,
        evidence_refs: tuple[str, ...],
        test_exit_code: int | None,
        now: datetime,
    ) -> ObservedOutcome:
        """Produce an ObservedOutcome from evidence."""
        ...

    def verify_verified_recording(
        self,
        expected: ExpectedOutcome,
        outcome: ObservedOutcome,
        *,
        report_resolver: TestReportResolver,
        now: datetime,
    ) -> None:
        """Validate a VERIFIED outcome before it is persisted.

        Raises InvalidTransitionError (imported lazily to avoid cycles) if the
        outcome does not meet the evaluator's evidence requirements.
        """
        ...


# ---------------------------------------------------------------------------
# Pytest evaluator (extracted verbatim from DeterministicOutcomeEvaluator)
# ---------------------------------------------------------------------------

PYTEST_EVALUATOR_TYPE = "pytest"
PYTEST_EVALUATOR_VERSION = "1"
PYTEST_EVIDENCE_REQUIREMENTS = ("test-report",)
PYTEST_FAILURE_SEMANTICS = frozenset(
    {"non-zero exit", "test command exits non-zero", "tests fail"}
)


@dataclass(frozen=True)
class PytestOutcomeEvaluator:
    """Evaluates pytest test-report outcomes. Logic extracted verbatim."""

    evidence_resolver: TestReportResolver | None
    evaluator_type: ClassVar[str] = PYTEST_EVALUATOR_TYPE

    def contract_error(self, expected: ExpectedOutcome) -> str | None:
        if (
            expected.evaluator_type,
            expected.evaluator_version,
        ) != (PYTEST_EVALUATOR_TYPE, PYTEST_EVALUATOR_VERSION):
            return "unsupported evaluator"
        if tuple(expected.evidence_requirements) != PYTEST_EVIDENCE_REQUIREMENTS:
            return "unsupported evidence requirements"
        if (
            not expected.failure_semantics
            or len(set(expected.failure_semantics)) != len(expected.failure_semantics)
            or not set(expected.failure_semantics).issubset(PYTEST_FAILURE_SEMANTICS)
        ):
            return "unsupported failure semantics"
        return None

    def evaluate(
        self,
        expected: ExpectedOutcome,
        *,
        task_id: str,
        run_id: str,
        tenant_id: str,
        workspace_id: str,
        evidence_refs: tuple[str, ...],
        test_exit_code: int | None,
        now: datetime,
    ) -> ObservedOutcome:
        observed = now
        gaps: list[str] = []
        status: OutcomeStatus
        score: float | None = None

        if (
            task_id != expected.task_id
            or tenant_id != expected.tenant_id
            or workspace_id != expected.workspace_id
        ):
            status = OutcomeStatus.INVALID
            gaps.append("expected outcome scope mismatch")
        elif self.contract_error(expected) == "unsupported evaluator":
            status = OutcomeStatus.INVALID
            gaps.append("unsupported evaluator")
        elif self.contract_error(expected) == "unsupported evidence requirements":
            status = OutcomeStatus.INVALID
            gaps.append("unsupported evidence requirements")
        elif self.contract_error(expected) is not None:
            status = OutcomeStatus.INVALID
            gaps.append("unsupported failure semantics")
        elif observed < expected.frozen_at:
            status = OutcomeStatus.INVALID
            gaps.append("observation predates frozen contract")
        elif observed > expected.frozen_at + timedelta(
            seconds=expected.observation_window_seconds
        ):
            status = OutcomeStatus.UNRESOLVED
            gaps.append("observation window expired")
        elif not any(ref.startswith("artifact:") for ref in evidence_refs):
            status = OutcomeStatus.UNRESOLVED
            gaps.append("missing required evidence: test-report")
        elif self.evidence_resolver is None:
            status = OutcomeStatus.UNRESOLVED
            gaps.append("test-report evidence is not bound to the durable event chain")
        elif (
            report := self.evidence_resolver(task_id, run_id)
        ) is None or not set(report.artifact_ids).issubset(evidence_refs):
            status = OutcomeStatus.UNRESOLVED
            gaps.append("test-report evidence is not bound to the durable event chain")
        elif report.completed_at < expected.frozen_at:
            status = OutcomeStatus.INVALID
            gaps.append("test report predates frozen contract")
        elif test_exit_code is None:
            status = OutcomeStatus.UNRESOLVED
            gaps.append("missing pytest exit code")
        elif test_exit_code != report.exit_code:
            status = OutcomeStatus.INVALID
            gaps.append("pytest exit code does not match durable test report")
        else:
            score = 1.0 if report.exit_code == 0 else 0.0
            if report.exit_code != 0:
                status = OutcomeStatus.NOT_MET
                gaps.extend(expected.failure_semantics)
            elif score < expected.threshold:
                status = OutcomeStatus.NOT_MET
                gaps.append("frozen threshold not met")
            else:
                status = OutcomeStatus.VERIFIED

        return ObservedOutcome(
            observed_outcome_id=f"observed-{uuid4()}",
            expected_outcome_id=expected.expected_outcome_id,
            task_id=task_id,
            run_id=run_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            evaluator_type=expected.evaluator_type,
            evaluator_version=expected.evaluator_version,
            status=status,
            score=score,
            confidence=1.0,
            evidence_refs=evidence_refs,
            unresolved_gaps=tuple(gaps),
            observed_at=observed,
        )

    def verify_verified_recording(
        self,
        expected: ExpectedOutcome,
        outcome: ObservedOutcome,
        *,
        report_resolver: TestReportResolver,
        now: datetime,
    ) -> None:
        from .errors import InvalidTransitionError

        score = outcome.score
        if score is None or score != 1.0:
            raise InvalidTransitionError(
                "verified outcome score does not match the trusted pytest score"
            )
        if score < expected.threshold:
            raise InvalidTransitionError(
                "verified outcome score is below frozen threshold"
            )
        if outcome.observed_at > now:
            raise InvalidTransitionError(
                "verified outcome cannot be observed in the future"
            )
        if now > expected.frozen_at + timedelta(
            seconds=expected.observation_window_seconds
        ):
            raise InvalidTransitionError(
                "verified outcome observation window is closed"
            )
        if not (
            expected.frozen_at
            <= outcome.observed_at
            <= expected.frozen_at
            + timedelta(seconds=expected.observation_window_seconds)
        ):
            raise InvalidTransitionError(
                "verified outcome is outside the frozen observation window"
            )
        report = report_resolver(outcome.task_id, outcome.run_id)
        if report is None:
            raise InvalidTransitionError(
                "verified outcome lacks durable test-report evidence"
            )
        if not set(report.artifact_ids).issubset(outcome.evidence_refs):
            raise InvalidTransitionError(
                "verified outcome evidence does not match durable test report"
            )
        if report.exit_code != 0:
            raise InvalidTransitionError(
                "verified outcome is bound to a failing test report"
            )
        if report.completed_at < expected.frozen_at:
            raise InvalidTransitionError(
                "verified test report predates frozen contract"
            )
        if report.completed_at > outcome.observed_at:
            raise InvalidTransitionError(
                "verified outcome predates its durable test report"
            )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class OutcomeEvaluatorRegistry:
    """Maps evaluator_type → OutcomeEvaluator. Fail-closed on unknown types."""

    def __init__(self) -> None:
        self._evaluators: dict[str, OutcomeEvaluator] = {}

    def register(self, evaluator: OutcomeEvaluator) -> None:
        self._evaluators[evaluator.evaluator_type] = evaluator

    def get(self, evaluator_type: str) -> OutcomeEvaluator | None:
        return self._evaluators.get(evaluator_type)

    def contract_error(self, expected: ExpectedOutcome) -> str | None:
        evaluator = self._evaluators.get(expected.evaluator_type)
        if evaluator is None:
            return "unsupported evaluator"
        return evaluator.contract_error(expected)

    def evaluate(
        self,
        expected: ExpectedOutcome,
        *,
        task_id: str,
        run_id: str,
        tenant_id: str,
        workspace_id: str,
        evidence_refs: tuple[str, ...],
        test_exit_code: int | None,
        now: datetime,
    ) -> ObservedOutcome:
        evaluator = self._evaluators.get(expected.evaluator_type)
        if evaluator is None:
            return ObservedOutcome(
                observed_outcome_id=f"observed-{uuid4()}",
                expected_outcome_id=expected.expected_outcome_id,
                task_id=task_id,
                run_id=run_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                evaluator_type=expected.evaluator_type,
                evaluator_version=expected.evaluator_version,
                status=OutcomeStatus.INVALID,
                score=None,
                confidence=1.0,
                evidence_refs=evidence_refs,
                unresolved_gaps=("unsupported evaluator",),
                observed_at=now,
            )
        return evaluator.evaluate(
            expected,
            task_id=task_id,
            run_id=run_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            evidence_refs=evidence_refs,
            test_exit_code=test_exit_code,
            now=now,
        )


def default_registry(
    evidence_resolver: TestReportResolver | None = None,
) -> OutcomeEvaluatorRegistry:
    """Registry with the pytest evaluator registered."""
    registry = OutcomeEvaluatorRegistry()
    registry.register(PytestOutcomeEvaluator(evidence_resolver=evidence_resolver))
    return registry
