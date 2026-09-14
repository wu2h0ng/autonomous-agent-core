"""Tests for automatic HCW telemetry recording."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone


from agent_os_contracts import (
    ClarificationAnswer,
    InferenceTelemetry,
    PredicateConfirmation,
    PredicateKind,
)

from agent_os_core.contract_inferencer_service import ContractInferencerService
from agent_os_core.provider import DeterministicProvider


EMAIL_SCHEMA = {
    "tool_name": "email_send",
    "parameters": {
        "type": "object",
        "properties": {"to": {"type": "string", "minLength": 1}},
        "required": ["to"],
    },
    "response": {
        "type": "object",
        "properties": {
            "status_code": {"type": "integer"},
            "body": {"type": "object", "properties": {"id": {"type": "string"}}},
        },
    },
}


def _high_conf_response() -> str:
    return json.dumps([{
        "predicate_id": "pred:sem:001",
        "kind": "SEMANTIC",
        "description": "API returns 200",
        "check_type": "TOOL_RESPONSE",
        "check_params": {"tool_name": "email_send", "condition": {"$.status_code": {"$gte": 200, "$lt": 300}}},
        "evidence_bindings": [{
            "binding_id": "b1", "source_type": "TOOL_RESPONSE",
            "source_selector": "email_send", "extract_path": "$.status_code",
            "relation": "success",
        }],
        "confidence": 0.95, "falsifiable": False, "blocking": False,
        "source": "llm:test", "meta_template": "evidence_anchor", "scope_tags": [],
    }])


def _low_conf_response() -> str:
    preds = json.loads(_high_conf_response())
    preds[0]["confidence"] = 0.4
    return json.dumps(preds)


class TestTelemetryType:
    def test_operator_wall_seconds_sums_both_rounds(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        tel = InferenceTelemetry(
            telemetry_id="t:1", contract_id="c:1", task_id="t:1", model_id="m",
            infer_started_at=now,
            clarification_presented_at=now,
            clarification_received_at=now.replace(minute=1),
            confirmation_presented_at=now.replace(minute=1),
            confirmation_received_at=now.replace(minute=2),
        )
        assert tel.clarification_wall_seconds == 60.0
        assert tel.confirmation_wall_seconds == 60.0
        assert tel.operator_wall_seconds == 120.0

    def test_intervention_count(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        tel = InferenceTelemetry(
            telemetry_id="t:1", contract_id="c:1", task_id="t:1", model_id="m",
            infer_started_at=now,
            questions_raised=2,
            predicates_presented=3,
        )
        assert tel.operator_intervention_count == 2

    def test_intervention_count_no_clarification(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        tel = InferenceTelemetry(
            telemetry_id="t:1", contract_id="c:1", task_id="t:1", model_id="m",
            infer_started_at=now,
            questions_raised=0,
            predicates_presented=3,
        )
        assert tel.operator_intervention_count == 1


class TestServiceTelemetry:
    def test_infer_records_timestamps_and_counts(self):
        provider = DeterministicProvider(text=_high_conf_response())
        svc = ContractInferencerService(provider, model_id="test")
        contract, report = svc.infer("send email", [EMAIL_SCHEMA], task_id="task:t1")
        assert contract is not None

        tel = svc.telemetry(contract.contract_id)
        assert tel is not None
        assert tel.infer_started_at is not None
        assert tel.infer_completed_at is not None
        assert tel.inference_latency_ms >= 0
        assert tel.pipeline_state == "CONFIRMATION_PENDING"
        assert tel.confirmation_presented_at is not None
        assert tel.predicates_presented > 0
        assert tel.questions_raised == 0

    def test_clarification_round_records_timing(self):
        provider = DeterministicProvider(text=_low_conf_response())
        svc = ContractInferencerService(provider, model_id="test")
        contract, report = svc.infer("send email", [EMAIL_SCHEMA], task_id="task:t2")
        assert contract is not None
        assert report.pipeline_state == "QUESTIONS_PENDING"

        tel = svc.telemetry(contract.contract_id)
        assert tel is not None
        assert tel.questions_raised == 1
        assert tel.clarification_presented_at is not None
        assert tel.clarification_received_at is None

        # Simulate operator delay
        time.sleep(0.05)
        q = contract.clarification_questions[0]
        answer = ClarificationAnswer(
            question_id=q.question_id, answer="yes",
            answered_by="operator:1",
            answered_at=datetime.now(timezone.utc),
        )
        contract, report = svc.apply_clarification(contract, [answer])

        tel = svc.telemetry(contract.contract_id)
        assert tel is not None
        assert tel.clarification_received_at is not None
        assert tel.clarification_wall_seconds >= 0.04
        assert tel.questions_answered_yes == 1
        assert tel.questions_answered_no == 0
        assert tel.pipeline_state == "CONFIRMATION_PENDING"

    def test_full_lifecycle_records_all_hcw(self):
        provider = DeterministicProvider(text=_high_conf_response())
        svc = ContractInferencerService(provider, model_id="test")
        contract, _ = svc.infer("send email", [EMAIL_SCHEMA], task_id="task:t3")
        assert contract is not None

        sem = [p for p in contract.success_predicates if p.kind is PredicateKind.SEMANTIC]
        confirmations = [
            PredicateConfirmation(
                predicate_id=p.predicate_id, decision="approve",
                confirmed_by="op:1", confirmed_at=datetime.now(timezone.utc),
            )
            for p in sem
        ]
        time.sleep(0.05)
        contract, ps, report = svc.apply_confirmation(contract, confirmations)

        tel = svc.telemetry(contract.contract_id)
        assert tel is not None
        assert tel.pipeline_state == "FROZEN"
        assert tel.completed_at is not None
        assert tel.confirmation_received_at is not None
        assert tel.predicates_approved == len(sem)
        assert tel.predicates_rejected == 0
        assert tel.predicates_adjusted == 0
        assert tel.blocking_count >= 1
        assert tel.operator_intervention_count == 1  # confirmation only, no clarification
        assert tel.operator_wall_seconds >= 0.04

    def test_rejection_records_reason(self):
        provider = DeterministicProvider(scripted=(("bad", ()), ("bad", ())))
        svc = ContractInferencerService(provider, model_id="test")
        contract, report = svc.infer("send email", [EMAIL_SCHEMA], task_id="task:t4")
        assert report.pipeline_state == "REJECTED"

        tel = svc.telemetry(report.contract_id)
        assert tel is not None
        assert tel.pipeline_state == "REJECTED"
        assert tel.rejection_reason is not None
        assert tel.completed_at is not None

    def test_no_answer_downgrade_counted(self):
        provider = DeterministicProvider(text=_low_conf_response())
        svc = ContractInferencerService(provider, model_id="test")
        contract, _ = svc.infer("send email", [EMAIL_SCHEMA], task_id="task:t5")
        assert contract is not None

        # No answers — all unanswered → downgrade
        contract, report = svc.apply_clarification(contract, [])
        tel = svc.telemetry(contract.contract_id)
        assert tel is not None
        assert tel.questions_unanswered_downgraded == 1
        assert tel.questions_answered_yes == 0

    def test_reject_decision_counted(self):
        provider = DeterministicProvider(text=_high_conf_response())
        svc = ContractInferencerService(provider, model_id="test")
        contract, _ = svc.infer("send email", [EMAIL_SCHEMA], task_id="task:t6")
        assert contract is not None
        sem = [p for p in contract.success_predicates if p.kind is PredicateKind.SEMANTIC]
        confirmations = [
            PredicateConfirmation(
                predicate_id=p.predicate_id, decision="reject",
                confirmed_by="op:1", confirmed_at=datetime.now(timezone.utc),
            )
            for p in sem
        ]
        contract, ps, report = svc.apply_confirmation(contract, confirmations)
        tel = svc.telemetry(contract.contract_id)
        assert tel is not None
        assert tel.predicates_rejected == len(sem)
        assert tel.predicates_approved == 0
