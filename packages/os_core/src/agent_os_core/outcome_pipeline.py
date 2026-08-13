from __future__ import annotations

from typing import Any
from uuid import uuid4

from agent_os_contracts import (
    ExpectedOutcome,
    ObservedOutcome,
    OutcomeStatus,
)

from .errors import RunExecutionError


class OutcomePipeline:
    """Outcome evaluation and revalidation before run finalization."""

    def __init__(
        self,
        evaluator: Any,
        tasks: Any,
    ) -> None:
        self._evaluator = evaluator
        self._tasks = tasks

    def evaluate(
        self,
        expected: ExpectedOutcome,
        *,
        task_id: str,
        run_id: str,
        tenant_id: str,
        workspace_id: str,
        evidence: tuple[str, ...],
        test_exit_code: int | None,
    ) -> ObservedOutcome:
        return self._evaluator.evaluate(
            expected,
            task_id=task_id,
            run_id=run_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            evidence_refs=evidence,
            test_exit_code=test_exit_code,
        )

    def revalidate_before_finalization(
        self,
        task_id: str,
        outcome: ObservedOutcome,
    ) -> ObservedOutcome:
        if outcome.status is not OutcomeStatus.VERIFIED:
            return outcome
        aggregate = self._tasks.get_task(task_id)
        if aggregate.run is None or aggregate.expected_outcome is None:
            raise RunExecutionError(
                "outcome finalization lost its committed bindings"
            )
        current = self._tasks.current_outcome(task_id)
        if current is not None and current.status is OutcomeStatus.VERIFIED:
            return outcome
        replacement = ObservedOutcome(
            observed_outcome_id=f"observed-{uuid4()}",
            expected_outcome_id=outcome.expected_outcome_id,
            task_id=outcome.task_id,
            run_id=outcome.run_id,
            tenant_id=outcome.tenant_id,
            workspace_id=outcome.workspace_id,
            evaluator_type=outcome.evaluator_type,
            evaluator_version=outcome.evaluator_version,
            status=OutcomeStatus.UNRESOLVED,
            score=None,
            confidence=1.0,
            evidence_refs=outcome.evidence_refs,
            unresolved_gaps=(
                "verified evidence became stale before run finalization",
            ),
            observed_at=self._tasks.now(),
        )
        self._tasks.record_outcome(task_id, replacement)
        return replacement
