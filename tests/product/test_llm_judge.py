"""Tests for LLMJudgeChecker (advisory cross-family judge)."""

from __future__ import annotations

import json


from agent_os_contracts import (
    CheckType,
    EvidenceBinding,
    EvidenceSourceType,
    PredicateKind,
    SuccessPredicate,
)

from agent_os_core.llm_judge import LLMJudgeChecker
from agent_os_core.provider import DeterministicProvider


def _judge_predicate(rubric: str = "The email is polite") -> SuccessPredicate:
    return SuccessPredicate(
        predicate_id="pred:judge:001",
        kind=PredicateKind.SEMANTIC,
        description="Email quality judged by LLM",
        check_type=CheckType.LLM_JUDGE,
        check_params={"rubric": rubric},
        evidence_bindings=(EvidenceBinding(
            binding_id="bind:judge",
            source_type=EvidenceSourceType.ARTIFACT,
            source_selector="email.txt",
            relation="email content to judge",
        ),),
        confidence=0.8,
        falsifiable=True,
        blocking=False,
        source="llm:proposer-model",
    )


class FakeAccessor:
    def __init__(self, artifacts: dict[str, bytes] | None = None):
        self._artifacts = artifacts or {}

    def artifact_content(self, artifact_id: str) -> bytes | None:
        return self._artifacts.get(artifact_id)

    def artifact_json(self, artifact_id: str):
        import json as _json
        raw = self._artifacts.get(artifact_id)
        if raw is None:
            return None
        return _json.loads(raw)

    def tool_result(self, tool_name: str, *, latest: bool = True):
        return None

    def state_snapshot(self, label: str):
        return None


class TestLLMJudgeChecker:
    def test_pass_verdict(self):
        judge_response = json.dumps({
            "verdict": "pass",
            "reasoning": "The email is polite and professional",
            "confidence": 0.9,
        })
        provider = DeterministicProvider(text=judge_response)
        checker = LLMJudgeChecker(provider, judge_model_id="judge-model")
        pred = _judge_predicate()
        accessor = FakeAccessor(artifacts={"email.txt": b"Dear Sir, thank you for..."})

        passed, refs, detail = checker.check(pred, accessor)
        assert passed is True
        assert "email.txt" in refs
        assert "polite" in detail

    def test_fail_verdict(self):
        judge_response = json.dumps({
            "verdict": "fail",
            "reasoning": "The email is rude and dismissive",
            "confidence": 0.85,
        })
        provider = DeterministicProvider(text=judge_response)
        checker = LLMJudgeChecker(provider)
        pred = _judge_predicate()
        accessor = FakeAccessor(artifacts={"email.txt": b"Whatever, figure it out yourself."})

        passed, refs, detail = checker.check(pred, accessor)
        assert passed is False
        assert "rude" in detail

    def test_fenced_json_parsed(self):
        judge_response = "```json\n" + json.dumps({
            "verdict": "pass",
            "reasoning": "ok",
            "confidence": 0.8,
        }) + "\n```"
        provider = DeterministicProvider(text=judge_response)
        checker = LLMJudgeChecker(provider)
        pred = _judge_predicate()
        accessor = FakeAccessor(artifacts={"email.txt": b"hello"})
        passed, _, _ = checker.check(pred, accessor)
        assert passed is True

    def test_missing_evidence_returns_none(self):
        provider = DeterministicProvider(text='{"verdict":"pass","reasoning":"ok"}')
        checker = LLMJudgeChecker(provider)
        pred = _judge_predicate()
        accessor = FakeAccessor()  # no artifacts
        passed, refs, detail = checker.check(pred, accessor)
        assert passed is None
        assert "no evidence" in detail

    def test_invalid_judge_output_returns_none(self):
        provider = DeterministicProvider(text="not json at all")
        checker = LLMJudgeChecker(provider)
        pred = _judge_predicate()
        accessor = FakeAccessor(artifacts={"email.txt": b"hello"})
        passed, _, detail = checker.check(pred, accessor)
        assert passed is None
        assert "invalid" in detail

    def test_missing_rubric_returns_none(self):
        provider = DeterministicProvider(text='{"verdict":"pass"}')
        checker = LLMJudgeChecker(provider)
        pred = SuccessPredicate(
            predicate_id="pred:judge:002",
            kind=PredicateKind.SEMANTIC,
            description="no rubric",
            check_type=CheckType.LLM_JUDGE,
            check_params={},
            evidence_bindings=(EvidenceBinding(
                binding_id="bind:j",
                source_type=EvidenceSourceType.ARTIFACT,
                source_selector="email.txt",
                relation="test",
            ),),
            confidence=0.8,
            falsifiable=True,
            blocking=False,
            source="llm:test",
        )
        accessor = FakeAccessor(artifacts={"email.txt": b"hello"})
        passed, _, detail = checker.check(pred, accessor)
        assert passed is None
        assert "rubric" in detail

    def test_advisory_result_does_not_block_verdict(self):
        """Integration: LLM_JUDGE fail must not cause NOT_MET when blocking=False."""
        from agent_os_core.predicate_evaluator import (
            InMemoryPredicateSetStore,
            PredicateConjunctionEvaluator,
            PREDICATE_CONJUNCTION_TYPE,
        )
        from agent_os_contracts import (
            ExpectedOutcome,
            PredicateSet,
        )
        from datetime import datetime, timedelta, timezone

        # One blocking structural predicate that passes + one advisory LLM_JUDGE that fails
        blocking_pred = SuccessPredicate(
            predicate_id="pred:block",
            kind=PredicateKind.STRUCTURAL,
            description="field exists",
            check_type=CheckType.FIELD_PRESENCE,
            check_params={},
            evidence_bindings=(EvidenceBinding(
                binding_id="bind:b",
                source_type=EvidenceSourceType.ARTIFACT,
                source_selector="output.json",
                extract_path="$.id",
                relation="id exists",
            ),),
            confidence=1.0,
            falsifiable=True,
            blocking=True,
            source="mechanical:tool_response_schema",
        )
        judge_pred = _judge_predicate()
        ps = PredicateSet(
            set_id="set:test",
            contract_id="contract:test",
            task_id="task:1",
            tenant_id="tenant:1",
            workspace_id="ws:1",
            predicates=(blocking_pred, judge_pred),
            frozen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        store = InMemoryPredicateSetStore()
        store.save(ps)

        judge_provider = DeterministicProvider(text=json.dumps({
            "verdict": "fail",
            "reasoning": "not polite enough",
            "confidence": 0.7,
        }))
        judge = LLMJudgeChecker(judge_provider)

        accessor = FakeAccessor(artifacts={
            "output.json": b'{"id": "123"}',
            "email.txt": b"meh",
        })

        def factory(*args):
            return accessor

        evaluator = PredicateConjunctionEvaluator(
            store, accessor_factory=factory, judge_checker=judge
        )
        expected = ExpectedOutcome(
            expected_outcome_id="expected:1",
            task_id="task:1",
            tenant_id="tenant:1",
            workspace_id="ws:1",
            evaluator_type=PREDICATE_CONJUNCTION_TYPE,
            evaluator_version=ps.content_key(),
            evidence_requirements=("predicate-set",),
            failure_semantics=("blocking predicate failed",),
            threshold=1.0,
            observation_window_seconds=3600,
            frozen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        result = evaluator.evaluate(
            expected,
            task_id="task:1", run_id="run:1",
            tenant_id="tenant:1", workspace_id="ws:1",
            evidence_refs=("output.json",), test_exit_code=None,
            now=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=10),
        )
        # Blocking predicate passes → VERIFIED despite advisory judge fail
        assert result.status.value == "VERIFIED"
        assert result.score == 1.0
