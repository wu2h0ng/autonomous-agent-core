"""End-to-end smoke test: mandate → infer → confirm → freeze → evaluate → verdict.

Tests the complete contract inferencer pipeline with a realistic email-sending
mandate, including:
- Mechanical extraction from tool JSON Schema
- LLM semantic proposal (hermetic DeterministicProvider)
- Quality gate routing
- Operator confirmation (C7 gate)
- PredicateSet freeze
- Conjunctive evaluation against evidence
- Negative control: bad evidence → NOT_MET
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone


from agent_os_contracts import (
    ExpectedOutcome,
    OutcomeStatus,
    PredicateConfirmation,
    PredicateKind,
)

from agent_os_core.contract_inferencer import ContractInferencer
from agent_os_core.predicate_evaluator import (
    InMemoryPredicateSetStore,
    PredicateConjunctionEvaluator,
    PREDICATE_CONJUNCTION_TYPE,
)
from agent_os_core.provider import DeterministicProvider
from agent_os_core.semantic_proposer import SemanticProposer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

EMAIL_TOOL_SCHEMA = {
    "tool_name": "email_send",
    "description": "Send an email to a recipient",
    "parameters": {
        "type": "object",
        "properties": {
            "to": {"type": "string", "minLength": 1},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["to", "subject"],
    },
    "response": {
        "type": "object",
        "properties": {
            "status_code": {"type": "integer"},
            "body": {
                "type": "object",
                "properties": {
                    "message_id": {"type": "string"},
                },
            },
        },
    },
    "errors": [
        {"status": 400, "action": "abort"},
        {"status": 500, "action": "retry", "max_retries": 2},
    ],
}

MANDATE_TEXT = """Send a welcome email to new-user@example.com with subject "Welcome".
The email must contain a valid message ID in the response confirming delivery."""


def _semantic_predicates_response() -> str:
    """Hermetic LLM response: two semantic predicates."""
    return json.dumps([
        {
            "predicate_id": "pred:sem:001",
            "kind": "SEMANTIC",
            "description": "The email was sent to new-user@example.com",
            "check_type": "TOOL_RESPONSE",
            "check_params": {
                "tool_name": "email_send",
                "condition": {"$.status_code": 200},
            },
            "evidence_bindings": [{
                "binding_id": "bind:sem1",
                "source_type": "TOOL_RESPONSE",
                "source_selector": "email_send",
                "extract_path": "$.status_code",
                "relation": "confirms the email API returned success",
            }],
            "confidence": 0.95,
            "falsifiable": False,
            "blocking": False,
            "source": "llm:test-model",
            "meta_template": "evidence_anchor",
            "scope_tags": [],
        },
        {
            "predicate_id": "pred:sem:002",
            "kind": "SEMANTIC",
            "description": "The response contains a non-empty message_id",
            "check_type": "FIELD_PRESENCE",
            "check_params": {},
            "evidence_bindings": [{
                "binding_id": "bind:sem2",
                "source_type": "TOOL_RESPONSE",
                "source_selector": "email_send",
                "extract_path": "$.body.message_id",
                "relation": "confirms a message was created",
            }],
            "confidence": 0.9,
            "falsifiable": False,
            "blocking": False,
            "source": "llm:test-model",
            "meta_template": "evidence_anchor",
            "scope_tags": [],
        },
    ])


class FakeEvidenceAccessor:
    """Minimal evidence accessor for smoke test."""

    def __init__(self, tool_results: dict | None = None, artifacts: dict | None = None):
        self._tool_results = tool_results or {}
        self._artifacts = artifacts or {}

    def artifact_content(self, artifact_id: str) -> bytes | None:
        return self._artifacts.get(artifact_id)

    def artifact_json(self, artifact_id: str):
        raw = self._artifacts.get(artifact_id)
        if raw is None:
            return None
        return json.loads(raw)

    def tool_result(self, tool_name: str, *, latest: bool = True):
        return self._tool_results.get(tool_name)

    def state_snapshot(self, label: str):
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEndToEndSmoke:
    def test_full_pipeline_success(self):
        """Stage 0 → freeze → evaluate → VERIFIED."""
        # Stage 0-3: infer
        provider = DeterministicProvider(text=_semantic_predicates_response())
        proposer = SemanticProposer(provider, model_id="test-model")
        inferencer = ContractInferencer(proposer, model_id="test-model")

        contract, report = inferencer.infer(
            mandate_text=MANDATE_TEXT,
            tool_schemas=[EMAIL_TOOL_SCHEMA],
            task_id="task:e2e:1",
        )

        assert contract is not None
        assert report.pipeline_state == "CONFIRMATION_PENDING"
        # Should have structural predicates (from schema) + semantic
        assert len(contract.success_predicates) >= 3  # 2+ structural
        assert report.mechanical_count >= 1
        assert report.semantic_proposed_count == 2

        # Stage 4.5: confirm all semantic predicates
        sem_preds = [
            p for p in contract.success_predicates
            if p.kind is PredicateKind.SEMANTIC
        ]
        confirmations = [
            PredicateConfirmation(
                predicate_id=p.predicate_id,
                decision="approve",
                confirmed_by="operator:e2e-test",
                confirmed_at=datetime.now(timezone.utc),
            )
            for p in sem_preds
        ]
        contract, predicate_set, report = inferencer.apply_confirmation(
            contract, confirmations
        )

        assert report.pipeline_state == "FROZEN"
        assert predicate_set is not None
        assert report.blocking_count >= 1
        assert contract.confirmation_status == "CONFIRMED"

        # All predicates in frozen set should be blocking
        blocking_preds = [p for p in predicate_set.predicates if p.blocking]
        assert len(blocking_preds) >= 3

        # Freeze → ExpectedOutcome
        store = InMemoryPredicateSetStore()
        store.save(predicate_set)

        frozen_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        expected = ExpectedOutcome(
            expected_outcome_id="expected:e2e:1",
            task_id="task:e2e:1",
            tenant_id="tenant:1",
            workspace_id="ws:1",
            evaluator_type=PREDICATE_CONJUNCTION_TYPE,
            evaluator_version=predicate_set.content_key(),
            evidence_requirements=("predicate-set",),
            failure_semantics=("blocking predicate failed",),
            threshold=1.0,
            observation_window_seconds=3600,
            frozen_at=frozen_at,
        )

        # Contract error check
        accessor = FakeEvidenceAccessor(tool_results={
            "email_send": {
                "to": "new-user@example.com",
                "subject": "Welcome",
                "body_params": "Welcome aboard!",
                "status_code": 200,
                "body": {"message_id": "msg-abc-123"},
            },
        })

        def factory(*args):
            return accessor

        evaluator = PredicateConjunctionEvaluator(store, accessor_factory=factory)
        assert evaluator.contract_error(expected) is None

        # Evaluate: all predicates should pass
        result = evaluator.evaluate(
            expected,
            task_id="task:e2e:1",
            run_id="run:e2e:1",
            tenant_id="tenant:1",
            workspace_id="ws:1",
            evidence_refs=("tool:email_send",),
            test_exit_code=None,
            now=frozen_at + timedelta(seconds=10),
        )

        assert result.status is OutcomeStatus.VERIFIED
        assert result.score == 1.0
        assert result.unresolved_gaps == ()

    def test_negative_control_bad_evidence_not_met(self):
        """Same frozen contract, but evidence shows failure → NOT_MET."""
        provider = DeterministicProvider(text=_semantic_predicates_response())
        proposer = SemanticProposer(provider, model_id="test-model")
        inferencer = ContractInferencer(proposer, model_id="test-model")

        contract, report = inferencer.infer(
            mandate_text=MANDATE_TEXT,
            tool_schemas=[EMAIL_TOOL_SCHEMA],
            task_id="task:e2e:2",
        )
        assert contract is not None
        sem_preds = [
            p for p in contract.success_predicates
            if p.kind is PredicateKind.SEMANTIC
        ]
        confirmations = [
            PredicateConfirmation(
                predicate_id=p.predicate_id,
                decision="approve",
                confirmed_by="operator:e2e-test",
                confirmed_at=datetime.now(timezone.utc),
            )
            for p in sem_preds
        ]
        _, predicate_set, _ = inferencer.apply_confirmation(contract, confirmations)
        assert predicate_set is not None

        store = InMemoryPredicateSetStore()
        store.save(predicate_set)

        frozen_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        expected = ExpectedOutcome(
            expected_outcome_id="expected:e2e:2",
            task_id="task:e2e:2",
            tenant_id="tenant:1",
            workspace_id="ws:1",
            evaluator_type=PREDICATE_CONJUNCTION_TYPE,
            evaluator_version=predicate_set.content_key(),
            evidence_requirements=("predicate-set",),
            failure_semantics=("blocking predicate failed",),
            threshold=1.0,
            observation_window_seconds=3600,
            frozen_at=frozen_at,
        )

        # Bad evidence: 500 error, no message_id
        accessor = FakeEvidenceAccessor(tool_results={
            "email_send": {
                "to": "new-user@example.com",
                "subject": "Welcome",
                "status_code": 500,
                "body": {},
            },
        })

        evaluator = PredicateConjunctionEvaluator(
            store, accessor_factory=lambda *a: accessor
        )
        result = evaluator.evaluate(
            expected,
            task_id="task:e2e:2",
            run_id="run:e2e:2",
            tenant_id="tenant:1",
            workspace_id="ws:1",
            evidence_refs=("tool:email_send",),
            test_exit_code=None,
            now=frozen_at + timedelta(seconds=10),
        )

        assert result.status is OutcomeStatus.NOT_MET
        assert result.score is not None
        assert result.score < 1.0
        assert len(result.unresolved_gaps) > 0

    def test_missing_evidence_unresolved(self):
        """No tool result at all → UNRESOLVED (not NOT_MET)."""
        provider = DeterministicProvider(text=_semantic_predicates_response())
        proposer = SemanticProposer(provider, model_id="test-model")
        inferencer = ContractInferencer(proposer, model_id="test-model")

        contract, _ = inferencer.infer(
            mandate_text=MANDATE_TEXT,
            tool_schemas=[EMAIL_TOOL_SCHEMA],
            task_id="task:e2e:3",
        )
        assert contract is not None
        sem_preds = [
            p for p in contract.success_predicates
            if p.kind is PredicateKind.SEMANTIC
        ]
        confirmations = [
            PredicateConfirmation(
                predicate_id=p.predicate_id,
                decision="approve",
                confirmed_by="operator:e2e-test",
                confirmed_at=datetime.now(timezone.utc),
            )
            for p in sem_preds
        ]
        _, predicate_set, _ = inferencer.apply_confirmation(contract, confirmations)
        assert predicate_set is not None

        store = InMemoryPredicateSetStore()
        store.save(predicate_set)

        frozen_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        expected = ExpectedOutcome(
            expected_outcome_id="expected:e2e:3",
            task_id="task:e2e:3",
            tenant_id="tenant:1",
            workspace_id="ws:1",
            evaluator_type=PREDICATE_CONJUNCTION_TYPE,
            evaluator_version=predicate_set.content_key(),
            evidence_requirements=("predicate-set",),
            failure_semantics=("blocking predicate failed",),
            threshold=1.0,
            observation_window_seconds=3600,
            frozen_at=frozen_at,
        )

        # No evidence at all
        accessor = FakeEvidenceAccessor()
        evaluator = PredicateConjunctionEvaluator(
            store, accessor_factory=lambda *a: accessor
        )
        result = evaluator.evaluate(
            expected,
            task_id="task:e2e:3",
            run_id="run:e2e:3",
            tenant_id="tenant:1",
            workspace_id="ws:1",
            evidence_refs=(),
            test_exit_code=None,
            now=frozen_at + timedelta(seconds=10),
        )

        assert result.status is OutcomeStatus.UNRESOLVED

    def test_llm_failure_rejects_pipeline(self):
        """If the LLM fails twice, infer() returns REJECTED."""
        provider = DeterministicProvider(scripted=(("bad", ()), ("bad", ())))
        proposer = SemanticProposer(provider, model_id="test-model")
        inferencer = ContractInferencer(proposer, model_id="test-model")

        contract, report = inferencer.infer(
            mandate_text=MANDATE_TEXT,
            tool_schemas=[EMAIL_TOOL_SCHEMA],
        )
        assert contract is None
        assert report.pipeline_state == "REJECTED"

    def test_clarification_then_confirmation_flow(self):
        """Low-confidence predicate → question → yes → pre-endorsed → freeze."""
        # One high-confidence, one low-confidence
        preds = json.loads(_semantic_predicates_response())
        preds[1]["confidence"] = 0.4  # below threshold
        provider = DeterministicProvider(text=json.dumps(preds))
        proposer = SemanticProposer(provider, model_id="test-model")
        inferencer = ContractInferencer(proposer, model_id="test-model")

        from agent_os_contracts import ClarificationAnswer

        contract, report = inferencer.infer(
            mandate_text=MANDATE_TEXT,
            tool_schemas=[EMAIL_TOOL_SCHEMA],
            task_id="task:e2e:4",
        )
        assert contract is not None
        assert report.pipeline_state == "QUESTIONS_PENDING"
        assert len(contract.clarification_questions) == 1

        # Answer "yes" to the clarification
        q = contract.clarification_questions[0]
        answer = ClarificationAnswer(
            question_id=q.question_id,
            answer="yes",
            answered_by="operator:1",
            answered_at=datetime.now(timezone.utc),
        )
        contract, report = inferencer.apply_clarification(contract, [answer])
        assert report.pipeline_state == "CONFIRMATION_PENDING"

        # Confirm remaining high-confidence semantic predicates
        sem_preds = [
            p for p in contract.success_predicates
            if p.kind is PredicateKind.SEMANTIC
        ]
        confirmations = [
            PredicateConfirmation(
                predicate_id=p.predicate_id,
                decision="approve",
                confirmed_by="operator:e2e-test",
                confirmed_at=datetime.now(timezone.utc),
            )
            for p in sem_preds
        ]
        _, predicate_set, report = inferencer.apply_confirmation(
            contract, confirmations
        )
        assert report.pipeline_state == "FROZEN"
        assert predicate_set is not None
        assert report.blocking_count >= 1
