from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from agent_os_contracts import ExpectedOutcome, OutcomeStatus
from agent_os_core import DeterministicOutcomeEvaluator, ValidatedTestReport


FROZEN_AT = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)


def _expected(**updates: Any) -> ExpectedOutcome:
    values: dict[str, Any] = {
        "expected_outcome_id": "expected-1",
        "task_id": "task-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "evaluator_type": "pytest",
        "evaluator_version": "1",
        "evidence_requirements": ("test-report",),
        "failure_semantics": ("non-zero exit",),
        "threshold": 1.0,
        "observation_window_seconds": 60,
        "frozen_at": FROZEN_AT,
    }
    values.update(updates)
    return ExpectedOutcome(**values)


def _evaluate(
    expected: ExpectedOutcome,
    *,
    trusted: bool = True,
    **updates: Any,
):
    values: dict[str, Any] = {
        "task_id": "task-1",
        "run_id": "run-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "evidence_refs": ("artifact:test-report",),
        "test_exit_code": 0,
        "now": FROZEN_AT + timedelta(seconds=30),
    }
    values.update(updates)
    evidence_refs = tuple(values["evidence_refs"])
    exit_code = values["test_exit_code"]
    if trusted and isinstance(exit_code, int):
        report = ValidatedTestReport(
            artifact_ids=evidence_refs,
            exit_code=exit_code,
            node_id="tests",
            action_id="action-tests",
            receipt_id="receipt-tests",
            completed_sequence=10,
            completed_at=FROZEN_AT + timedelta(seconds=20),
        )

        def resolve(_task_id: str, _run_id: str) -> ValidatedTestReport:
            return report

        evaluator = DeterministicOutcomeEvaluator(resolve)
    else:
        evaluator = DeterministicOutcomeEvaluator()
    return evaluator.evaluate(expected, **values)


def test_score_below_frozen_threshold_is_not_verified() -> None:
    outcome = _evaluate(_expected(threshold=2.0))

    assert outcome.status is OutcomeStatus.NOT_MET
    assert outcome.score == 1.0


def test_reproduced_false_verified_attack_fails_closed() -> None:
    outcome = _evaluate(
        _expected(
            threshold=999.0,
            evidence_requirements=("test-report", "independent-review"),
        ),
        trusted=False,
        evidence_refs=("artifact:" + "a" * 64,),
    )

    assert outcome.status is OutcomeStatus.INVALID
    assert outcome.score is None
    assert "unsupported evidence requirements" in outcome.unresolved_gaps


def test_unknown_evaluator_identity_is_invalid() -> None:
    outcome = _evaluate(_expected(evaluator_type="unknown"))

    assert outcome.status is OutcomeStatus.INVALID
    assert "unsupported evaluator" in outcome.unresolved_gaps


def test_missing_required_test_report_is_unresolved() -> None:
    outcome = _evaluate(_expected(), evidence_refs=())

    assert outcome.status is OutcomeStatus.UNRESOLVED
    assert "missing required evidence: test-report" in outcome.unresolved_gaps


def test_observation_after_frozen_window_is_unresolved() -> None:
    outcome = _evaluate(_expected(), now=FROZEN_AT + timedelta(seconds=61))

    assert outcome.status is OutcomeStatus.UNRESOLVED
    assert "observation window expired" in outcome.unresolved_gaps


def test_unsupported_failure_semantics_is_invalid() -> None:
    outcome = _evaluate(_expected(failure_semantics=("model says it is good",)))

    assert outcome.status is OutcomeStatus.INVALID
    assert "unsupported failure semantics" in outcome.unresolved_gaps


def test_scope_mismatch_is_invalid() -> None:
    outcome = _evaluate(_expected(), task_id="task-other")

    assert outcome.status is OutcomeStatus.INVALID
    assert "expected outcome scope mismatch" in outcome.unresolved_gaps


def test_forged_artifact_cannot_produce_verified_without_trusted_resolver() -> None:
    outcome = _evaluate(
        _expected(),
        trusted=False,
        evidence_refs=("artifact:" + "a" * 64,),
    )

    assert outcome.status is OutcomeStatus.UNRESOLVED
    assert "test-report evidence is not bound to the durable event chain" in (
        outcome.unresolved_gaps
    )


def test_missing_runtime_exit_code_is_not_defaulted_to_failure() -> None:
    report = ValidatedTestReport(
        artifact_ids=("artifact:" + "b" * 64,),
        exit_code=0,
        node_id="tests",
        action_id="action-tests",
        receipt_id="receipt-tests",
        completed_sequence=10,
        completed_at=FROZEN_AT + timedelta(seconds=20),
    )

    def resolve(_task_id: str, _run_id: str) -> ValidatedTestReport:
        return report

    outcome = DeterministicOutcomeEvaluator(resolve).evaluate(
        _expected(),
        task_id="task-1",
        run_id="run-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        evidence_refs=report.artifact_ids,
        test_exit_code=None,
        now=FROZEN_AT + timedelta(seconds=30),
    )

    assert outcome.status is OutcomeStatus.UNRESOLVED
    assert "missing pytest exit code" in outcome.unresolved_gaps


def test_evaluator_uses_injected_clock_when_caller_omits_now() -> None:
    report = ValidatedTestReport(
        artifact_ids=("artifact:" + "c" * 64,),
        exit_code=0,
        node_id="tests",
        action_id="action-tests",
        receipt_id="receipt-tests",
        completed_sequence=10,
        completed_at=FROZEN_AT + timedelta(seconds=20),
    )

    evaluator = DeterministicOutcomeEvaluator(
        lambda _task_id, _run_id: report,
        clock=lambda: FROZEN_AT + timedelta(seconds=30),
    )
    outcome = evaluator.evaluate(
        _expected(),
        task_id="task-1",
        run_id="run-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        evidence_refs=report.artifact_ids,
        test_exit_code=0,
    )

    assert outcome.status is OutcomeStatus.VERIFIED
    assert outcome.observed_at == FROZEN_AT + timedelta(seconds=30)


def test_default_registry_registers_predicate_conjunction_evaluator() -> None:
    """C3: the default registry must include the predicate:conjunction evaluator
    alongside pytest, so named-goal predicates can be mechanically evaluated."""
    from agent_os_core.outcome_evaluators import default_registry
    from agent_os_core.predicate_evaluator import PREDICATE_CONJUNCTION_TYPE

    registry = default_registry()
    predicate_evaluator = registry.get(PREDICATE_CONJUNCTION_TYPE)
    assert predicate_evaluator is not None, (
        "predicate:conjunction evaluator must be registered in default_registry"
    )
    assert predicate_evaluator.evaluator_type == PREDICATE_CONJUNCTION_TYPE


def test_predicate_contract_rejects_unknown_predicate_set() -> None:
    """C3: an unknown predicate-set digest is rejected by contract_error before
    any evaluation — the empty in-memory store cannot resolve it."""
    from agent_os_core.outcome_evaluators import default_registry
    from agent_os_core.predicate_evaluator import PREDICATE_CONJUNCTION_TYPE
    from datetime import datetime, timezone
    from agent_os_contracts.outcome import ExpectedOutcome

    registry = default_registry()
    evaluator = registry.get(PREDICATE_CONJUNCTION_TYPE)
    assert evaluator is not None

    expected = ExpectedOutcome(
        expected_outcome_id="exp-1",
        task_id="task-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        evaluator_type=PREDICATE_CONJUNCTION_TYPE,
        evaluator_version="nonexistent-digest",
        evidence_requirements=("predicate-set",),
        failure_semantics=("blocking predicate failed",),
        threshold=1.0,
        frozen_at=datetime.now(timezone.utc),
        observation_window_seconds=3600,
    )

    error = evaluator.contract_error(expected)
    assert error == "predicate set not found"


def test_default_registry_evaluator_has_no_accessor_factory() -> None:
    """C3 MAJOR-1: the default-registry predicate evaluator must have
    accessor_factory=None — this is the fail-closed switch. Without a real
    evidence accessor, evaluate() must return UNRESOLVED rather than guessing."""
    from agent_os_core.outcome_evaluators import default_registry
    from agent_os_core.predicate_evaluator import PREDICATE_CONJUNCTION_TYPE

    registry = default_registry()
    evaluator = registry.get(PREDICATE_CONJUNCTION_TYPE)
    assert evaluator is not None
    assert evaluator._accessor_factory is None, (
        "default-registry predicate evaluator must have accessor_factory=None; "
        "a guessing factory would silently produce fake VERIFIED outcomes"
    )


def test_evaluate_without_accessor_returns_unresolved() -> None:
    """C3 MAJOR-1: with a pre-loaded predicate set but accessor_factory=None,
    evaluate() must return UNRESOLVED with 'evidence accessor not configured'."""
    from datetime import datetime, timezone
    from agent_os_contracts import ExpectedOutcome, PredicateSet
    from agent_os_contracts.outcome import OutcomeStatus
    from agent_os_core.outcome_evaluators import default_registry
    from agent_os_core.predicate_evaluator import PREDICATE_CONJUNCTION_TYPE

    # Build a minimal predicate set and save it into the evaluator's store.
    # The predicate check itself won't run (accessor_factory=None), so any
    # well-formed predicate satisfies the contract.
    from agent_os_contracts import SuccessPredicate, PredicateKind
    minimal_pred = SuccessPredicate(
        predicate_id="pred:1",
        kind=PredicateKind.SEMANTIC,
        description="test predicate",
        check_type="FIELD_PRESENCE",
        check_params={"path": "answer"},
        evidence_bindings=(__import__("agent_os_contracts").EvidenceBinding(
            binding_id="bind:1",
            source_type="TOOL_RESPONSE",
            source_selector="assistant",
            extract_path="answer",
            relation="test",
        ),),
        confidence=0.9,
        falsifiable=True,
        blocking=True,
        source="test",
    )
    ps = PredicateSet(
        set_id="set:test",
        contract_id="contract:test",
        task_id="task-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        predicates=(minimal_pred,),
        frozen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    registry = default_registry()
    evaluator = registry.get(PREDICATE_CONJUNCTION_TYPE)
    assert evaluator is not None
    evaluator._store.save(ps)  # type: ignore[attr-defined]

    expected = ExpectedOutcome(
        expected_outcome_id="expected:1",
        task_id="task-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        evaluator_type=PREDICATE_CONJUNCTION_TYPE,
        evaluator_version=ps.content_key(),
        evidence_requirements=("predicate-set",),
        failure_semantics=("blocking predicate failed",),
        threshold=1.0,
        frozen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        observation_window_seconds=3600,
    )

    observed = datetime(2026, 1, 1, second=30, tzinfo=timezone.utc)
    outcome = evaluator.evaluate(
        expected,
        task_id="task-1",
        run_id="run-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        evidence_refs=("predicate-set:" + ps.content_key(),),
        test_exit_code=None,
        now=observed,
    )

    assert outcome.status is OutcomeStatus.UNRESOLVED, (
        f"expected UNRESOLVED without accessor, got {outcome.status}: {outcome.unresolved_gaps}"
    )
    assert any("evidence accessor" in g for g in outcome.unresolved_gaps), (
        f"expected 'evidence accessor not configured' gap, got {outcome.unresolved_gaps}"
    )


def test_verify_verified_without_accessor_raises() -> None:
    """C3 MAJOR-1: verify_verified_recording() with accessor_factory=None must
    raise InvalidTransitionError — a stale VERIFIED must not be trusted."""
    import pytest
    from datetime import datetime, timezone
    from agent_os_contracts import ExpectedOutcome, ObservedOutcome, PredicateSet
    from agent_os_contracts.outcome import OutcomeStatus
    from agent_os_core.errors import InvalidTransitionError
    from agent_os_core.outcome_evaluators import default_registry
    from agent_os_core.predicate_evaluator import PREDICATE_CONJUNCTION_TYPE

    from agent_os_contracts import SuccessPredicate, PredicateKind
    minimal_pred = SuccessPredicate(
        predicate_id="pred:1",
        kind=PredicateKind.SEMANTIC,
        description="test predicate",
        check_type="FIELD_PRESENCE",
        check_params={"path": "answer"},
        evidence_bindings=(__import__("agent_os_contracts").EvidenceBinding(
            binding_id="bind:1",
            source_type="TOOL_RESPONSE",
            source_selector="assistant",
            extract_path="answer",
            relation="test",
        ),),
        confidence=0.9,
        falsifiable=True,
        blocking=True,
        source="test",
    )
    ps = PredicateSet(
        set_id="set:test",
        contract_id="contract:test",
        task_id="task-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        predicates=(minimal_pred,),
        frozen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    registry = default_registry()
    evaluator = registry.get(PREDICATE_CONJUNCTION_TYPE)
    assert evaluator is not None
    evaluator._store.save(ps)  # type: ignore[attr-defined]

    expected = ExpectedOutcome(
        expected_outcome_id="expected:1",
        task_id="task-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        evaluator_type=PREDICATE_CONJUNCTION_TYPE,
        evaluator_version=ps.content_key(),
        evidence_requirements=("predicate-set",),
        failure_semantics=("blocking predicate failed",),
        threshold=1.0,
        frozen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        observation_window_seconds=3600,
    )

    fake_verified = ObservedOutcome(
        observed_outcome_id="observed:fake",
        expected_outcome_id=expected.expected_outcome_id,
        task_id="task-1",
        run_id="run-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        evaluator_type=PREDICATE_CONJUNCTION_TYPE,
        evaluator_version="1",
        status=OutcomeStatus.VERIFIED,
        score=1.0,
        confidence=1.0,
        evidence_refs=("predicate-set:" + ps.content_key(),),
        unresolved_gaps=(),
        observed_at=datetime(2026, 1, 1, second=30, tzinfo=timezone.utc),
    )

    with pytest.raises(InvalidTransitionError, match="accessor"):
        evaluator.verify_verified_recording(
            expected,
            fake_verified,
            report_resolver=lambda *a: None,  # type: ignore[arg-type]
            now=datetime(2026, 1, 1, second=30, tzinfo=timezone.utc),
        )
