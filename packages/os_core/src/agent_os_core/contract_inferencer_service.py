"""ContractInferencerService: application-level facade for contract inference.

This is the entry point for API/CLI callers. It wraps the ContractInferencer
pipeline, persists frozen PredicateSets, produces ExpectedOutcome records,
and automatically records HCW telemetry at every human-interaction boundary.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_os_contracts import (
    ClarificationAnswer,
    ExpectedOutcome,
    InferenceReport,
    InferenceTelemetry,
    InferredTaskContract,
    PredicateConfirmation,
    PredicateSet,
)

from .contract_inferencer import ContractInferencer
from .llm_judge import LLMJudgeChecker
from .predicate_evaluator import (
    PREDICATE_CONJUNCTION_TYPE,
    PREDICATE_EVIDENCE_REQUIREMENTS,
    PREDICATE_FAILURE_SEMANTICS,
)
from .predicate_set_store import SQLitePredicateSetStore
from .provider import ProviderPort
from .semantic_proposer import SemanticProposer

DEFAULT_OBSERVATION_WINDOW_SECONDS = 3600


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ContractInferencerService:
    """Facade for the full contract inference lifecycle.

    HCW telemetry is recorded automatically at each three-call API boundary.
    Retrieve it with service.telemetry(contract_id) after any call.

    Usage:
        service = ContractInferencerService(
            provider=llm_provider, model_id="gpt-x",
            store_path="agent-os.sqlite3",
        )
        contract, report = service.infer(mandate_text, tool_schemas, task_id=...)
        contract, report = service.apply_clarification(contract, answers)
        contract, predicate_set, report = service.apply_confirmation(contract, confirmations)
        tel = service.telemetry(contract.contract_id)
        print(tel.operator_wall_seconds, tel.operator_intervention_count)
    """

    def __init__(
        self,
        provider: ProviderPort,
        *,
        model_id: str,
        store_path: str = ":memory:",
        judge_provider: ProviderPort | None = None,
        judge_model_id: str | None = None,
        observation_window_seconds: int = DEFAULT_OBSERVATION_WINDOW_SECONDS,
    ) -> None:
        self._model_id = model_id
        self._observation_window = observation_window_seconds

        proposer = SemanticProposer(provider, model_id=model_id)
        judge_checker = None
        if judge_provider is not None and judge_model_id is not None:
            judge_checker = LLMJudgeChecker(
                judge_provider, judge_model_id=judge_model_id
            )
        self._inferencer = ContractInferencer(proposer, model_id=model_id)
        self._judge_checker = judge_checker
        self._store = SQLitePredicateSetStore(store_path)
        self._telemetry: dict[str, InferenceTelemetry] = {}

    @property
    def predicate_set_store(self) -> SQLitePredicateSetStore:
        return self._store

    def telemetry(self, contract_id: str) -> InferenceTelemetry | None:
        """Retrieve HCW telemetry for a contract. Auto-recorded, never manual."""
        return self._telemetry.get(contract_id)

    def infer(
        self,
        mandate_text: str,
        tool_schemas: list[dict[str, Any]],
        *,
        mandate_id: str | None = None,
        task_id: str | None = None,
        deliverable_schema: dict[str, Any] | None = None,
    ) -> tuple[InferredTaskContract | None, InferenceReport]:
        """Stage 0-3: infer a contract from mandate + tool schemas."""
        started = _now()
        monotonic_start = time.monotonic()

        contract, report = self._inferencer.infer(
            mandate_text=mandate_text,
            tool_schemas=tool_schemas,
            mandate_id=mandate_id,
            task_id=task_id,
            deliverable_schema=deliverable_schema,
        )

        completed = _now()
        latency_ms = int((time.monotonic() - monotonic_start) * 1000)

        # Build telemetry
        tel_id = f"telemetry:{uuid4()}"
        cid = contract.contract_id if contract else report.contract_id
        tid = contract.task_id if contract else (task_id or "unknown")

        questions_raised = report.clarification_raised
        clarification_presented = completed if questions_raised > 0 else None
        confirmation_presented = (
            completed if report.pipeline_state == "CONFIRMATION_PENDING" else None
        )

        rejection_reason = None
        if report.pipeline_state == "REJECTED":
            rejection_reason = (
                contract.warnings[0] if contract and contract.warnings else "pipeline rejected"
            )

        tel = InferenceTelemetry(
            telemetry_id=tel_id,
            contract_id=cid,
            task_id=tid,
            model_id=self._model_id,
            infer_started_at=started,
            infer_completed_at=completed,
            inference_latency_ms=latency_ms,
            clarification_presented_at=clarification_presented,
            confirmation_presented_at=confirmation_presented,
            questions_raised=questions_raised,
            predicates_presented=(
                report.mechanical_count + report.semantic_proposed_count
                if report.pipeline_state == "CONFIRMATION_PENDING"
                else 0
            ),
            pipeline_state=report.pipeline_state,
            blocking_count=report.blocking_count,
            rejection_reason=rejection_reason,
            completed_at=completed if report.pipeline_state == "REJECTED" else None,
        )
        self._telemetry[cid] = tel
        return contract, report

    def apply_clarification(
        self,
        contract: InferredTaskContract,
        answers: list[ClarificationAnswer],
    ) -> tuple[InferredTaskContract, InferenceReport]:
        """Stage 4: apply clarification answers. Records HCW timing/counts."""
        received_at = _now()
        tel = self._telemetry.get(contract.contract_id)

        # Count answer types before applying
        yes_count = sum(1 for a in answers if a.answer.strip().lower() == "yes")
        no_count = sum(1 for a in answers if a.answer.strip().lower() == "no")
        choice_count = len(answers) - yes_count - no_count

        # Count unanswered questions
        answered_q_ids = {a.question_id for a in answers}
        unanswered = [
            q for q in contract.clarification_questions
            if q.question_id not in answered_q_ids
        ]
        downgraded = sum(1 for q in unanswered if q.on_unanswered == "downgrade")
        dropped = sum(1 for q in unanswered if q.on_unanswered == "drop")

        contract, report = self._inferencer.apply_clarification(contract, answers)

        if tel is not None:
            updates: dict[str, Any] = {
                "clarification_received_at": received_at,
                "questions_answered_yes": tel.questions_answered_yes + yes_count,
                "questions_answered_no": tel.questions_answered_no + no_count,
                "questions_answered_choice": tel.questions_answered_choice + choice_count,
                "questions_unanswered_downgraded": tel.questions_unanswered_downgraded + downgraded,
                "questions_unanswered_dropped": tel.questions_unanswered_dropped + dropped,
                "pipeline_state": report.pipeline_state,
            }
            # If moving to confirmation pending, stamp confirmation presented
            if report.pipeline_state == "CONFIRMATION_PENDING":
                updates["confirmation_presented_at"] = received_at
                updates["predicates_presented"] = (
                    report.mechanical_count + report.semantic_proposed_count
                )
            self._telemetry[contract.contract_id] = tel.model_copy(update=updates)

        return contract, report

    def apply_confirmation(
        self,
        contract: InferredTaskContract,
        confirmations: list[PredicateConfirmation],
        *,
        tenant_id: str = "tenant:1",
        workspace_id: str = "ws:1",
    ) -> tuple[InferredTaskContract, PredicateSet | None, InferenceReport]:
        """Stage 4.5: apply confirmations, freeze, persist, and finalize telemetry."""
        received_at = _now()
        tel = self._telemetry.get(contract.contract_id)

        # Count decisions
        approved = sum(1 for c in confirmations if c.decision == "approve")
        rejected = sum(1 for c in confirmations if c.decision == "reject")
        adjusted = sum(1 for c in confirmations if c.decision == "adjust")
        pre_endorsed = 0
        if tel:
            # Pre-endorsed = predicates that became CONFIRMED without explicit confirmation
            # (came through clarification with confidence=1.0)
            explicitly_confirmed = {c.predicate_id for c in confirmations}
            pre_endorsed = sum(
                1
                for c in contract.confirmation_records
                if c.pre_endorsed and c.predicate_id not in explicitly_confirmed
            )

        contract, predicate_set, report = self._inferencer.apply_confirmation(
            contract,
            confirmations,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        if predicate_set is not None:
            self._store.save(predicate_set)

        if tel is not None:
            updates: dict[str, Any] = {
                "confirmation_received_at": received_at,
                "predicates_approved": tel.predicates_approved + approved,
                "predicates_rejected": tel.predicates_rejected + rejected,
                "predicates_adjusted": tel.predicates_adjusted + adjusted,
                "predicates_pre_endorsed": pre_endorsed,
                "pipeline_state": report.pipeline_state,
                "blocking_count": report.blocking_count,
                "completed_at": received_at,
            }
            if report.pipeline_state == "REJECTED":
                updates["rejection_reason"] = "zero blocking predicates after confirmation"
            self._telemetry[contract.contract_id] = tel.model_copy(update=updates)

        return contract, predicate_set, report

    def build_expected_outcome(
        self,
        predicate_set: PredicateSet,
        *,
        task_id: str,
        tenant_id: str,
        workspace_id: str,
        threshold: float = 1.0,
        frozen_at: datetime | None = None,
        observation_window_seconds: int | None = None,
    ) -> ExpectedOutcome:
        """Build an ExpectedOutcome record from a frozen, persisted PredicateSet."""
        frozen = frozen_at or _now()
        window = observation_window_seconds or self._observation_window
        return ExpectedOutcome(
            expected_outcome_id=f"expected:{uuid4()}",
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            evaluator_type=PREDICATE_CONJUNCTION_TYPE,
            evaluator_version=predicate_set.content_key(),
            evidence_requirements=PREDICATE_EVIDENCE_REQUIREMENTS,
            failure_semantics=tuple(PREDICATE_FAILURE_SEMANTICS),
            threshold=threshold,
            observation_window_seconds=window,
            frozen_at=frozen,
        )

    def close(self) -> None:
        self._store.close()
