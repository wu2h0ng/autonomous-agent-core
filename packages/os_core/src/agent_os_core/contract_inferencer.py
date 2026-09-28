"""ContractInferencer: five-stage pipeline with three-call API.

Stage 0: Input normalization
Stage 1: Mechanical extraction (deterministic)
Stage 2: Semantic proposal (one LLM call)
Stage 3: Quality gate (deterministic)
Stage 4: Clarification (apply_clarification — pure transformation)
Stage 4.5: Confirmation + freeze (apply_confirmation — pure transformation)

Three-call API:
  infer() → InferenceReport (QUESTIONS_PENDING or CONFIRMATION_PENDING)
  apply_clarification(report, answers) → InferenceReport
  apply_confirmation(report, confirmations) → InferenceReport (FROZEN or REJECTED)
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_os_contracts import (
    CheckType,
    ClarificationAnswer,
    ClarificationQuestion,
    InferenceReport,
    InferredTaskContract,
    PredicateConfirmation,
    PredicateKind,
    PredicateSet,
    SuccessPredicate,
)

from .mechanical_extractor import extract_structural_predicates
from .quality_gate import run_quality_gate
from .semantic_proposer import (
    SemanticProposalError,
    SemanticProposer,
)

INFERRER_VERSION = "0.3.0"
MAX_CLARIFICATION_QUESTIONS = 7


def _mandate_digest(mandate_text: str) -> str:
    return hashlib.sha256(mandate_text.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ContractInferencer:
    """Orchestrates Stages 0-4.5. Three-call API, no hidden state."""

    def __init__(
        self,
        semantic_proposer: SemanticProposer,
        *,
        model_id: str = "unknown",
    ) -> None:
        self._proposer = semantic_proposer
        self._model_id = model_id

    def infer(
        self,
        mandate_text: str,
        tool_schemas: list[dict[str, Any]],
        *,
        mandate_id: str | None = None,
        deliverable_schema: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> tuple[InferredTaskContract | None, InferenceReport]:
        """Stage 0-3: normalize, extract, propose, quality-gate.

        Returns (contract, report). contract is None when pipeline is REJECTED.
        """
        start = time.monotonic()
        mandate_id = mandate_id or f"mandate:{uuid4()}"
        task_id = task_id or f"task:{uuid4()}"
        contract_id = f"contract:{uuid4()}"
        now = _now()

        # Stage 0: normalize — collect available tool names
        available_tool_names: set[str] = set()
        for schema in tool_schemas:
            name = schema.get("tool_name") or schema.get("name")
            if isinstance(name, str):
                available_tool_names.add(name)
                # Also add short name (after last dot)
                available_tool_names.add(name.split(".")[-1])

        # Stage 1: mechanical extraction
        structural_preds, failure_paths = extract_structural_predicates(tool_schemas)

        # Stage 2: semantic proposal
        try:
            semantic_preds = self._proposer.propose(
                mandate_text=mandate_text,
                tool_schemas=tool_schemas,
                structural_predicates=structural_preds,
                deliverable_schema=deliverable_schema,
            )
        except SemanticProposalError:
            report = InferenceReport(
                report_id=f"report:{uuid4()}",
                contract_id=contract_id,
                mandate_id=mandate_id,
                pipeline_state="REJECTED",
                mechanical_count=len(structural_preds),
                semantic_proposed_count=0,
                semantic_rejected_count=0,
                confirmed_count=0,
                blocking_count=0,
                advisory_count=0,
                clarification_raised=0,
                clarification_answered=0,
                coverage_gaps=(),
                inference_latency_ms=int((time.monotonic() - start) * 1000),
                model_id=self._model_id,
                created_at=now,
            )
            return None, report

        # Stage 3: quality gate
        gate = run_quality_gate(
            semantic_preds,
            structural_preds,
            available_tool_names,
            deliverable_schema,
        )

        # Zero predicates survive Q1-Q3 → fatal REJECTED
        if not gate.accepted and not structural_preds:
            report = InferenceReport(
                report_id=f"report:{uuid4()}",
                contract_id=contract_id,
                mandate_id=mandate_id,
                pipeline_state="REJECTED",
                mechanical_count=len(structural_preds),
                semantic_proposed_count=len(semantic_preds),
                semantic_rejected_count=len(gate.rejected),
                confirmed_count=0,
                blocking_count=0,
                advisory_count=0,
                clarification_raised=0,
                clarification_answered=0,
                coverage_gaps=gate.coverage_gaps,
                inference_latency_ms=int((time.monotonic() - start) * 1000),
                model_id=self._model_id,
                created_at=now,
            )
            return None, report

        # Generate clarification questions (Stage 4)
        questions: list[ClarificationQuestion] = []
        clarification_pred_ids: set[str] = set()
        for i, pred in enumerate(gate.clarification_needed[:MAX_CLARIFICATION_QUESTIONS]):
            questions.append(
                ClarificationQuestion(
                    question_id=f"q:{i+1:03d}",
                    predicate_id=pred.predicate_id,
                    question=f"Should {pred.description}?",
                    question_type="yes_no",
                    on_unanswered="downgrade",
                )
            )
            clarification_pred_ids.add(pred.predicate_id)

        # Combine all predicates: structural + accepted semantic
        all_predicates = list(structural_preds)
        all_predicates.extend(gate.accepted)

        # Determine pipeline state
        if questions:
            pipeline_state = "QUESTIONS_PENDING"
        else:
            pipeline_state = "CONFIRMATION_PENDING"

        # Count advisory (LLM_JUDGE, non-blocking)
        advisory_count = sum(
            1 for p in gate.accepted
            if p.check_type is CheckType.LLM_JUDGE or not p.blocking
        )

        report = InferenceReport(
            report_id=f"report:{uuid4()}",
            contract_id=contract_id,
            mandate_id=mandate_id,
            pipeline_state=pipeline_state,
            mechanical_count=len(structural_preds),
            semantic_proposed_count=len(semantic_preds),
            semantic_rejected_count=len(gate.rejected),
            confirmed_count=0,
            blocking_count=len(structural_preds),  # structural are blocking
            advisory_count=advisory_count,
            clarification_raised=len(questions),
            clarification_answered=0,
            coverage_gaps=gate.coverage_gaps,
            inference_latency_ms=int((time.monotonic() - start) * 1000),
            model_id=self._model_id,
            created_at=now,
        )

        contract = InferredTaskContract(
            contract_id=contract_id,
            mandate_id=mandate_id,
            mandate_digest=_mandate_digest(mandate_text),
            task_id=task_id,
            inferred_at=now,
            inferrer_version=INFERRER_VERSION,
            model_id=self._model_id,
            deliverable_schema=deliverable_schema or {},
            success_predicates=tuple(all_predicates),
            failure_paths=tuple(failure_paths),
            clarification_questions=tuple(questions),
            warnings=tuple(gate.warnings),
            meta_templates_instantiated=tuple(
                sorted({p.meta_template for p in gate.accepted if p.meta_template})
            ),
        )

        # Stash gate results on the contract for the apply calls
        # (using a private attribute pattern — the contract is frozen, so we
        # carry the routing info in the report's unresolved_items)
        self._pending_confirmation = {
            p.predicate_id for p in gate.confirmation_needed
        }
        self._pending_clarification = clarification_pred_ids
        self._last_contract_id = contract_id

        return contract, report

    def apply_clarification(
        self,
        contract: InferredTaskContract,
        answers: list[ClarificationAnswer],
    ) -> tuple[InferredTaskContract, InferenceReport]:
        """Stage 4: apply clarification answers. Pure transformation.

        "yes" → pre_endorsed, confidence=1.0, enters confirmation batch
        "no" → predicate removed
        choice value → update check_params, pre_endorsed
        unanswered → downgrade (blocking=False) or drop
        """
        now = _now()
        answer_map = {a.question_id: a for a in answers}

        kept_predicates: list[SuccessPredicate] = []
        answered_count = 0
        new_questions = list(contract.clarification_questions)
        new_answers = list(contract.clarification_answers)

        for pred in contract.success_predicates:
            # Find the question for this predicate, if any
            matching_q = next(
                (q for q in contract.clarification_questions if q.predicate_id == pred.predicate_id),
                None,
            )
            if matching_q is None:
                kept_predicates.append(pred)
                continue

            answer = answer_map.get(matching_q.question_id)
            if answer is None:
                # Unanswered → apply on_unanswered policy
                if matching_q.on_unanswered == "drop":
                    continue  # remove
                else:
                    # downgrade: keep as non-blocking
                    kept_predicates.append(
                        pred.model_copy(update={"blocking": False})
                    )
                continue

            answered_count += 1
            new_answers.append(answer)
            ans = answer.answer.strip().lower()

            if ans == "no":
                continue  # remove predicate
            elif ans == "yes":
                kept_predicates.append(
                    pred.model_copy(update={
                        "confidence": 1.0,
                        "kind": PredicateKind.SEMANTIC,
                    })
                )
            else:
                # Choice value — update check_params with the chosen value
                new_params = dict(pred.check_params)
                if matching_q.options:
                    # Find matching option and apply
                    new_params["chosen_value"] = ans
                kept_predicates.append(
                    pred.model_copy(update={
                        "confidence": 1.0,
                        "check_params": new_params,
                        "kind": PredicateKind.SEMANTIC,
                    })
                )

        # Remove answered questions
        unanswered_questions = [
            q for q in new_questions
            if q.question_id not in answer_map
        ]

        pipeline_state = "CONFIRMATION_PENDING" if not unanswered_questions else "QUESTIONS_PENDING"

        new_contract = contract.model_copy(update={
            "success_predicates": tuple(kept_predicates),
            "clarification_answers": tuple(new_answers),
            "clarification_questions": tuple(unanswered_questions),
        })

        blocking_count = sum(1 for p in kept_predicates if p.blocking)
        report = InferenceReport(
            report_id=f"report:{uuid4()}",
            contract_id=contract.contract_id,
            mandate_id=contract.mandate_id,
            pipeline_state=pipeline_state,
            mechanical_count=sum(1 for p in kept_predicates if p.kind is PredicateKind.STRUCTURAL),
            semantic_proposed_count=sum(1 for p in kept_predicates if p.kind is PredicateKind.SEMANTIC),
            semantic_rejected_count=len(contract.success_predicates) - len(kept_predicates),
            confirmed_count=0,
            blocking_count=blocking_count,
            advisory_count=sum(1 for p in kept_predicates if not p.blocking),
            clarification_raised=len(unanswered_questions),
            clarification_answered=answered_count,
            coverage_gaps=(),
            inference_latency_ms=0,
            model_id=self._model_id,
            created_at=now,
        )

        return new_contract, report

    def apply_confirmation(
        self,
        contract: InferredTaskContract,
        confirmations: list[PredicateConfirmation],
    ) -> tuple[InferredTaskContract, PredicateSet | None, InferenceReport]:
        """Stage 4.5: apply confirmations and freeze. Pure transformation.

        - approve → predicate becomes CONFIRMED, blocking=True
        - reject → predicate removed
        - adjust → replaced by adjusted_predicate (new content-derived id)
        - Freeze gates: confirmation_status ∈ {CONFIRMED, NOT_REQUIRED}
          AND blocking_count ≥ 1
        - E-7 bypass check: llm:/operator: sourced blocking predicates must
          have matching confirmation
        """
        now = _now()
        conf_by_pred_id = {c.predicate_id: c for c in confirmations}

        final_predicates: list[SuccessPredicate] = []
        confirmed_count = 0

        for pred in contract.success_predicates:
            # Structural predicates are already blocking and don't need confirmation
            if pred.kind is PredicateKind.STRUCTURAL:
                final_predicates.append(pred)
                continue

            conf = conf_by_pred_id.get(pred.predicate_id)

            # Pre-endorsed predicates (from clarification "yes"/choice) default approve
            if conf is None:
                # Check if this was pre-endorsed — if so, default approve
                # Pre-endorsed predicates have confidence=1.0 from clarification
                if pred.confidence >= 1.0 and pred.kind is PredicateKind.SEMANTIC:
                    final_predicates.append(
                        pred.model_copy(update={
                            "kind": PredicateKind.CONFIRMED,
                            "blocking": True,
                        })
                    )
                    confirmed_count += 1
                else:
                    # Unconfirmed semantic predicate → keep as non-blocking advisory
                    final_predicates.append(
                        pred.model_copy(update={"blocking": False})
                    )
                continue

            if conf.decision == "reject":
                continue  # remove
            elif conf.decision == "adjust" and conf.adjusted_predicate is not None:
                adjusted = conf.adjusted_predicate.model_copy(update={
                    "kind": PredicateKind.CONFIRMED,
                    "blocking": True,
                    "source": f"operator:{conf.confirmed_by}",
                })
                final_predicates.append(adjusted)
                confirmed_count += 1
            else:  # approve
                final_predicates.append(
                    pred.model_copy(update={
                        "kind": PredicateKind.CONFIRMED,
                        "blocking": True,
                    })
                )
                confirmed_count += 1

        # E-7 bypass detection: blocking predicates with llm:/operator: source
        # must have a matching confirmation record
        blocking_with_confirmation = {c.predicate_id for c in confirmations}
        for pred in final_predicates:
            if pred.blocking and pred.source.startswith(("llm:", "operator:")):
                if pred.predicate_id not in blocking_with_confirmation:
                    # This is a bypass attempt — but pre-endorsed are auto-confirmed
                    # (they went through clarification). Structural have mechanical: source.
                    if pred.source.startswith("llm:") and pred.confidence < 1.0:
                        # Force non-blocking — unconfirmed LLM predicate cannot block
                        idx = final_predicates.index(pred)
                        final_predicates[idx] = pred.model_copy(update={"blocking": False})

        blocking_count = sum(1 for p in final_predicates if p.blocking)
        advisory_count = sum(1 for p in final_predicates if not p.blocking)

        # Freeze gates
        confirmation_status = "CONFIRMED" if confirmed_count > 0 else "NOT_REQUIRED"
        if blocking_count < 1:
            pipeline_state = "REJECTED"
            predicate_set = None
        else:
            pipeline_state = "FROZEN"
            predicate_set = PredicateSet(
                set_id=f"set:{uuid4()}",
                contract_id=contract.contract_id,
                task_id=contract.task_id,
                tenant_id="tenant:1",
                workspace_id="ws:1",
                predicates=tuple(final_predicates),
                confirmation_records=tuple(confirmations),
                frozen_at=now,
            )

        new_contract = contract.model_copy(update={
            "success_predicates": tuple(final_predicates),
            "confirmation_records": tuple(confirmations),
            "confirmation_status": confirmation_status,
        })

        report = InferenceReport(
            report_id=f"report:{uuid4()}",
            contract_id=contract.contract_id,
            mandate_id=contract.mandate_id,
            pipeline_state=pipeline_state,
            mechanical_count=sum(1 for p in final_predicates if p.kind is PredicateKind.STRUCTURAL),
            semantic_proposed_count=sum(1 for p in final_predicates if p.kind in (PredicateKind.SEMANTIC, PredicateKind.CONFIRMED)),
            semantic_rejected_count=len(contract.success_predicates) - len(final_predicates),
            confirmed_count=confirmed_count,
            blocking_count=blocking_count,
            advisory_count=advisory_count,
            clarification_raised=0,
            clarification_answered=contract.clarification_answers.__len__(),
            coverage_gaps=(),
            inference_latency_ms=0,
            model_id=self._model_id,
            created_at=now,
        )

        return new_contract, predicate_set, report
