from __future__ import annotations

from enum import Enum

from agent_os_contracts import ObservedOutcome, OutcomeStatus
from agent_os_contracts.common import ContractModel, NonEmptyStr

from .task_service import TaskService


class OutcomeAdmissionReason(str, Enum):
    """Enumerable fail-closed reasons for admitting or refusing an outcome."""

    ADMITTED = "ADMITTED"
    TASK_UNAVAILABLE = "TASK_UNAVAILABLE"
    NO_EXPECTED_OUTCOME = "NO_EXPECTED_OUTCOME"
    OUTCOME_SCOPE_MISMATCH = "OUTCOME_SCOPE_MISMATCH"
    OUTCOME_NOT_VERIFIED = "OUTCOME_NOT_VERIFIED"
    UNKNOWN_EVALUATOR = "UNKNOWN_EVALUATOR"
    OUTCOME_NOT_CURRENT = "OUTCOME_NOT_CURRENT"
    EVIDENCE_INVALID = "EVIDENCE_INVALID"


class OutcomeAdmissionDecision(ContractModel):
    """Typed, read-only admission receipt; no state is mutated."""

    admitted: bool
    task_id: NonEmptyStr
    outcome_id: NonEmptyStr | None = None
    reason_code: OutcomeAdmissionReason
    detail: NonEmptyStr | None = None


class OutcomeLearningGate:
    """Decides whether a terminal outcome may update cross-task state.

    Fail-closed and read-only: it returns a typed admission receipt and never
    mutates the Task, the belief ledger or any knowledge asset. Only a VERIFIED
    outcome that (a) binds the task's frozen ExpectedOutcome, (b) has a registered
    evaluator, and (c) is the task's CURRENT trusted outcome is admitted.
    """

    def __init__(self, task_service: TaskService) -> None:
        self._tasks = task_service

    def admit(
        self, task_id: str, outcome: ObservedOutcome
    ) -> OutcomeAdmissionDecision:
        def _deny(
            reason: OutcomeAdmissionReason, detail: str = ""
        ) -> OutcomeAdmissionDecision:
            return OutcomeAdmissionDecision(
                admitted=False,
                task_id=task_id,
                outcome_id=outcome.observed_outcome_id,
                reason_code=reason,
                detail=detail or None,
            )

        try:
            aggregate = self._tasks.get_task(task_id)
        except Exception as exc:
            return _deny(OutcomeAdmissionReason.TASK_UNAVAILABLE, type(exc).__name__)

        expected = aggregate.expected_outcome
        if expected is None:
            return _deny(OutcomeAdmissionReason.NO_EXPECTED_OUTCOME)

        if (
            outcome.expected_outcome_id != expected.expected_outcome_id
            or outcome.task_id != expected.task_id
            or outcome.tenant_id != expected.tenant_id
            or outcome.workspace_id != expected.workspace_id
            or outcome.evaluator_type != expected.evaluator_type
            or outcome.evaluator_version != expected.evaluator_version
        ):
            return _deny(OutcomeAdmissionReason.OUTCOME_SCOPE_MISMATCH)

        if outcome.status is not OutcomeStatus.VERIFIED:
            return _deny(OutcomeAdmissionReason.OUTCOME_NOT_VERIFIED)

        evaluator = self._tasks.evaluator_registry.get(expected.evaluator_type)
        if evaluator is None:
            return _deny(OutcomeAdmissionReason.UNKNOWN_EVALUATOR)

        # Evidence binding is enforced on the SUPPLIED outcome (not only on the
        # stored one), so reusing a genuine outcome id with forged score/evidence/
        # run/window fields is rejected here.
        try:
            evaluator.verify_verified_recording(
                expected,
                outcome,
                report_resolver=self._tasks.validated_test_report,
                now=self._tasks.now(),
            )
        except Exception as exc:
            return _deny(OutcomeAdmissionReason.EVIDENCE_INVALID, type(exc).__name__)

        # Full equality with the current trusted outcome binds every field
        # (run_id, observed_at, score, evidence_refs), rejecting any forgery that
        # reuses a genuine observed_outcome_id.
        current = self._tasks.current_outcome(task_id)
        if (
            current is None
            or current.status is not OutcomeStatus.VERIFIED
            or current != outcome
        ):
            return _deny(OutcomeAdmissionReason.OUTCOME_NOT_CURRENT)

        return OutcomeAdmissionDecision(
            admitted=True,
            task_id=task_id,
            outcome_id=outcome.observed_outcome_id,
            reason_code=OutcomeAdmissionReason.ADMITTED,
        )
