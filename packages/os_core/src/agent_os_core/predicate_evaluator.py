"""PredicateSet persistence and the predicate conjunction evaluator.

The PredicateConjunctionEvaluator is registered in the OutcomeEvaluatorRegistry
under evaluator_type "predicate:conjunction". It loads the frozen PredicateSet
by content digest (ExpectedOutcome.evaluator_version), runs each blocking
predicate's checker, and aggregates conjunctively.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, ClassVar, Protocol
from uuid import uuid4

from agent_os_contracts import (
    ExpectedOutcome,
    ObservedOutcome,
    OutcomeStatus,
    PredicateSet,
)

from .evidence_accessor import EvidenceAccessor
from .outcome_evaluators import TestReportResolver
from .predicate_checkers import PredicateCheckError, run_checker

PREDICATE_CONJUNCTION_TYPE = "predicate:conjunction"
PREDICATE_CONJUNCTION_VERSION = "1"
PREDICATE_EVIDENCE_REQUIREMENTS = ("predicate-set",)
PREDICATE_FAILURE_SEMANTICS = frozenset({"blocking predicate failed"})


# ---------------------------------------------------------------------------
# PredicateSet store
# ---------------------------------------------------------------------------


class PredicateSetStore(Protocol):
    """Assembly-time persistence for frozen PredicateSets."""

    def save(self, predicate_set: PredicateSet) -> None: ...

    def load(self, digest: str) -> PredicateSet | None: ...


class InMemoryPredicateSetStore:
    """In-memory store for tests and single-process use."""

    def __init__(self) -> None:
        self._sets: dict[str, PredicateSet] = {}

    def save(self, predicate_set: PredicateSet) -> None:
        self._sets[predicate_set.content_key()] = predicate_set

    def load(self, digest: str) -> PredicateSet | None:
        return self._sets.get(digest)


# ---------------------------------------------------------------------------
# Evidence accessor provider
# ---------------------------------------------------------------------------

# A factory that builds an EvidenceAccessor for a given task/run at evaluation time.
EvidenceAccessorFactory = Callable[
    [str, str, str, str, tuple[str, ...]],
    EvidenceAccessor,
]


# ---------------------------------------------------------------------------
# Predicate conjunction evaluator
# ---------------------------------------------------------------------------


class PredicateConjunctionEvaluator:
    """Evaluates all blocking predicates in a frozen PredicateSet.

    Conjunctive semantics:
    - ALL blocking predicates pass → VERIFIED
    - ANY blocking predicate fails → NOT_MET
    - evidence missing for a blocking predicate → UNRESOLVED
    - advisory predicates (blocking=False) are checked but never affect status
    """

    evaluator_type: ClassVar[str] = PREDICATE_CONJUNCTION_TYPE

    def __init__(
        self,
        predicate_store: PredicateSetStore,
        accessor_factory: EvidenceAccessorFactory | None = None,
        judge_checker: Any | None = None,
    ) -> None:
        self._store = predicate_store
        self._accessor_factory = accessor_factory
        self._judge_checker = judge_checker

    def contract_error(self, expected: ExpectedOutcome) -> str | None:
        if expected.evaluator_type != PREDICATE_CONJUNCTION_TYPE:
            return "unsupported evaluator"
        if tuple(expected.evidence_requirements) != PREDICATE_EVIDENCE_REQUIREMENTS:
            return "unsupported evidence requirements"
        if (
            not expected.failure_semantics
            or len(set(expected.failure_semantics)) != len(expected.failure_semantics)
            or not set(expected.failure_semantics).issubset(
                PREDICATE_FAILURE_SEMANTICS
            )
        ):
            return "unsupported failure semantics"
        # Verify the predicate set is loadable
        if self._store.load(expected.evaluator_version) is None:
            return "predicate set not found"
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
        gaps: list[str] = []
        score: float | None = None

        # Scope check
        if (
            task_id != expected.task_id
            or tenant_id != expected.tenant_id
            or workspace_id != expected.workspace_id
        ):
            return self._outcome(
                expected, task_id, run_id, tenant_id, workspace_id,
                evidence_refs, OutcomeStatus.INVALID, None,
                ("expected outcome scope mismatch",), now,
            )

        # Time window
        if now < expected.frozen_at:
            return self._outcome(
                expected, task_id, run_id, tenant_id, workspace_id,
                evidence_refs, OutcomeStatus.INVALID, None,
                ("observation predates frozen contract",), now,
            )
        if now > expected.frozen_at + timedelta(
            seconds=expected.observation_window_seconds
        ):
            return self._outcome(
                expected, task_id, run_id, tenant_id, workspace_id,
                evidence_refs, OutcomeStatus.UNRESOLVED, None,
                ("observation window expired",), now,
            )

        # Load predicate set
        predicate_set = self._store.load(expected.evaluator_version)
        if predicate_set is None:
            return self._outcome(
                expected, task_id, run_id, tenant_id, workspace_id,
                evidence_refs, OutcomeStatus.INVALID, None,
                ("predicate set not found",), now,
            )

        # Build evidence accessor
        if self._accessor_factory is None:
            return self._outcome(
                expected, task_id, run_id, tenant_id, workspace_id,
                evidence_refs, OutcomeStatus.UNRESOLVED, None,
                ("evidence accessor not configured",), now,
            )
        accessor = self._accessor_factory(
            task_id, run_id, tenant_id, workspace_id, evidence_refs
        )

        # Evaluate predicates
        blocking = [p for p in predicate_set.predicates if p.blocking]
        advisory = [p for p in predicate_set.predicates if not p.blocking]

        if not blocking:
            return self._outcome(
                expected, task_id, run_id, tenant_id, workspace_id,
                evidence_refs, OutcomeStatus.INVALID, None,
                ("no blocking predicates in frozen set",), now,
            )

        passed_count = 0
        failed_predicates: list[str] = []
        unresolved_predicates: list[str] = []
        all_evidence_refs: set[str] = set()

        for predicate in blocking:
            try:
                passed, refs, detail = run_checker(predicate, accessor)
            except PredicateCheckError as exc:
                failed_predicates.append(
                    f"{predicate.predicate_id}: {exc}"
                )
                continue
            all_evidence_refs.update(refs)
            if passed is None:
                unresolved_predicates.append(
                    f"{predicate.predicate_id}: {detail}"
                )
            elif passed:
                passed_count += 1
            else:
                failed_predicates.append(
                    f"{predicate.predicate_id}: {detail}"
                )

        # Run advisory predicates (record but don't affect status)
        for predicate in advisory:
            try:
                if (
                    predicate.check_type.value == "LLM_JUDGE"
                    and self._judge_checker is not None
                ):
                    _, refs, _ = self._judge_checker.check(predicate, accessor)
                else:
                    _, refs, _ = run_checker(predicate, accessor)
                all_evidence_refs.update(refs)
            except Exception:
                # Advisory predicates (including an LLM judge whose provider
                # call fails) must never affect the outcome.
                pass

        # Determine status (conjunctive)
        if failed_predicates:
            status = OutcomeStatus.NOT_MET
            gaps.extend(failed_predicates)
            score = passed_count / len(blocking)
        elif unresolved_predicates:
            status = OutcomeStatus.UNRESOLVED
            gaps.extend(unresolved_predicates)
        else:
            status = OutcomeStatus.VERIFIED
            score = 1.0

        if score is not None and score < expected.threshold and status is OutcomeStatus.VERIFIED:
            status = OutcomeStatus.NOT_MET
            gaps.append("frozen threshold not met")

        return self._outcome(
            expected, task_id, run_id, tenant_id, workspace_id,
            tuple(sorted(all_evidence_refs)) or evidence_refs,
            status, score, tuple(gaps), now,
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

        if outcome.score is None or outcome.score != 1.0:
            raise InvalidTransitionError(
                "verified outcome score does not match conjunctive pass"
            )
        if outcome.score < expected.threshold:
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
        predicate_set = self._store.load(expected.evaluator_version)
        if predicate_set is None:
            raise InvalidTransitionError(
                "verified outcome predicate set not found"
            )
        blocking_count = sum(1 for p in predicate_set.predicates if p.blocking)
        if blocking_count == 0:
            raise InvalidTransitionError(
                "verified outcome has no blocking predicates"
            )
        # A VERIFIED predicate outcome must be re-verified against the durable
        # evidence, mirroring PytestOutcomeEvaluator: re-run every blocking
        # checker and require its evidence to be bound by the recorded refs.
        if not outcome.evidence_refs:
            raise InvalidTransitionError(
                "verified outcome carries no evidence references"
            )
        if self._accessor_factory is None:
            raise InvalidTransitionError(
                "verified outcome cannot be re-verified without an evidence accessor"
            )
        accessor = self._accessor_factory(
            outcome.task_id,
            outcome.run_id,
            outcome.tenant_id,
            outcome.workspace_id,
            outcome.evidence_refs,
        )
        for predicate in predicate_set.predicates:
            if not predicate.blocking:
                continue
            try:
                passed, refs, detail = run_checker(predicate, accessor)
            except PredicateCheckError as exc:
                raise InvalidTransitionError(
                    f"verified outcome predicate {predicate.predicate_id} "
                    f"check failed: {exc}"
                ) from exc
            if passed is not True:
                raise InvalidTransitionError(
                    f"verified outcome predicate {predicate.predicate_id} "
                    f"did not pass: {detail}"
                )
            if not set(refs).issubset(outcome.evidence_refs):
                raise InvalidTransitionError(
                    f"verified outcome predicate {predicate.predicate_id} "
                    "cites evidence outside the recorded outcome"
                )

    @staticmethod
    def _outcome(
        expected: ExpectedOutcome,
        task_id: str,
        run_id: str,
        tenant_id: str,
        workspace_id: str,
        evidence_refs: tuple[str, ...],
        status: OutcomeStatus,
        score: float | None,
        gaps: tuple[str, ...],
        now: datetime,
    ) -> ObservedOutcome:
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
            unresolved_gaps=gaps,
            observed_at=now,
        )
