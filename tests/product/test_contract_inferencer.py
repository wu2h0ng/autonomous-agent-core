"""Tests for QualityGate (Stage 3) and ContractInferencer (Stages 0-4.5)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from agent_os_contracts import (
    CheckType,
    ClarificationAnswer,
    EvidenceBinding,
    EvidenceSourceType,
    PredicateConfirmation,
    PredicateKind,
    SuccessPredicate,
)

from agent_os_core.contract_inferencer import ContractInferencer
from agent_os_core.provider import DeterministicProvider
from agent_os_core.quality_gate import run_quality_gate
from agent_os_core.semantic_proposer import SemanticProposer


def _binding(
    source_type: EvidenceSourceType,
    selector: str,
    path: str | None = None,
    bid: str = "bind:1",
) -> EvidenceBinding:
    return EvidenceBinding(
        binding_id=bid,
        source_type=source_type,
        source_selector=selector,
        extract_path=path,
        relation="test",
    )


def _semantic_predicate(
    pid: str = "pred:sem:001",
    check_type: CheckType = CheckType.REGEX,
    params: dict | None = None,
    *,
    confidence: float = 0.9,
    blocking: bool = False,
    source_type: EvidenceSourceType = EvidenceSourceType.ARTIFACT,
    selector: str = "output.json",
    path: str = "$.field",
    description: str = "field matches pattern",
    source: str = "llm:test-model",
) -> SuccessPredicate:
    return SuccessPredicate(
        predicate_id=pid,
        kind=PredicateKind.SEMANTIC,
        description=description,
        check_type=check_type,
        check_params=params or {"pattern": r"^ORD-\d+$"},
        evidence_bindings=(_binding(source_type, selector, path),),
        confidence=confidence,
        falsifiable=False,
        blocking=blocking,
        source=source,
    )


# ---------------------------------------------------------------------------
# Quality Gate tests
# ---------------------------------------------------------------------------


class TestQualityGate:
    def test_q1_accepts_known_tool(self):
        p = _semantic_predicate(
            source_type=EvidenceSourceType.TOOL_RESPONSE,
            selector="known_tool",
            params={"tool_name": "known_tool", "condition": {"$.status": 200}},
            check_type=CheckType.TOOL_RESPONSE,
        )
        gate = run_quality_gate([p], [], {"known_tool"})
        assert len(gate.accepted) == 1
        assert len(gate.rejected) == 0

    def test_q1_rejects_unknown_tool(self):
        p = _semantic_predicate(
            source_type=EvidenceSourceType.TOOL_RESPONSE,
            selector="unknown_tool",
            params={"tool_name": "unknown_tool", "condition": {"$.status": 200}},
            check_type=CheckType.TOOL_RESPONSE,
        )
        gate = run_quality_gate([p], [], {"known_tool"})
        assert len(gate.rejected) == 1

    def test_q2_rejects_missing_params(self):
        p = _semantic_predicate(check_type=CheckType.RANGE, params={})
        gate = run_quality_gate([p], [], set())
        assert len(gate.rejected) == 1
        assert "Q2" in gate.rejected[0][1]

    def test_q3_rejects_blocking_llm_judge(self):
        p = _semantic_predicate(
            check_type=CheckType.LLM_JUDGE,
            params={"rubric": "is good"},
            blocking=True,
        )
        gate = run_quality_gate([p], [], set())
        assert len(gate.rejected) == 1
        assert "Q3" in gate.rejected[0][1]

    def test_q6_low_confidence_to_clarification(self):
        p = _semantic_predicate(confidence=0.5)
        gate = run_quality_gate([p], [], set())
        assert len(gate.clarification_needed) == 1
        assert len(gate.confirmation_needed) == 0

    def test_q6_high_confidence_to_confirmation(self):
        p = _semantic_predicate(confidence=0.9)
        gate = run_quality_gate([p], [], set())
        assert len(gate.confirmation_needed) == 1
        assert len(gate.clarification_needed) == 0

    def test_accepted_predicates_marked_falsifiable(self):
        p = _semantic_predicate()
        gate = run_quality_gate([p], [], set())
        assert all(p.falsifiable for p in gate.accepted)

    def test_contradiction_drops_lower_confidence(self):
        p1 = _semantic_predicate(
            pid="pred:a", check_type=CheckType.RANGE,
            params={"min": 0, "max": 100}, confidence=0.9,
            path="$.score",
        )
        p2 = _semantic_predicate(
            pid="pred:b", check_type=CheckType.RANGE,
            params={"min": 200, "max": 300}, confidence=0.6,
            path="$.score",
        )
        gate = run_quality_gate([p1, p2], [], set())
        assert len(gate.accepted) == 1
        assert gate.accepted[0].predicate_id == "pred:a"
        assert any("Q4" in w for w in gate.warnings)


# ---------------------------------------------------------------------------
# ContractInferencer tests
# ---------------------------------------------------------------------------


def _make_inferencer(response_text: str) -> ContractInferencer:
    provider = DeterministicProvider(text=response_text)
    proposer = SemanticProposer(provider, model_id="test-model")
    return ContractInferencer(proposer, model_id="test-model")


def _good_predicate_json() -> str:
    return json.dumps([{
        "predicate_id": "pred:sem:001",
        "kind": "SEMANTIC",
        "description": "The output contains a valid order ID",
        "check_type": "REGEX",
        "check_params": {"pattern": r"^ORD-\d+$"},
        "evidence_bindings": [{
            "binding_id": "bind:1",
            "source_type": "ARTIFACT",
            "source_selector": "output.json",
            "extract_path": "$.order_id",
            "relation": "proves order ID",
        }],
        "confidence": 0.9,
        "falsifiable": False,
        "blocking": False,
        "source": "llm:test-model",
        "meta_template": "schema",
        "scope_tags": [],
    }])


class TestContractInferencerInfer:
    def test_infer_produces_confirmation_pending(self):
        inf = _make_inferencer(_good_predicate_json())
        contract, report = inf.infer(
            mandate_text="Create an order with ID matching ORD-\\d+",
            tool_schemas=[{"tool_name": "create_order"}],
        )
        assert report.pipeline_state == "CONFIRMATION_PENDING"
        assert len(contract.success_predicates) >= 1
        assert report.mechanical_count >= 0

    def test_infer_low_confidence_produces_questions(self):
        pred = json.loads(_good_predicate_json())
        pred[0]["confidence"] = 0.5
        inf = _make_inferencer(json.dumps(pred))
        contract, report = inf.infer(
            mandate_text="Do something",
            tool_schemas=[{"tool_name": "create_order"}],
        )
        assert report.pipeline_state == "QUESTIONS_PENDING"
        assert len(contract.clarification_questions) == 1

    def test_infer_rejected_on_llm_failure(self):
        inf = _make_inferencer("not json at all")
        # Two failures (initial + retry) → REJECTED
        provider = DeterministicProvider(scripted=(("bad", ()), ("bad", ())))
        from agent_os_core.semantic_proposer import SemanticProposer
        inf = ContractInferencer(
            SemanticProposer(provider, model_id="test-model"),
            model_id="test-model",
        )
        contract, report = inf.infer(
            mandate_text="test",
            tool_schemas=[],
        )
        assert report.pipeline_state == "REJECTED"


class TestApplyClarification:
    def test_yes_keeps_predicate(self):
        inf = _make_inferencer(_good_predicate_json())
        # Make it low-confidence to trigger clarification
        pred = json.loads(_good_predicate_json())
        pred[0]["confidence"] = 0.5
        inf = _make_inferencer(json.dumps(pred))
        contract, report = inf.infer("test", [{"tool_name": "create_order"}])
        assert report.pipeline_state == "QUESTIONS_PENDING"

        q = contract.clarification_questions[0]
        answer = ClarificationAnswer(
            question_id=q.question_id,
            answer="yes",
            answered_at=datetime.now(timezone.utc),
        )
        contract2, report2 = inf.apply_clarification(contract, [answer])
        assert report2.pipeline_state == "CONFIRMATION_PENDING"
        assert len(contract2.success_predicates) == len(contract.success_predicates)

    def test_no_removes_predicate(self):
        pred = json.loads(_good_predicate_json())
        pred[0]["confidence"] = 0.5
        inf = _make_inferencer(json.dumps(pred))
        contract, _ = inf.infer("test", [{"tool_name": "create_order"}])
        q = contract.clarification_questions[0]
        answer = ClarificationAnswer(
            question_id=q.question_id,
            answer="no",
            answered_at=datetime.now(timezone.utc),
        )
        contract2, report2 = inf.apply_clarification(contract, [answer])
        assert len(contract2.success_predicates) < len(contract.success_predicates)


class TestApplyConfirmation:
    def test_approve_freezes_contract(self):
        inf = _make_inferencer(_good_predicate_json())
        contract, report = inf.infer("test", [{"tool_name": "create_order"}])
        sem_preds = [p for p in contract.success_predicates if p.kind is PredicateKind.SEMANTIC]
        confirmations = [
            PredicateConfirmation(
                predicate_id=p.predicate_id,
                decision="approve",
                confirmed_by="operator:1",
                confirmed_at=datetime.now(timezone.utc),
            )
            for p in sem_preds
        ]
        contract2, pred_set, report2 = inf.apply_confirmation(contract, confirmations)
        assert report2.pipeline_state == "FROZEN"
        assert pred_set is not None
        assert report2.blocking_count >= 1
        assert all(p.blocking for p in pred_set.predicates if p.kind is PredicateKind.CONFIRMED)

    def test_reject_removes_predicate(self):
        inf = _make_inferencer(_good_predicate_json())
        contract, _ = inf.infer("test", [{"tool_name": "create_order"}])
        sem_preds = [p for p in contract.success_predicates if p.kind is PredicateKind.SEMANTIC]
        confirmations = [
            PredicateConfirmation(
                predicate_id=p.predicate_id,
                decision="reject",
                confirmed_by="operator:1",
                confirmed_at=datetime.now(timezone.utc),
            )
            for p in sem_preds
        ]
        contract2, pred_set, report2 = inf.apply_confirmation(contract, confirmations)
        # If structural predicates exist, contract still freezes
        if pred_set is not None:
            assert report2.pipeline_state == "FROZEN"
        else:
            assert report2.pipeline_state == "REJECTED"

    def test_no_blocking_predicates_rejected(self):
        # All semantic, all rejected, no structural → REJECTED
        pred = json.loads(_good_predicate_json())
        # Make it a tool that doesn't exist so mechanical extraction produces nothing
        inf = _make_inferencer(json.dumps(pred))
        contract, _ = inf.infer("test", [])
        sem_preds = [p for p in contract.success_predicates if p.kind is PredicateKind.SEMANTIC]
        confirmations = [
            PredicateConfirmation(
                predicate_id=p.predicate_id,
                decision="reject",
                confirmed_by="operator:1",
                confirmed_at=datetime.now(timezone.utc),
            )
            for p in sem_preds
        ]
        _, pred_set, report2 = inf.apply_confirmation(contract, confirmations)
        assert report2.pipeline_state == "REJECTED"
        assert pred_set is None
