"""Tests for contract inference types (spec §4, §12).

Step 1 of implementation-cast: type definitions only.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    ALLOWED_META_TEMPLATES,
    CHECK_TYPE_REQUIRED_PARAMS,
    CheckType,
    ClarificationQuestion,
    EvidenceBinding,
    EvidenceSourceType,
    InferredTaskContract,
    PredicateConfirmation,
    PredicateKind,
    PredicateSet,
    QualityGateResult,
    SuccessPredicate,
    TypedPredicateCorrection,
    derive_contract_id,
    derive_predicate_id,
)


def _binding(
    binding_id: str = "bind:1",
    source_type: EvidenceSourceType = EvidenceSourceType.TOOL_RESPONSE,
    source_selector: str = "send_email:last",
    extract_path: str | None = "$.status_code",
    relation: str = "email send returned 200",
) -> EvidenceBinding:
    return EvidenceBinding(
        binding_id=binding_id,
        source_type=source_type,
        source_selector=source_selector,
        extract_path=extract_path,
        relation=relation,
    )


def _predicate(
    predicate_id: str = "pred:abc123",
    kind: PredicateKind = PredicateKind.STRUCTURAL,
    description: str = "send_email returns status 200",
    check_type: CheckType = CheckType.TOOL_RESPONSE,
    check_params: dict | None = None,
    evidence_bindings: tuple[EvidenceBinding, ...] | None = None,
    blocking: bool = True,
    confidence: float = 1.0,
    source: str = "mechanical:tool_response_schema",
    falsifiable: bool = True,
    meta_template: str | None = None,
    scope_tags: tuple[str, ...] = (),
) -> SuccessPredicate:
    return SuccessPredicate(
        predicate_id=predicate_id,
        kind=kind,
        description=description,
        check_type=check_type,
        check_params=check_params
        or {"tool_name": "send_email", "condition": {"$.status_code": 200}},
        evidence_bindings=evidence_bindings or (_binding(),),
        blocking=blocking,
        confidence=confidence,
        source=source,
        falsifiable=falsifiable,
        meta_template=meta_template,
        scope_tags=scope_tags,
    )


# ---------------------------------------------------------------------------
# SuccessPredicate
# ---------------------------------------------------------------------------


class TestSuccessPredicate:
    def test_frozen(self) -> None:
        p = _predicate()
        with pytest.raises(ValidationError):
            p.blocking = False  # type: ignore[misc]

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            SuccessPredicate(
                predicate_id="pred:x",
                kind=PredicateKind.STRUCTURAL,
                description="d",
                check_type=CheckType.TYPE,
                check_params={"field": "$.x", "expected_type": "string"},
                evidence_bindings=(_binding(),),
                confidence=1.0,
                source="mechanical:test",
                unknown_field=1,  # type: ignore[call-arg]
            )

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            _predicate(confidence=1.5)
        with pytest.raises(ValidationError):
            _predicate(confidence=-0.1)

    def test_requires_evidence_binding(self) -> None:
        with pytest.raises(ValidationError):
            SuccessPredicate(
                predicate_id="pred:x",
                kind=PredicateKind.STRUCTURAL,
                description="d",
                check_type=CheckType.TYPE,
                check_params={"field": "$.x", "expected_type": "string"},
                evidence_bindings=(),
                confidence=1.0,
                source="mechanical:test",
            )

    def test_meta_template_valid(self) -> None:
        for mt in ALLOWED_META_TEMPLATES:
            p = _predicate(meta_template=mt)
            assert p.meta_template == mt

    def test_meta_template_invalid(self) -> None:
        with pytest.raises(ValidationError):
            _predicate(meta_template="not_a_template")

    def test_meta_template_none_allowed(self) -> None:
        p = _predicate(meta_template=None)
        assert p.meta_template is None


# ---------------------------------------------------------------------------
# derive_predicate_id
# ---------------------------------------------------------------------------


class TestDerivePredicateId:
    def test_stable_for_same_input(self) -> None:
        args = (
            PredicateKind.STRUCTURAL,
            CheckType.TOOL_RESPONSE,
            {"tool_name": "send_email", "condition": {"$.status_code": 200}},
            (_binding(),),
        )
        assert derive_predicate_id(*args) == derive_predicate_id(*args)

    def test_changes_when_params_change(self) -> None:
        bindings = (_binding(),)
        id1 = derive_predicate_id(
            PredicateKind.STRUCTURAL,
            CheckType.TOOL_RESPONSE,
            {"tool_name": "send_email", "condition": {"$.status_code": 200}},
            bindings,
        )
        id2 = derive_predicate_id(
            PredicateKind.STRUCTURAL,
            CheckType.TOOL_RESPONSE,
            {"tool_name": "send_email", "condition": {"$.status_code": 201}},
            bindings,
        )
        assert id1 != id2

    def test_changes_when_bindings_change(self) -> None:
        params = {"tool_name": "send_email", "condition": {"$.status_code": 200}}
        id1 = derive_predicate_id(
            PredicateKind.STRUCTURAL, CheckType.TOOL_RESPONSE, params, (_binding(),)
        )
        id2 = derive_predicate_id(
            PredicateKind.STRUCTURAL,
            CheckType.TOOL_RESPONSE,
            params,
            (_binding(extract_path="$.body.id"),),
        )
        assert id1 != id2

    def test_prefix(self) -> None:
        pid = derive_predicate_id(
            PredicateKind.SEMANTIC,
            CheckType.TYPE,
            {"field": "$.x", "expected_type": "string"},
            (_binding(),),
        )
        assert pid.startswith("pred:")
        assert len(pid) == len("pred:") + 12


# ---------------------------------------------------------------------------
# CHECK_TYPE_REQUIRED_PARAMS
# ---------------------------------------------------------------------------


class TestCheckTypeParams:
    def test_covers_all_check_types(self) -> None:
        for ct in CheckType:
            assert ct in CHECK_TYPE_REQUIRED_PARAMS, f"missing {ct}"

    def test_all_params_non_empty(self) -> None:
        for ct, params in CHECK_TYPE_REQUIRED_PARAMS.items():
            assert len(params) > 0, f"{ct} has no required params"


# ---------------------------------------------------------------------------
# EvidenceBinding
# ---------------------------------------------------------------------------


class TestEvidenceBinding:
    def test_extract_path_optional(self) -> None:
        b = EvidenceBinding(
            binding_id="bind:1",
            source_type=EvidenceSourceType.ARTIFACT,
            source_selector="deliverables/report.json",
            extract_path=None,
            relation="report file exists",
        )
        assert b.extract_path is None


# ---------------------------------------------------------------------------
# ClarificationQuestion
# ---------------------------------------------------------------------------


class TestClarificationQuestion:
    def test_choice_requires_options(self) -> None:
        with pytest.raises(ValidationError):
            ClarificationQuestion(
                question_id="q1",
                predicate_id="pred:x",
                question="Pick one",
                question_type="choice",
                options=(),
            )

    def test_choice_with_options_ok(self) -> None:
        q = ClarificationQuestion(
            question_id="q1",
            predicate_id="pred:x",
            question="Pick one",
            question_type="choice",
            options=("a", "b"),
        )
        assert q.options == ("a", "b")

    def test_yes_no_no_options_required(self) -> None:
        q = ClarificationQuestion(
            question_id="q1",
            predicate_id="pred:x",
            question="Should X?",
            question_type="yes_no",
        )
        assert q.options == ()


# ---------------------------------------------------------------------------
# PredicateConfirmation
# ---------------------------------------------------------------------------


class TestPredicateConfirmation:
    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def test_adjust_requires_predicate(self) -> None:
        with pytest.raises(ValidationError):
            PredicateConfirmation(
                predicate_id="pred:x",
                decision="adjust",
                adjusted_predicate=None,
                confirmed_by="op:1",
                confirmed_at=self._now(),
            )

    def test_adjust_with_predicate_ok(self) -> None:
        replacement = _predicate(predicate_id="pred:new")
        c = PredicateConfirmation(
            predicate_id="pred:old",
            decision="adjust",
            adjusted_predicate=replacement,
            confirmed_by="op:1",
            confirmed_at=self._now(),
        )
        assert c.adjusted_predicate is not None
        assert c.adjusted_predicate.predicate_id == "pred:new"

    def test_approve_no_predicate_needed(self) -> None:
        c = PredicateConfirmation(
            predicate_id="pred:x",
            decision="approve",
            adjusted_predicate=None,
            confirmed_by="op:1",
            confirmed_at=self._now(),
        )
        assert c.decision == "approve"

    def test_pre_endorsed_default_false(self) -> None:
        c = PredicateConfirmation(
            predicate_id="pred:x",
            decision="approve",
            confirmed_by="op:1",
            confirmed_at=self._now(),
        )
        assert c.pre_endorsed is False


# ---------------------------------------------------------------------------
# InferredTaskContract
# ---------------------------------------------------------------------------


class TestInferredTaskContract:
    def _contract(self, **kwargs: object) -> InferredTaskContract:
        now = datetime.now(timezone.utc)
        defaults: dict[str, object] = {
            "contract_id": "itc:placeholder",
            "mandate_id": "man:1",
            "mandate_digest": "a" * 64,
            "task_id": "task:1",
            "inferred_at": now,
            "inferrer_version": "contract-inferencer/0.1.0",
            "model_id": "none",
            "deliverable_schema": {"type": "object"},
            "success_predicates": (_predicate(),),
        }
        defaults.update(kwargs)
        return InferredTaskContract(**defaults)  # type: ignore[arg-type]

    def test_requires_at_least_one_predicate(self) -> None:
        with pytest.raises(ValidationError):
            self._contract(success_predicates=())

    def test_contract_digest_changes_with_content(self) -> None:
        c1 = self._contract()
        c2 = self._contract(model_id="llm:test")
        assert c1.contract_digest() != c2.contract_digest()

    def test_derive_contract_id_prefix(self) -> None:
        c = self._contract()
        cid = derive_contract_id(c)
        assert cid.startswith("itc:")


# ---------------------------------------------------------------------------
# QualityGateResult
# ---------------------------------------------------------------------------


class TestQualityGateResult:
    def test_empty_ok(self) -> None:
        r = QualityGateResult()
        assert r.accepted == ()
        assert r.rejected == ()


# ---------------------------------------------------------------------------
# PredicateSet
# ---------------------------------------------------------------------------


class TestPredicateSet:
    def test_content_key_deterministic(self) -> None:
        now = datetime.now(timezone.utc)
        p = _predicate()
        ps1 = PredicateSet(
            set_id="predset:abc",
            contract_id="itc:x",
            task_id="task:1",
            tenant_id="tenant:1",
            workspace_id="ws:1",
            predicates=(p,),
            frozen_at=now,
        )
        ps2 = PredicateSet(
            set_id="predset:abc",
            contract_id="itc:x",
            task_id="task:1",
            tenant_id="tenant:1",
            workspace_id="ws:1",
            predicates=(p,),
            frozen_at=now,
        )
        assert ps1.content_key() == ps2.content_key()

    def test_requires_predicates(self) -> None:
        with pytest.raises(ValidationError):
            PredicateSet(
                set_id="predset:abc",
                contract_id="itc:x",
                task_id="task:1",
                tenant_id="tenant:1",
                workspace_id="ws:1",
                predicates=(),
                frozen_at=datetime.now(timezone.utc),
            )


# ---------------------------------------------------------------------------
# TypedPredicateCorrection
# ---------------------------------------------------------------------------


class TestTypedPredicateCorrection:
    def test_construction(self) -> None:
        c = TypedPredicateCorrection(
            correction_id="corr:1",
            contract_id="itc:x",
            predicate_id="pred:abc",
            predicate_description="send_email returns 200",
            observed_value={"status_code": 429},
            expected_condition={"$.status_code": 200},
            failure_code="CRITERIA_NOT_MET",
            evidence_refs=("artifact:test-report.json",),
            created_at=datetime.now(timezone.utc),
        )
        assert c.failure_code == "CRITERIA_NOT_MET"

    def test_invalid_failure_code(self) -> None:
        with pytest.raises(ValidationError):
            TypedPredicateCorrection(
                correction_id="corr:1",
                contract_id="itc:x",
                predicate_id="pred:abc",
                predicate_description="d",
                observed_value={},
                expected_condition={},
                failure_code="NOT_A_CODE",  # type: ignore[arg-type]
                evidence_refs=(),
                created_at=datetime.now(timezone.utc),
            )
