"""RED bypass tests for the arm-neutral SRL E2E falsifier contracts.

These tests are written before ``product_evals/srl_e2e_falsifier/contracts.py``
exists.  They attack digest forgery, kind/field smuggling, non-strict
``no_external_effect`` coercion, forbidden public-state keys (including nested
raw mappings), remaining-budget leakage into public state, arm-label influence
on canonical public-state bytes, unknown/extra fields, non-canonical digests
and authority/effect boolean smuggling.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from pydantic import ValidationError

from agent_os_contracts import canonical_json, content_digest
from product_evals.srl_e2e_falsifier.contracts import (
    BudgetFeedback,
    CandidateKind,
    ControllerBindingReceipt,
    DecisionCandidate,
    MissingInputKind,
    PublicResponsibilityState,
    StaticBudgetConfiguration,
    decision_candidate_digest,
)


def _digest_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


STATE_DIGEST = _digest_of("public-state")
TRIGGER_DIGEST = _digest_of("trigger")
CONTROLLER_DIGEST = _digest_of("controller")
PROMPT_DIGEST = _digest_of("prompt")
MODEL_DIGEST = _digest_of("model")
TOOL_DIGEST = _digest_of("tool-catalog")
BUDGET_DIGEST = _digest_of("budget-configuration")
MANDATE_DIGEST = _digest_of("mandate")
BINDING_DIGEST = _digest_of("environment-binding")
CONTENT_DIGEST = _digest_of("public-content")
CREATED_AT = "2026-07-17T00:00:00Z"


def _work_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "candidate_id": "cand-work-001",
        "candidate_kind": "WORK",
        "public_state_digest": STATE_DIGEST,
        "no_external_effect": True,
        "desired_outcome": "restore the failing canonical-lib test to green",
        "acceptance_criteria": ("pytest exit code is 0",),
        "missing_input_kind": None,
        "minimum_question": None,
        "created_at": CREATED_AT,
    }
    payload.update(overrides)
    return payload


def _help_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "candidate_id": "cand-help-001",
        "candidate_kind": "HELP",
        "public_state_digest": STATE_DIGEST,
        "no_external_effect": True,
        "desired_outcome": None,
        "acceptance_criteria": (),
        "missing_input_kind": "INFORMATION",
        "minimum_question": "which interface revision is authoritative?",
        "created_at": CREATED_AT,
    }
    payload.update(overrides)
    return payload


def _none_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "candidate_id": "cand-none-001",
        "candidate_kind": "NONE",
        "public_state_digest": STATE_DIGEST,
        "no_external_effect": True,
        "desired_outcome": None,
        "acceptance_criteria": (),
        "missing_input_kind": None,
        "minimum_question": None,
        "created_at": CREATED_AT,
    }
    payload.update(overrides)
    return payload


def _sealed(payload: dict[str, Any]) -> DecisionCandidate:
    return DecisionCandidate.model_validate(
        {**payload, "candidate_digest": content_digest(payload)}
    )


def _budget_configuration() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "max_llm_calls": 40,
        "max_input_tokens": 200_000,
        "max_output_tokens": 50_000,
        "max_retries": 4,
        "max_tool_invocations": 60,
        "max_wall_seconds": 3_600,
    }


def _state_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "state_id": "state-001",
        "mandate_digest": MANDATE_DIGEST,
        "mission_statement": "keep the canonical-lib test suite healthy",
        "environment_binding_digest": BINDING_DIGEST,
        "correction_epoch": 0,
        "public_events": (
            {
                "schema_version": "1.0",
                "event_id": "event-001",
                "payload": {
                    "summary": "one test started failing",
                    "details": {"path": "tests/test_core.py"},
                },
                "content_ref": None,
            },
        ),
        "public_projections": (
            {
                "schema_version": "1.0",
                "projection_id": "projection-001",
                "payload": None,
                "content_ref": {
                    "schema_version": "1.0",
                    "content_digest": CONTENT_DIGEST,
                    "media_type": "application/json",
                },
            },
        ),
        "public_evidence_ids": ("evidence-001",),
        "budget_configuration": _budget_configuration(),
    }
    payload.update(overrides)
    return payload


def _receipt_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "receipt_id": "receipt-001",
        "public_state_digest": STATE_DIGEST,
        "controller_digest": CONTROLLER_DIGEST,
        "prompt_digest": PROMPT_DIGEST,
        "model_digest": MODEL_DIGEST,
        "tool_catalog_digest": TOOL_DIGEST,
        "budget_configuration_digest": BUDGET_DIGEST,
        "trigger_digest": TRIGGER_DIGEST,
        "candidate_digest": _digest_of("candidate"),
        "bound_at": CREATED_AT,
    }
    payload.update(overrides)
    return payload


class TestClosedVocabularies:
    def test_candidate_kind_is_closed(self) -> None:
        assert {item.value for item in CandidateKind} == {"WORK", "HELP", "NONE"}
        with pytest.raises(ValueError):
            CandidateKind("EXECUTE")

    def test_missing_input_kind_is_closed(self) -> None:
        assert {item.value for item in MissingInputKind} == {
            "INFORMATION",
            "PERMISSION",
            "VALUE_TRADE_OFF",
            "AUTHORITY_CONFLICT",
            "IRREVERSIBLE_RISK",
        }
        with pytest.raises(ValueError):
            MissingInputKind("VIBES")

    def test_unknown_candidate_kind_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _sealed(_work_payload(candidate_kind="EXECUTE"))

    def test_unknown_missing_input_kind_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _sealed(_help_payload(missing_input_kind="VIBES"))


class TestCandidateDigest:
    def test_valid_work_candidate_seals(self) -> None:
        candidate = _sealed(_work_payload())
        assert candidate.candidate_kind is CandidateKind.WORK
        assert candidate.candidate_digest == content_digest(_work_payload())

    def test_forged_digest_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DecisionCandidate.model_validate(
                {**_work_payload(), "candidate_digest": _digest_of("forged")}
            )

    def test_digest_of_other_candidate_rejected(self) -> None:
        other_digest = content_digest(_help_payload())
        with pytest.raises(ValidationError):
            DecisionCandidate.model_validate(
                {**_work_payload(), "candidate_digest": other_digest}
            )

    @pytest.mark.parametrize(
        ("base", "field", "value"),
        [
            (_work_payload, "candidate_id", "cand-work-002"),
            (_work_payload, "candidate_kind", "NONE"),
            (_work_payload, "public_state_digest", _digest_of("other-state")),
            (
                _work_payload,
                "desired_outcome",
                "silently rewrite the assertion instead",
            ),
            (
                _work_payload,
                "acceptance_criteria",
                ("pytest exit code is 0", "no new failures"),
            ),
            (_work_payload, "created_at", "2026-07-18T00:00:00Z"),
            (_help_payload, "missing_input_kind", "PERMISSION"),
            (_help_payload, "minimum_question", "may I delete the flaky test?"),
        ],
    )
    def test_every_field_mutation_invalidates_digest(
        self, base: Any, field: str, value: Any
    ) -> None:
        original_digest = content_digest(base())
        mutated = base(**{field: value})
        assert content_digest(mutated) != original_digest
        with pytest.raises(ValidationError):
            DecisionCandidate.model_validate(
                {**mutated, "candidate_digest": original_digest}
            )

    def test_digest_payload_must_exclude_itself(self) -> None:
        payload = _work_payload()
        payload["candidate_digest"] = content_digest(_work_payload())
        with pytest.raises(ValueError):
            decision_candidate_digest(payload)

    def test_non_canonical_digest_rejected(self) -> None:
        payload = _work_payload()
        pretty = json.dumps(
            _sealed(payload).model_dump(mode="json", exclude={"candidate_digest"}),
            indent=2,
            sort_keys=True,
        )
        non_canonical = hashlib.sha256(pretty.encode("utf-8")).hexdigest()
        assert non_canonical != content_digest(payload)
        with pytest.raises(ValidationError):
            DecisionCandidate.model_validate(
                {**payload, "candidate_digest": non_canonical}
            )

    def test_uppercase_digest_rejected(self) -> None:
        payload = _work_payload()
        with pytest.raises(ValidationError):
            DecisionCandidate.model_validate(
                {**payload, "candidate_digest": content_digest(payload).upper()}
            )

    def test_extra_field_rejected(self) -> None:
        payload = _work_payload()
        with pytest.raises(ValidationError):
            DecisionCandidate.model_validate(
                {
                    **payload,
                    "candidate_digest": content_digest(payload),
                    "arm_id": "arm-3",
                }
            )


class TestKindFieldCombinations:
    def test_work_requires_desired_outcome(self) -> None:
        with pytest.raises(ValidationError):
            _sealed(_work_payload(desired_outcome=None))

    def test_work_requires_non_blank_desired_outcome(self) -> None:
        with pytest.raises(ValidationError):
            _sealed(_work_payload(desired_outcome="   "))

    def test_work_requires_acceptance_criteria(self) -> None:
        with pytest.raises(ValidationError):
            _sealed(_work_payload(acceptance_criteria=()))

    def test_work_rejects_blank_acceptance_criterion(self) -> None:
        with pytest.raises(ValidationError):
            _sealed(_work_payload(acceptance_criteria=("",)))

    def test_work_forbids_missing_input_kind(self) -> None:
        with pytest.raises(ValidationError):
            _sealed(_work_payload(missing_input_kind="INFORMATION"))

    def test_work_forbids_minimum_question(self) -> None:
        with pytest.raises(ValidationError):
            _sealed(_work_payload(minimum_question="which revision?"))

    def test_help_requires_missing_input_kind(self) -> None:
        with pytest.raises(ValidationError):
            _sealed(_help_payload(missing_input_kind=None))

    def test_help_requires_minimum_question(self) -> None:
        with pytest.raises(ValidationError):
            _sealed(_help_payload(minimum_question=None))

    def test_help_requires_non_blank_minimum_question(self) -> None:
        with pytest.raises(ValidationError):
            _sealed(_help_payload(minimum_question=" "))

    def test_help_forbids_desired_outcome(self) -> None:
        with pytest.raises(ValidationError):
            _sealed(_help_payload(desired_outcome="also fix the test"))

    def test_help_forbids_acceptance_criteria(self) -> None:
        with pytest.raises(ValidationError):
            _sealed(_help_payload(acceptance_criteria=("tests pass",)))

    def test_none_forbids_work_fields(self) -> None:
        with pytest.raises(ValidationError):
            _sealed(_none_payload(desired_outcome="do something"))
        with pytest.raises(ValidationError):
            _sealed(_none_payload(acceptance_criteria=("done",)))

    def test_none_forbids_help_fields(self) -> None:
        with pytest.raises(ValidationError):
            _sealed(_none_payload(missing_input_kind="PERMISSION"))
        with pytest.raises(ValidationError):
            _sealed(_none_payload(minimum_question="may I?"))

    def test_valid_help_and_none_candidates_seal(self) -> None:
        assert _sealed(_help_payload()).candidate_kind is CandidateKind.HELP
        assert _sealed(_none_payload()).candidate_kind is CandidateKind.NONE


class TestNoExternalEffectStrictness:
    def test_false_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _sealed(_work_payload(no_external_effect=False))

    def test_integer_one_rejected_before_coercion(self) -> None:
        with pytest.raises(ValidationError):
            _sealed(_work_payload(no_external_effect=1))

    def test_string_true_rejected_before_coercion(self) -> None:
        for smuggled in ("true", "True", "1", "yes"):
            with pytest.raises(ValidationError):
                _sealed(_work_payload(no_external_effect=smuggled))

    def test_zero_and_none_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _sealed(_work_payload(no_external_effect=0))
        with pytest.raises(ValidationError):
            _sealed(_work_payload(no_external_effect=None))


class TestPublicResponsibilityState:
    def test_valid_state_constructs(self) -> None:
        state = PublicResponsibilityState(**_state_payload())
        assert state.correction_epoch == 0
        assert state.state_digest() == content_digest(state)

    def test_forbidden_top_level_keys_rejected(self) -> None:
        for key, value in (
            ("arm_id", "arm-3"),
            ("remaining_llm_calls", 5),
            ("task_class", "TEST_FIXED"),
            ("plugin", "test_fixed_plugin"),
            ("expected_answer", "42"),
            ("source_identity", "operator-1"),
            ("hcw_minutes", 12),
            ("transcript", ("turn-1",)),
            ("internal_state", {"beliefs": ()}),
        ):
            with pytest.raises(ValidationError):
                PublicResponsibilityState.model_validate(
                    {**_state_payload(), key: value}
                )

    @pytest.mark.parametrize(
        "nested_payload",
        [
            {"summary": "ok", "arm_id": "arm-3"},
            {"details": {"arm_id": "arm-1"}},
            {"details": {"deep": {"remaining_wall_seconds": 30}}},
            {"task_class": "TEST_FIXED"},
            {"scoring": {"plugin": "decoy_plugin"}},
            {"expected_answer": "the hidden target"},
            {"expected_outcome": {"disposition": "VERIFIED"}},
            {"source_identity": "unit-author"},
            {"hcw": {"minutes": 3}},
            {"transcript": ["operator: hello"]},
            {"internal_state": {"commitments": []}},
            {"wrapped": [{"arm_id": "arm-2"}]},
        ],
    )
    def test_forbidden_nested_raw_mapping_keys_rejected(
        self, nested_payload: dict[str, Any]
    ) -> None:
        event = {
            "schema_version": "1.0",
            "event_id": "event-002",
            "payload": nested_payload,
            "content_ref": None,
        }
        with pytest.raises(ValidationError):
            PublicResponsibilityState(**_state_payload(public_events=(event,)))

    def test_forbidden_nested_projection_payload_rejected(self) -> None:
        projection = {
            "schema_version": "1.0",
            "projection_id": "projection-002",
            "payload": {"remaining_llm_calls": 7},
            "content_ref": None,
        }
        with pytest.raises(ValidationError):
            PublicResponsibilityState(
                **_state_payload(public_projections=(projection,))
            )

    def test_event_requires_exactly_one_of_payload_or_content_ref(self) -> None:
        empty = {
            "schema_version": "1.0",
            "event_id": "event-003",
            "payload": None,
            "content_ref": None,
        }
        with pytest.raises(ValidationError):
            PublicResponsibilityState(**_state_payload(public_events=(empty,)))
        both = {
            "schema_version": "1.0",
            "event_id": "event-004",
            "payload": {"summary": "ok"},
            "content_ref": {
                "schema_version": "1.0",
                "content_digest": CONTENT_DIGEST,
                "media_type": "application/json",
            },
        }
        with pytest.raises(ValidationError):
            PublicResponsibilityState(**_state_payload(public_events=(both,)))

    def test_remaining_budget_cannot_enter_public_state(self) -> None:
        budget = _budget_configuration()
        budget["remaining_llm_calls"] = 12
        with pytest.raises(ValidationError):
            PublicResponsibilityState(**_state_payload(budget_configuration=budget))
        with pytest.raises(ValidationError):
            PublicResponsibilityState.model_validate(
                {
                    **_state_payload(),
                    "budget_feedback": {"remaining_llm_calls": 12},
                }
            )

    def test_budget_feedback_dump_cannot_enter_public_event(self) -> None:
        feedback = BudgetFeedback.model_validate(
            {
                "feedback_id": "feedback-001",
                "budget_configuration_digest": BUDGET_DIGEST,
                "remaining_llm_calls": 3,
                "remaining_input_tokens": 1000,
                "remaining_output_tokens": 500,
                "remaining_retries": 1,
                "remaining_tool_invocations": 9,
                "remaining_wall_seconds": 120,
                "issued_at": CREATED_AT,
            }
        )
        event = {
            "schema_version": "1.0",
            "event_id": "event-005",
            "payload": {"feedback": feedback.model_dump(mode="json")},
            "content_ref": None,
        }
        with pytest.raises(ValidationError):
            PublicResponsibilityState(**_state_payload(public_events=(event,)))

    def test_three_arm_labels_cannot_alter_canonical_bytes(self) -> None:
        states = [
            PublicResponsibilityState(**_state_payload())
            for _arm_label in ("arm-1-scheduled", "arm-2-user-driven", "arm-3-srl")
        ]
        canonical = {canonical_json(state) for state in states}
        assert len(canonical) == 1
        digests = {state.state_digest() for state in states}
        assert len(digests) == 1
        for arm_label in ("arm-1-scheduled", "arm-2-user-driven", "arm-3-srl"):
            with pytest.raises(ValidationError):
                PublicResponsibilityState.model_validate(
                    {**_state_payload(), "arm_id": arm_label}
                )
            event = {
                "schema_version": "1.0",
                "event_id": "event-006",
                "payload": {"metadata": {"arm_id": arm_label}},
                "content_ref": None,
            }
            with pytest.raises(ValidationError):
                PublicResponsibilityState(**_state_payload(public_events=(event,)))

    def test_static_budget_configuration_is_closed(self) -> None:
        with pytest.raises(ValidationError):
            StaticBudgetConfiguration.model_validate(
                {**_budget_configuration(), "remaining_llm_calls": 1}
            )
        with pytest.raises(ValidationError):
            StaticBudgetConfiguration.model_validate(
                {**_budget_configuration(), "arm_id": "arm-3"}
            )


class TestBudgetFeedback:
    def test_valid_feedback_constructs(self) -> None:
        feedback = BudgetFeedback.model_validate(
            {
                "feedback_id": "feedback-002",
                "budget_configuration_digest": BUDGET_DIGEST,
                "remaining_llm_calls": 0,
                "remaining_input_tokens": 0,
                "remaining_output_tokens": 0,
                "remaining_retries": 0,
                "remaining_tool_invocations": 0,
                "remaining_wall_seconds": 0,
                "issued_at": CREATED_AT,
            }
        )
        assert feedback.remaining_llm_calls == 0

    def test_feedback_is_arm_neutral(self) -> None:
        with pytest.raises(ValidationError):
            BudgetFeedback.model_validate(
                {
                    "feedback_id": "feedback-003",
                    "budget_configuration_digest": BUDGET_DIGEST,
                    "remaining_llm_calls": 1,
                    "remaining_input_tokens": 1,
                    "remaining_output_tokens": 1,
                    "remaining_retries": 1,
                    "remaining_tool_invocations": 1,
                    "remaining_wall_seconds": 1,
                    "issued_at": CREATED_AT,
                    "arm_id": "arm-3",
                }
            )

    def test_negative_remaining_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BudgetFeedback.model_validate(
                {
                    "feedback_id": "feedback-004",
                    "budget_configuration_digest": BUDGET_DIGEST,
                    "remaining_llm_calls": -1,
                    "remaining_input_tokens": 1,
                    "remaining_output_tokens": 1,
                    "remaining_retries": 1,
                    "remaining_tool_invocations": 1,
                    "remaining_wall_seconds": 1,
                    "issued_at": CREATED_AT,
                }
            )

    def test_feedback_is_not_a_public_state_field(self) -> None:
        assert "budget_feedback" not in PublicResponsibilityState.model_fields
        assert not any(
            "remaining" in name
            for name in PublicResponsibilityState.model_fields
        )
        assert not any(
            "remaining" in name
            for name in StaticBudgetConfiguration.model_fields
        )


class TestControllerBindingReceipt:
    def test_valid_receipt_constructs(self) -> None:
        receipt = ControllerBindingReceipt(**_receipt_payload())
        assert receipt.authority_granted is False
        assert receipt.external_effects_authorized is False

    def test_receipt_binds_exact_digests(self) -> None:
        receipt = ControllerBindingReceipt(**_receipt_payload())
        assert receipt.public_state_digest == STATE_DIGEST
        assert receipt.controller_digest == CONTROLLER_DIGEST
        assert receipt.prompt_digest == PROMPT_DIGEST
        assert receipt.model_digest == MODEL_DIGEST
        assert receipt.tool_catalog_digest == TOOL_DIGEST
        assert receipt.budget_configuration_digest == BUDGET_DIGEST
        assert receipt.trigger_digest == TRIGGER_DIGEST

    def test_missing_binding_digest_rejected(self) -> None:
        for field in (
            "public_state_digest",
            "controller_digest",
            "prompt_digest",
            "model_digest",
            "tool_catalog_digest",
            "budget_configuration_digest",
            "trigger_digest",
            "candidate_digest",
        ):
            payload = _receipt_payload()
            del payload[field]
            with pytest.raises(ValidationError):
                ControllerBindingReceipt(**payload)

    def test_authority_boolean_cannot_be_smuggled(self) -> None:
        for value in (True, 1, "true", "1", None):
            with pytest.raises(ValidationError):
                ControllerBindingReceipt.model_validate(
                    {**_receipt_payload(), "authority_granted": value}
                )

    def test_effect_boolean_cannot_be_smuggled(self) -> None:
        for value in (True, 1, "true", "1", None):
            with pytest.raises(ValidationError):
                ControllerBindingReceipt.model_validate(
                    {**_receipt_payload(), "external_effects_authorized": value}
                )

    def test_zero_is_not_literal_false(self) -> None:
        with pytest.raises(ValidationError):
            ControllerBindingReceipt.model_validate(
                {**_receipt_payload(), "authority_granted": 0}
            )
        with pytest.raises(ValidationError):
            ControllerBindingReceipt.model_validate(
                {**_receipt_payload(), "external_effects_authorized": 0}
            )

    def test_extra_authority_like_fields_rejected(self) -> None:
        for key in (
            "effects_allowed",
            "authority",
            "can_execute",
            "external_effects",
        ):
            with pytest.raises(ValidationError):
                ControllerBindingReceipt.model_validate(
                    {**_receipt_payload(), key: True}
                )

    def test_receipt_grants_no_authority_fields(self) -> None:
        fields = ControllerBindingReceipt.model_fields
        assert fields["authority_granted"].default is False
        assert fields["external_effects_authorized"].default is False
