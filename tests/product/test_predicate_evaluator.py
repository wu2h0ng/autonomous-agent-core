"""Tests for predicate checkers and PredicateConjunctionEvaluator."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent_os_contracts import (
    CheckType,
    EvidenceBinding,
    EvidenceSourceType,
    ExpectedOutcome,
    ObservedOutcome,
    OutcomeStatus,
    PredicateKind,
    PredicateSet,
    SuccessPredicate,
)

from agent_os_core.predicate_checkers import (
    run_checker,
)
from agent_os_core.predicate_evaluator import (
    InMemoryPredicateSetStore,
    PredicateConjunctionEvaluator,
    PREDICATE_CONJUNCTION_TYPE,
)


# ---------------------------------------------------------------------------
# In-memory EvidenceAccessor for tests
# ---------------------------------------------------------------------------


class FakeEvidenceAccessor:
    def __init__(
        self,
        artifacts: dict[str, bytes] | None = None,
        tool_results: dict[str, dict] | None = None,
        snapshots: dict[str, dict] | None = None,
    ) -> None:
        self._artifacts = artifacts or {}
        self._tool_results = tool_results or {}
        self._snapshots = snapshots or {}

    def artifact_content(self, artifact_id: str) -> bytes | None:
        return self._artifacts.get(artifact_id)

    def artifact_json(self, artifact_id: str) -> object | None:
        import json
        raw = self._artifacts.get(artifact_id)
        if raw is None:
            return None
        return json.loads(raw)

    def tool_result(self, tool_name: str, *, latest: bool = True) -> dict | None:
        return self._tool_results.get(tool_name)

    def state_snapshot(self, label: str) -> dict | None:
        return self._snapshots.get(label)


def _binding(source_type: EvidenceSourceType, selector: str, path: str | None = None) -> EvidenceBinding:
    return EvidenceBinding(
        binding_id=f"bind:{selector}",
        source_type=source_type,
        source_selector=selector,
        extract_path=path,
        relation="test evidence",
    )


def _predicate(
    check_type: CheckType,
    params: dict,
    *,
    blocking: bool = True,
    bindings: list[EvidenceBinding] | None = None,
    pid: str = "pred:test",
) -> SuccessPredicate:
    return SuccessPredicate(
        predicate_id=pid,
        kind=PredicateKind.SEMANTIC,
        description=f"test predicate {pid}",
        check_type=check_type,
        check_params=params,
        evidence_bindings=tuple(bindings or []),
        confidence=0.9,
        falsifiable=True,
        blocking=blocking,
        source="llm:test-model",
    )


# ---------------------------------------------------------------------------
# Checker tests
# ---------------------------------------------------------------------------


class TestTypeChecker:
    def test_string_pass(self):
        p = _predicate(
            CheckType.TYPE, {"expected_type": "string"},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.name")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"name": "hello"}'})
        passed, refs, detail = run_checker(p, acc)
        assert passed is True

    def test_integer_fail_when_string(self):
        p = _predicate(
            CheckType.TYPE, {"expected_type": "integer"},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.count")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"count": "five"}'})
        passed, _, _ = run_checker(p, acc)
        assert passed is False

    def test_bool_not_integer(self):
        p = _predicate(
            CheckType.TYPE, {"expected_type": "integer"},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.flag")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"flag": true}'})
        passed, _, _ = run_checker(p, acc)
        assert passed is False

    def test_missing_evidence_unresolved(self):
        p = _predicate(
            CheckType.TYPE, {"expected_type": "string"},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.name")],
        )
        acc = FakeEvidenceAccessor()
        passed, _, _ = run_checker(p, acc)
        assert passed is None

    def test_null_value_fails(self):
        p = _predicate(
            CheckType.TYPE, {"expected_type": "string"},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.name")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"name": null}'})
        passed, _, _ = run_checker(p, acc)
        assert passed is False


class TestRangeChecker:
    def test_in_range(self):
        p = _predicate(
            CheckType.RANGE, {"min": 0, "max": 100},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.score")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"score": 85}'})
        passed, _, _ = run_checker(p, acc)
        assert passed is True

    def test_below_min(self):
        p = _predicate(
            CheckType.RANGE, {"min": 0},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.score")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"score": -5}'})
        passed, _, _ = run_checker(p, acc)
        assert passed is False

    def test_non_numeric_fails(self):
        p = _predicate(
            CheckType.RANGE, {"min": 0},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.score")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"score": [1, 2]}'})
        passed, _, _ = run_checker(p, acc)
        assert passed is False

    def test_string_length_range(self):
        p = _predicate(
            CheckType.RANGE, {"min": 3, "max": 10},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.name")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"name": "hello"}'})
        assert run_checker(p, acc)[0] is True
        acc2 = FakeEvidenceAccessor(artifacts={"a1": b'{"name": "hi"}'})
        assert run_checker(p, acc2)[0] is False


class TestEnumChecker:
    def test_allowed(self):
        p = _predicate(
            CheckType.ENUM, {"allowed_values": ["draft", "published"]},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.status")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"status": "published"}'})
        assert run_checker(p, acc)[0] is True

    def test_not_allowed(self):
        p = _predicate(
            CheckType.ENUM, {"allowed_values": ["draft", "published"]},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.status")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"status": "deleted"}'})
        assert run_checker(p, acc)[0] is False


class TestRegexChecker:
    def test_match(self):
        p = _predicate(
            CheckType.REGEX, {"pattern": r"^ORD-\d+$"},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.order_id")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"order_id": "ORD-12345"}'})
        assert run_checker(p, acc)[0] is True

    def test_no_match(self):
        p = _predicate(
            CheckType.REGEX, {"pattern": r"^ORD-\d+$"},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.order_id")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"order_id": "ABC-123"}'})
        assert run_checker(p, acc)[0] is False


class TestCardinalityChecker:
    def test_min_count_pass(self):
        p = _predicate(
            CheckType.CARDINALITY,
            {"target": "$.items", "min_count": 1},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"items": [1, 2, 3]}'})
        assert run_checker(p, acc)[0] is True

    def test_min_count_fail(self):
        p = _predicate(
            CheckType.CARDINALITY,
            {"target": "$.items", "min_count": 1},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"items": []}'})
        assert run_checker(p, acc)[0] is False


class TestFieldPresenceChecker:
    def test_present(self):
        p = _predicate(
            CheckType.FIELD_PRESENCE, {},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.id")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"id": "x"}'})
        assert run_checker(p, acc)[0] is True

    def test_absent(self):
        p = _predicate(
            CheckType.FIELD_PRESENCE, {},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.id")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"name": "x"}'})
        assert run_checker(p, acc)[0] is False


class TestToolResponseChecker:
    def test_status_2xx_pass(self):
        p = _predicate(
            CheckType.TOOL_RESPONSE,
            {"tool_name": "send_email", "condition": {"$.status_code": {"$gte": 200}}},
            bindings=[_binding(EvidenceSourceType.TOOL_RESPONSE, "send_email")],
        )
        acc = FakeEvidenceAccessor(
            tool_results={"send_email": {"status_code": 200, "body": {}}}
        )
        assert run_checker(p, acc)[0] is True

    def test_status_5xx_fail(self):
        p = _predicate(
            CheckType.TOOL_RESPONSE,
            {"tool_name": "send_email", "condition": {"$.status_code": 200}},
            bindings=[_binding(EvidenceSourceType.TOOL_RESPONSE, "send_email")],
        )
        acc = FakeEvidenceAccessor(
            tool_results={"send_email": {"status_code": 500, "body": {}}}
        )
        assert run_checker(p, acc)[0] is False

    def test_missing_tool_result_unresolved(self):
        p = _predicate(
            CheckType.TOOL_RESPONSE,
            {"tool_name": "send_email", "condition": {"$.status_code": {"$gte": 200}}},
            bindings=[_binding(EvidenceSourceType.TOOL_RESPONSE, "send_email")],
        )
        acc = FakeEvidenceAccessor()
        assert run_checker(p, acc)[0] is None


class TestStateDeltaChecker:
    def test_mvp_returns_unresolved(self):
        p = _predicate(
            CheckType.STATE_DELTA,
            {"snapshot": "pre-run", "path": "$.config", "expected": "unchanged"},
            bindings=[_binding(EvidenceSourceType.ENVIRONMENT_QUERY, "pre-run")],
        )
        acc = FakeEvidenceAccessor()
        passed, _, _ = run_checker(p, acc)
        assert passed is None  # MVP: no baseline → UNRESOLVED


class TestLLMJudgeChecker:
    def test_advisory_returns_none(self):
        p = _predicate(
            CheckType.LLM_JUDGE,
            {"criteria": "response is helpful"},
            blocking=False,
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"text": "hi"}'})
        passed, _, _ = run_checker(p, acc)
        assert passed is None  # advisory, never blocks


# ---------------------------------------------------------------------------
# PredicateConjunctionEvaluator tests
# ---------------------------------------------------------------------------


def _make_predicate_set(predicates: list[SuccessPredicate]) -> PredicateSet:
    return PredicateSet(
        set_id="set:test",
        contract_id="contract:test",
        task_id="task:1",
        tenant_id="tenant:1",
        workspace_id="ws:1",
        predicates=tuple(predicates),
        frozen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _make_expected(
    predicate_set: PredicateSet,
    *,
    threshold: float = 1.0,
    frozen_at: datetime | None = None,
) -> ExpectedOutcome:
    now = frozen_at or datetime(2026, 1, 1, tzinfo=timezone.utc)
    return ExpectedOutcome(
        expected_outcome_id="expected:1",
        task_id="task:1",
        tenant_id="tenant:1",
        workspace_id="ws:1",
        evaluator_type=PREDICATE_CONJUNCTION_TYPE,
        evaluator_version=predicate_set.content_key(),
        evidence_requirements=("predicate-set",),
        failure_semantics=("blocking predicate failed",),
        threshold=threshold,
        observation_window_seconds=3600,
        frozen_at=now,
    )


class TestCrossConsistencyChecker:
    def test_empty_refs_is_unresolved_not_vacuously_true(self):
        p = _predicate(
            CheckType.CROSS_CONSISTENCY,
            {"refs": [], "relation": "equal"},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.x")],
        )
        passed, _refs, _detail = run_checker(p, FakeEvidenceAccessor())
        assert passed is None

    def test_malformed_refs_is_unresolved_not_vacuously_true(self):
        p = _predicate(
            CheckType.CROSS_CONSISTENCY,
            {"refs": ["garbage", "garbage2"], "relation": "equal"},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.x")],
        )
        passed, _refs, _detail = run_checker(p, FakeEvidenceAccessor())
        assert passed is None

    def test_single_valid_ref_is_unresolved_not_vacuously_true(self):
        p = _predicate(
            CheckType.CROSS_CONSISTENCY,
            {"refs": ["artifact:a1:$.x"], "relation": "equal"},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.x")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"x": 1}'})
        passed, _refs, _detail = run_checker(p, acc)
        assert passed is None

    def test_mixed_malformed_and_valid_collapsing_to_one_is_unresolved(self):
        p = _predicate(
            CheckType.CROSS_CONSISTENCY,
            {"refs": ["garbage", "artifact:a1:$.x"], "relation": "equal"},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.x")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"x": 1}'})
        passed, _refs, _detail = run_checker(p, acc)
        assert passed is None

    def test_all_refs_missing_path_is_unresolved(self):
        p = _predicate(
            CheckType.CROSS_CONSISTENCY,
            {
                "refs": ["artifact:a1:$.missing", "artifact:a1:$.absent"],
                "relation": "equal",
            },
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.x")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"x": 1}'})
        passed, _refs, _detail = run_checker(p, acc)
        assert passed is None

    def test_two_equal_refs_pass(self):
        p = _predicate(
            CheckType.CROSS_CONSISTENCY,
            {"refs": ["artifact:a1:$.x", "artifact:a2:$.x"], "relation": "equal"},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.x")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"x": 5}', "a2": b'{"x": 5}'})
        passed, _refs, _detail = run_checker(p, acc)
        assert passed is True

    def test_duplicate_refs_is_unresolved(self):
        p = _predicate(
            CheckType.CROSS_CONSISTENCY,
            {"refs": ["artifact:a1:$.x", "artifact:a1:$.x"], "relation": "equal"},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.x")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"x": 1}'})
        passed, _refs, _detail = run_checker(p, acc)
        assert passed is None

    def test_non_jsonpath_refs_is_unresolved(self):
        p = _predicate(
            CheckType.CROSS_CONSISTENCY,
            {"refs": ["artifact:a1:x", "artifact:a1:y"], "relation": "equal"},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.x")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"x": 1, "y": 2}'})
        passed, _refs, _detail = run_checker(p, acc)
        assert passed is None

    def test_two_distinct_paths_equal_values_pass(self):
        p = _predicate(
            CheckType.CROSS_CONSISTENCY,
            {"refs": ["artifact:a1:$.x", "artifact:a1:$.y"], "relation": "equal"},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.x")],
        )
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"x": 7, "y": 7}'})
        passed, _refs, _detail = run_checker(p, acc)
        assert passed is True


class TestPredicateConjunctionEvaluator:
    def _make_evaluator(self, predicate_set, accessor):
        store = InMemoryPredicateSetStore()
        store.save(predicate_set)

        def factory(task_id, run_id, tenant_id, workspace_id, evidence_refs):
            return accessor

        return PredicateConjunctionEvaluator(store, accessor_factory=factory)

    def test_all_pass_verified(self):
        p1 = _predicate(
            CheckType.FIELD_PRESENCE, {},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.id")],
            pid="pred:p1",
        )
        p2 = _predicate(
            CheckType.ENUM, {"allowed_values": ["ok"]},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.status")],
            pid="pred:p2",
        )
        ps = _make_predicate_set([p1, p2])
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"id": "x", "status": "ok"}'})
        evaluator = self._make_evaluator(ps, acc)
        expected = _make_expected(ps)

        result = evaluator.evaluate(
            expected,
            task_id="task:1", run_id="run:1", tenant_id="tenant:1", workspace_id="ws:1",
            evidence_refs=("a1",), test_exit_code=None,
            now=expected.frozen_at + timedelta(seconds=10),
        )
        assert result.status is OutcomeStatus.VERIFIED
        assert result.score == 1.0

    def test_one_fails_not_met(self):
        p1 = _predicate(
            CheckType.FIELD_PRESENCE, {},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.id")],
            pid="pred:p1",
        )
        p2 = _predicate(
            CheckType.ENUM, {"allowed_values": ["ok"]},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.status")],
            pid="pred:p2",
        )
        ps = _make_predicate_set([p1, p2])
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"id": "x", "status": "bad"}'})
        evaluator = self._make_evaluator(ps, acc)
        expected = _make_expected(ps)

        result = evaluator.evaluate(
            expected,
            task_id="task:1", run_id="run:1", tenant_id="tenant:1", workspace_id="ws:1",
            evidence_refs=("a1",), test_exit_code=None,
            now=expected.frozen_at + timedelta(seconds=10),
        )
        assert result.status is OutcomeStatus.NOT_MET
        assert result.score == 0.5
        assert any("pred:p2" in g for g in result.unresolved_gaps)

    def test_missing_evidence_unresolved(self):
        p1 = _predicate(
            CheckType.FIELD_PRESENCE, {},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.id")],
            pid="pred:p1",
        )
        ps = _make_predicate_set([p1])
        acc = FakeEvidenceAccessor()  # no artifacts
        evaluator = self._make_evaluator(ps, acc)
        expected = _make_expected(ps)

        result = evaluator.evaluate(
            expected,
            task_id="task:1", run_id="run:1", tenant_id="tenant:1", workspace_id="ws:1",
            evidence_refs=(), test_exit_code=None,
            now=expected.frozen_at + timedelta(seconds=10),
        )
        assert result.status is OutcomeStatus.UNRESOLVED

    def test_advisory_predicate_does_not_block(self):
        p1 = _predicate(
            CheckType.FIELD_PRESENCE, {},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.id")],
            pid="pred:p1",
        )
        p2 = _predicate(
            CheckType.LLM_JUDGE, {"criteria": "helpful"},
            blocking=False,
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1")],
            pid="pred:p2",
        )
        ps = _make_predicate_set([p1, p2])
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"id": "x"}'})
        evaluator = self._make_evaluator(ps, acc)
        expected = _make_expected(ps)

        result = evaluator.evaluate(
            expected,
            task_id="task:1", run_id="run:1", tenant_id="tenant:1", workspace_id="ws:1",
            evidence_refs=("a1",), test_exit_code=None,
            now=expected.frozen_at + timedelta(seconds=10),
        )
        assert result.status is OutcomeStatus.VERIFIED

    def test_scope_mismatch_invalid(self):
        p1 = _predicate(
            CheckType.FIELD_PRESENCE, {},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.id")],
            pid="pred:p1",
        )
        ps = _make_predicate_set([p1])
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"id": "x"}'})
        evaluator = self._make_evaluator(ps, acc)
        expected = _make_expected(ps)

        result = evaluator.evaluate(
            expected,
            task_id="task:OTHER", run_id="run:1",
            tenant_id="tenant:1", workspace_id="ws:1",
            evidence_refs=("a1",), test_exit_code=None,
            now=expected.frozen_at + timedelta(seconds=10),
        )
        assert result.status is OutcomeStatus.INVALID

    def test_window_expired_unresolved(self):
        p1 = _predicate(
            CheckType.FIELD_PRESENCE, {},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.id")],
            pid="pred:p1",
        )
        ps = _make_predicate_set([p1])
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"id": "x"}'})
        evaluator = self._make_evaluator(ps, acc)
        expected = _make_expected(ps)

        result = evaluator.evaluate(
            expected,
            task_id="task:1", run_id="run:1", tenant_id="tenant:1", workspace_id="ws:1",
            evidence_refs=("a1",), test_exit_code=None,
            now=expected.frozen_at + timedelta(seconds=7200),
        )
        assert result.status is OutcomeStatus.UNRESOLVED

    def test_contract_error_flags_predicate_set_scope_mismatch(self):
        p1 = _predicate(
            CheckType.FIELD_PRESENCE, {},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.id")],
            pid="pred:p1",
        )
        ps = _make_predicate_set([p1])
        evaluator = self._make_evaluator(ps, FakeEvidenceAccessor())
        expected = _make_expected(ps).model_copy(update={"tenant_id": "tenant:other"})
        assert evaluator.contract_error(expected) == "predicate set scope mismatch"

    def test_contract_error_unknown_predicate_set(self):
        p1 = _predicate(
            CheckType.FIELD_PRESENCE, {},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.id")],
            pid="pred:p1",
        )
        ps = _make_predicate_set([p1])
        store = InMemoryPredicateSetStore()  # not saved
        evaluator = PredicateConjunctionEvaluator(store, accessor_factory=lambda *a: FakeEvidenceAccessor())
        expected = _make_expected(ps)
        assert evaluator.contract_error(expected) == "predicate set not found"

    def test_verify_verified_recording_accepts_valid(self):
        p1 = _predicate(
            CheckType.FIELD_PRESENCE, {},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.id")],
            pid="pred:p1",
        )
        ps = _make_predicate_set([p1])
        acc = FakeEvidenceAccessor(artifacts={"a1": b'{"id": "x"}'})
        evaluator = self._make_evaluator(ps, acc)
        expected = _make_expected(ps)
        outcome = ObservedOutcome(
            observed_outcome_id="observed:1",
            expected_outcome_id="expected:1",
            task_id="task:1", run_id="run:1",
            tenant_id="tenant:1", workspace_id="ws:1",
            evaluator_type=PREDICATE_CONJUNCTION_TYPE,
            evaluator_version=ps.content_key(),
            status=OutcomeStatus.VERIFIED, score=1.0, confidence=1.0,
            evidence_refs=("a1",), unresolved_gaps=(),
            observed_at=expected.frozen_at + timedelta(seconds=10),
        )
        # Should not raise
        evaluator.verify_verified_recording(
            expected, outcome, report_resolver=lambda *a: None,
            now=expected.frozen_at + timedelta(seconds=20),
        )

    def test_verify_verified_recording_rejects_low_score(self):
        from agent_os_core.errors import InvalidTransitionError
        p1 = _predicate(
            CheckType.FIELD_PRESENCE, {},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.id")],
            pid="pred:p1",
        )
        ps = _make_predicate_set([p1])
        evaluator = self._make_evaluator(ps, FakeEvidenceAccessor())
        expected = _make_expected(ps)
        outcome = ObservedOutcome(
            observed_outcome_id="observed:1",
            expected_outcome_id="expected:1",
            task_id="task:1", run_id="run:1",
            tenant_id="tenant:1", workspace_id="ws:1",
            evaluator_type=PREDICATE_CONJUNCTION_TYPE,
            evaluator_version=ps.content_key(),
            status=OutcomeStatus.VERIFIED, score=0.5, confidence=1.0,
            evidence_refs=("a1",), unresolved_gaps=(),
            observed_at=expected.frozen_at + timedelta(seconds=10),
        )
        with pytest.raises(InvalidTransitionError):
            evaluator.verify_verified_recording(
                expected, outcome, report_resolver=lambda *a: None,
                now=expected.frozen_at + timedelta(seconds=20),
            )

    def test_verify_verified_recording_rejects_unbound_evidence(self):
        from agent_os_core.errors import InvalidTransitionError
        p1 = _predicate(
            CheckType.FIELD_PRESENCE, {},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.id")],
            pid="pred:p1",
        )
        ps = _make_predicate_set([p1])
        # The checker needs "a1", but the recorded outcome cites only "forged".
        evaluator = self._make_evaluator(
            ps, FakeEvidenceAccessor(artifacts={"a1": b'{"id": "x"}'})
        )
        expected = _make_expected(ps)
        outcome = ObservedOutcome(
            observed_outcome_id="observed:1",
            expected_outcome_id="expected:1",
            task_id="task:1", run_id="run:1",
            tenant_id="tenant:1", workspace_id="ws:1",
            evaluator_type=PREDICATE_CONJUNCTION_TYPE,
            evaluator_version=ps.content_key(),
            status=OutcomeStatus.VERIFIED, score=1.0, confidence=1.0,
            evidence_refs=("forged",), unresolved_gaps=(),
            observed_at=expected.frozen_at + timedelta(seconds=10),
        )
        with pytest.raises(InvalidTransitionError):
            evaluator.verify_verified_recording(
                expected, outcome, report_resolver=lambda *a: None,
                now=expected.frozen_at + timedelta(seconds=20),
            )

    def test_verify_verified_recording_rejects_failed_predicate(self):
        from agent_os_core.errors import InvalidTransitionError
        p1 = _predicate(
            CheckType.FIELD_PRESENCE, {},
            bindings=[_binding(EvidenceSourceType.ARTIFACT, "a1", "$.id")],
            pid="pred:p1",
        )
        ps = _make_predicate_set([p1])
        # Accessor has no artifact "a1", so the blocking checker cannot pass.
        evaluator = self._make_evaluator(ps, FakeEvidenceAccessor())
        expected = _make_expected(ps)
        outcome = ObservedOutcome(
            observed_outcome_id="observed:1",
            expected_outcome_id="expected:1",
            task_id="task:1", run_id="run:1",
            tenant_id="tenant:1", workspace_id="ws:1",
            evaluator_type=PREDICATE_CONJUNCTION_TYPE,
            evaluator_version=ps.content_key(),
            status=OutcomeStatus.VERIFIED, score=1.0, confidence=1.0,
            evidence_refs=("a1",), unresolved_gaps=(),
            observed_at=expected.frozen_at + timedelta(seconds=10),
        )
        with pytest.raises(InvalidTransitionError):
            evaluator.verify_verified_recording(
                expected, outcome, report_resolver=lambda *a: None,
                now=expected.frozen_at + timedelta(seconds=20),
            )
