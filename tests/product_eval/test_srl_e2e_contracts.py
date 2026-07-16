"""RED bypass tests for the arm-neutral SRL E2E falsifier contracts.

These tests are written before ``product_evals/srl_e2e_falsifier/contracts.py``
exists.  They attack digest forgery, kind/field smuggling, non-strict
``no_external_effect`` coercion, remaining-budget leakage into public state,
arm-label influence on canonical public-state bytes, unknown/extra fields,
non-canonical digests, authority/effect boolean smuggling, value-channel
injection, armId/arm-id/zero-width/fullwidth smuggling, renamed-budget
injection, opaque-ref-without-manifest attacks, candidate_kind full-morph
stale-digest attacks, and ControllerBindingReceipt content-digest forgery.
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
MANIFEST_DIGEST = _digest_of("manifest-entry")
MISSION_DIGEST = _digest_of("mission-text")
PROJECTION_DIGEST = _digest_of("projection")
EVIDENCE_DIGEST = _digest_of("evidence")
BUDGET_CONFIG_DIGEST = _digest_of("budget-config-object")
CREATED_AT = "2026-07-17T00:00:00Z"


# ---------------------------------------------------------------------------
# DecisionCandidate helpers (unchanged payload/kind logic)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# PublicResponsibilityState helpers (content-addressed refs only)
# ---------------------------------------------------------------------------


def _content_ref(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "content_digest": CONTENT_DIGEST,
        "content_class": "ARM_NEUTRAL_PUBLIC",
        "media_type": "application/json",
    }
    payload.update(overrides)
    return payload


def _mission_ref(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "manifest_entry_digest": MANIFEST_DIGEST,
        "content_ref": _content_ref(content_digest=MISSION_DIGEST),
    }
    payload.update(overrides)
    return payload


def _event_ref(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "event_id": "event-001",
        "manifest_entry_digest": MANIFEST_DIGEST,
        "content_ref": _content_ref(),
    }
    payload.update(overrides)
    return payload


def _projection_ref(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "projection_id": "projection-001",
        "manifest_entry_digest": MANIFEST_DIGEST,
        "content_ref": _content_ref(content_digest=PROJECTION_DIGEST),
    }
    payload.update(overrides)
    return payload


def _evidence_ref(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "evidence_id": "evidence-001",
        "manifest_entry_digest": MANIFEST_DIGEST,
        "content_ref": _content_ref(content_digest=EVIDENCE_DIGEST),
    }
    payload.update(overrides)
    return payload


def _state_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "state_id": "state-001",
        "mandate_digest": MANDATE_DIGEST,
        "mission_ref": _mission_ref(),
        "environment_binding_digest": BINDING_DIGEST,
        "correction_epoch": 0,
        "public_events": (_event_ref(),),
        "public_projections": (_projection_ref(),),
        "public_evidence": (_evidence_ref(),),
        "budget_configuration_digest": BUDGET_CONFIG_DIGEST,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ControllerBindingReceipt helpers
# ---------------------------------------------------------------------------


def _receipt_content_fields(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "public_state_digest": STATE_DIGEST,
        "controller_digest": CONTROLLER_DIGEST,
        "prompt_digest": PROMPT_DIGEST,
        "model_digest": MODEL_DIGEST,
        "tool_catalog_digest": TOOL_DIGEST,
        "budget_configuration_digest": BUDGET_DIGEST,
        "trigger_digest": TRIGGER_DIGEST,
        "candidate_digest": _digest_of("candidate"),
        "bound_at": CREATED_AT,
        "authority_granted": False,
        "external_effects_authorized": False,
    }
    payload.update(overrides)
    return payload


def _receipt_payload(**overrides: Any) -> dict[str, Any]:
    content_fields = _receipt_content_fields()
    digest = content_digest(content_fields)
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "receipt_id": f"controller-binding:{digest}",
        **content_fields,
        "content_digest": digest,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


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

    def test_no_raw_payload_fields_exist(self) -> None:
        """State fields carry only digests and closed refs, zero raw payload."""
        fields = PublicResponsibilityState.model_fields
        for name in ("public_events", "public_projections", "public_evidence"):
            assert name in fields
        assert "mission_ref" in fields
        assert "budget_configuration_digest" in fields
        assert "mission_statement" not in fields
        assert "payload" not in fields
        assert "budget_configuration" not in fields
        assert "public_evidence_ids" not in fields

    def test_state_cannot_carry_raw_mapping(self) -> None:
        """extra=forbid rejects any free-text or mapping field at top level."""
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
            ("value_channel", "arm-3"),
            ("mission_statement", "a free-text mission"),
            ("payload", {"summary": "something"}),
        ):
            with pytest.raises(ValidationError):
                PublicResponsibilityState.model_validate(
                    {**_state_payload(), key: value}
                )

    def test_value_channel_rejected(self) -> None:
        """value_channel field must not enter public state or any nested ref."""
        with pytest.raises(ValidationError):
            PublicResponsibilityState.model_validate(
                {**_state_payload(), "value_channel": "trade-off-data"}
            )
        with pytest.raises(ValidationError):
            PublicResponsibilityState.model_validate(
                {
                    **_state_payload(),
                    "mission_ref": _mission_ref(value_channel="injected"),
                }
            )
        with pytest.raises(ValidationError):
            PublicResponsibilityState.model_validate(
                {
                    **_state_payload(),
                    "public_events": (
                        {**_event_ref(), "value_channel": "injected"},
                    ),
                }
            )

    @pytest.mark.parametrize(
        "field_name",
        [
            "arm_id",
            "armId",
            "arm-id",
            "arm\u200bid",        # zero-width space
            "arm_id\ufe0f",       # variation selector
            "ａrm_id",            # fullwidth 'a'
            "\uff41rm_id",        # fullwidth 'a' via codepoint
        ],
    )
    def test_arm_id_variants_rejected(self, field_name: str) -> None:
        """arm_id, armId, arm-id, zero-width, fullwidth variants all rejected."""
        with pytest.raises(ValidationError):
            PublicResponsibilityState.model_validate(
                {**_state_payload(), field_name: "arm-3"}
            )

    def test_renamed_budget_rejected(self) -> None:
        """Renamed budget counters (budget_left, tokens_remaining etc) rejected."""
        for key in ("budget_left", "tokens_remaining", "calls_left", "wall_left"):
            with pytest.raises(ValidationError):
                PublicResponsibilityState.model_validate(
                    {**_state_payload(), key: 99}
                )

    def test_static_budget_cannot_enter_public_state(self) -> None:
        """StaticBudgetConfiguration object cannot enter state (digest only)."""
        with pytest.raises(ValidationError):
            PublicResponsibilityState.model_validate(
                {**_state_payload(), "budget_configuration": _digest_of("cfg")}
            )
        budget_obj = {
            "schema_version": "1.0",
            "max_llm_calls": 1,
            "max_input_tokens": 1,
            "max_output_tokens": 1,
            "max_retries": 1,
            "max_tool_invocations": 1,
            "max_wall_seconds": 1,
        }
        with pytest.raises(ValidationError):
            PublicResponsibilityState.model_validate(
                {**_state_payload(), "budget_configuration": budget_obj}
            )
        with pytest.raises(ValidationError):
            PublicResponsibilityState.model_validate(
                {**_state_payload(), "remaining_llm_calls": 12}
            )

    def test_opaque_ref_missing_manifest_rejected(self) -> None:
        """A content ref without manifest_entry_digest cannot enter anywhere."""
        bad_event = {
            "schema_version": "1.0",
            "event_id": "event-bad",
            "content_ref": _content_ref(),
        }
        with pytest.raises(ValidationError):
            PublicResponsibilityState(**_state_payload(public_events=(bad_event,)))
        bad_projection = {
            "schema_version": "1.0",
            "projection_id": "projection-bad",
            "content_ref": _content_ref(),
        }
        with pytest.raises(ValidationError):
            PublicResponsibilityState(
                **_state_payload(public_projections=(bad_projection,))
            )
        bad_evidence = {
            "schema_version": "1.0",
            "evidence_id": "evidence-bad",
            "content_ref": _content_ref(),
        }
        with pytest.raises(ValidationError):
            PublicResponsibilityState(
                **_state_payload(public_evidence=(bad_evidence,))
            )
        bad_mission = {
            "schema_version": "1.0",
            "content_ref": _content_ref(content_digest=MISSION_DIGEST),
        }
        with pytest.raises(ValidationError):
            PublicResponsibilityState(**_state_payload(mission_ref=bad_mission))

    def test_content_ref_missing_class_field_rejected(self) -> None:
        """A ref omitting content_class defaults closed; a ref with a class
        key set to None or empty is rejected."""
        for bad_class in (None, ""):
            with pytest.raises(ValidationError):
                PublicResponsibilityState.model_validate(
                    {
                        **_state_payload(),
                        "public_events": (
                            _event_ref(
                                content_ref=_content_ref(content_class=bad_class)
                            ),
                        ),
                    }
                )

    def test_opaque_ref_wrong_content_class_rejected(self) -> None:
        """content_class must be ARM_NEUTRAL_PUBLIC, nothing else, anywhere."""
        for wrong_class in ("OTHER_CLASS", "ARM_SPECIFIC", "PRIVATE", "arm_neutral_public"):
            wrong_ref = _content_ref(content_class=wrong_class)
            with pytest.raises(ValidationError):
                PublicResponsibilityState.model_validate(
                    {
                        **_state_payload(),
                        "public_events": (_event_ref(content_ref=wrong_ref),),
                    }
                )
            with pytest.raises(ValidationError):
                PublicResponsibilityState.model_validate(
                    {
                        **_state_payload(),
                        "public_projections": (
                            _projection_ref(content_ref=wrong_ref),
                        ),
                    }
                )
            with pytest.raises(ValidationError):
                PublicResponsibilityState.model_validate(
                    {
                        **_state_payload(),
                        "public_evidence": (_evidence_ref(content_ref=wrong_ref),),
                    }
                )
            with pytest.raises(ValidationError):
                PublicResponsibilityState.model_validate(
                    {
                        **_state_payload(),
                        "mission_ref": _mission_ref(content_ref=wrong_ref),
                    }
                )

    @pytest.mark.parametrize(
        "leak_payload",
        [
            {"condition": "arm-3-srl"},
            {"summary": "expected answer: 42"},
            {"note": "calls left: 5"},
        ],
        ids=["arm-condition-value", "expected-answer-value", "calls-left-value"],
    )
    def test_value_leak_via_payload_channel_rejected(
        self, leak_payload: dict[str, Any]
    ) -> None:
        """The removed raw-payload channel cannot be reintroduced to carry
        arm/expected-answer/remaining-budget values on any ref site."""
        with pytest.raises(ValidationError):
            PublicResponsibilityState.model_validate(
                {
                    **_state_payload(),
                    "public_events": (
                        {**_event_ref(), "payload": leak_payload},
                    ),
                }
            )
        with pytest.raises(ValidationError):
            PublicResponsibilityState.model_validate(
                {
                    **_state_payload(),
                    "public_projections": (
                        {**_projection_ref(), "payload": leak_payload},
                    ),
                }
            )
        with pytest.raises(ValidationError):
            PublicResponsibilityState.model_validate(
                {
                    **_state_payload(),
                    "public_evidence": (
                        {**_evidence_ref(), "payload": leak_payload},
                    ),
                }
            )
        with pytest.raises(ValidationError):
            PublicResponsibilityState.model_validate(
                {
                    **_state_payload(),
                    "mission_ref": {**_mission_ref(), "payload": leak_payload},
                }
            )
        with pytest.raises(ValidationError):
            PublicResponsibilityState.model_validate(
                {
                    **_state_payload(),
                    "public_events": (
                        _event_ref(content_ref={**_content_ref(), **leak_payload}),
                    ),
                }
            )

    def test_three_injection_attempts_then_evaluator_owned_refs(self) -> None:
        """Three injection attempts on PublicResponsibilityState all rejected,
        then three distinct evaluator-owned refs construct successfully."""
        # -- injection attempt 1: arm_id at state level --
        with pytest.raises(ValidationError):
            PublicResponsibilityState.model_validate(
                {**_state_payload(), "arm_id": "arm-1-scheduled"}
            )
        # -- injection attempt 2: arm label inside event ref --
        with pytest.raises(ValidationError):
            PublicResponsibilityState.model_validate(
                {
                    **_state_payload(),
                    "public_events": (
                        {
                            "schema_version": "1.0",
                            "event_id": "event-inject",
                            "manifest_entry_digest": MANIFEST_DIGEST,
                            "content_ref": _content_ref(),
                            "arm_label": "arm-3-srl",
                        },
                    ),
                }
            )
        # -- injection attempt 3: arm_id inside content_ref --
        with pytest.raises(ValidationError):
            PublicResponsibilityState.model_validate(
                {
                    **_state_payload(),
                    "public_events": (
                        {
                            "schema_version": "1.0",
                            "event_id": "event-inject2",
                            "manifest_entry_digest": MANIFEST_DIGEST,
                            "content_ref": _content_ref(arm_id="arm-2"),
                        },
                    ),
                }
            )

        # -- evaluator-owned refs: three distinct objects (not same instance) --
        ref_a = _event_ref(event_id="event-eval-a")
        ref_b = _projection_ref(projection_id="projection-eval-b")
        ref_c = _evidence_ref(evidence_id="evidence-eval-c")

        state = PublicResponsibilityState(
            **_state_payload(
                public_events=(ref_a,),
                public_projections=(ref_b,),
                public_evidence=(ref_c,),
                correction_epoch=1,
            )
        )
        assert state.correction_epoch == 1
        assert state.public_events[0].event_id == "event-eval-a"
        assert state.public_projections[0].projection_id == "projection-eval-b"
        assert state.public_evidence[0].evidence_id == "evidence-eval-c"
        digest = state.state_digest()
        assert isinstance(digest, str)
        assert len(digest) == 64

    def test_canonical_bytes_are_arm_neutral(self) -> None:
        """Same state constructed twice with nothing arm-related produces same
        canonical bytes regardless of evaluator identity."""
        s1 = PublicResponsibilityState(**_state_payload())
        s2 = PublicResponsibilityState(**_state_payload())
        assert canonical_json(s1) == canonical_json(s2)
        assert s1.state_digest() == s2.state_digest()

    def test_static_budget_configuration_is_closed(self) -> None:
        with pytest.raises(ValidationError):
            StaticBudgetConfiguration.model_validate(
                {
                    "schema_version": "1.0",
                    "max_llm_calls": 1,
                    "max_input_tokens": 1,
                    "max_output_tokens": 1,
                    "max_retries": 1,
                    "max_tool_invocations": 1,
                    "max_wall_seconds": 1,
                    "remaining_llm_calls": 1,
                }
            )
        with pytest.raises(ValidationError):
            StaticBudgetConfiguration.model_validate(
                {
                    "schema_version": "1.0",
                    "max_llm_calls": 1,
                    "max_input_tokens": 1,
                    "max_output_tokens": 1,
                    "max_retries": 1,
                    "max_tool_invocations": 1,
                    "max_wall_seconds": 1,
                    "arm_id": "arm-3",
                }
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

    def test_receipt_id_matches_content_digest(self) -> None:
        receipt = ControllerBindingReceipt(**_receipt_payload())
        assert receipt.receipt_id == f"controller-binding:{receipt.content_digest}"

    def test_content_digest_matches_canonical_payload(self) -> None:
        receipt = ControllerBindingReceipt(**_receipt_payload())
        payload = receipt.model_dump(
            mode="json", exclude={"receipt_id", "content_digest"}
        )
        assert receipt.content_digest == content_digest(payload)

    def test_forged_content_digest_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ControllerBindingReceipt(
                **_receipt_payload(content_digest=_digest_of("forged"))
            )

    def test_stale_receipt_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ControllerBindingReceipt(
                **_receipt_payload(receipt_id="controller-binding:deadbeef")
            )

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
            "content_digest",
        ):
            payload = _receipt_payload()
            del payload[field]
            with pytest.raises(ValidationError):
                ControllerBindingReceipt(**payload)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("public_state_digest", _digest_of("mutated-state")),
            ("controller_digest", _digest_of("mutated-controller")),
            ("prompt_digest", _digest_of("mutated-prompt")),
            ("model_digest", _digest_of("mutated-model")),
            ("tool_catalog_digest", _digest_of("mutated-tools")),
            ("budget_configuration_digest", _digest_of("mutated-budget")),
            ("trigger_digest", _digest_of("mutated-trigger")),
            ("candidate_digest", _digest_of("mutated-candidate")),
            ("bound_at", "2026-07-18T00:00:00Z"),
        ],
    )
    def test_every_field_mutation_stale_digest_rejected(
        self, field: str, value: Any
    ) -> None:
        """Any content-field mutation carries a stale content_digest and is
        rejected by the integrity validator."""
        original = _receipt_payload()
        mutated = _receipt_payload()
        mutated[field] = value
        assert content_digest(
            _receipt_content_fields(**{field: value})
        ) != original["content_digest"]
        with pytest.raises(ValidationError):
            ControllerBindingReceipt(**mutated)

    def test_authority_booleans_admit_no_mutable_value(self) -> None:
        """Literal[False] fields have exactly one representable value, so no
        stale-digest mutation exists; every other value is rejected outright."""
        for field in ("authority_granted", "external_effects_authorized"):
            for value in (True, 1, 0, "false", None):
                with pytest.raises(ValidationError):
                    ControllerBindingReceipt.model_validate(
                        {**_receipt_payload(), field: value}
                    )

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


class TestCandidateKindMutation:
    """Full-shape WORK↔HELP↔NONE transitions with stale digest."""

    def test_work_to_help_stale_digest_rejected(self) -> None:
        work_digest = content_digest(_work_payload())
        with pytest.raises(ValidationError):
            DecisionCandidate.model_validate(
                {**_help_payload(), "candidate_digest": work_digest}
            )

    def test_help_to_work_stale_digest_rejected(self) -> None:
        help_digest = content_digest(_help_payload())
        with pytest.raises(ValidationError):
            DecisionCandidate.model_validate(
                {**_work_payload(), "candidate_digest": help_digest}
            )

    def test_work_to_none_stale_digest_rejected(self) -> None:
        work_digest = content_digest(_work_payload())
        with pytest.raises(ValidationError):
            DecisionCandidate.model_validate(
                {**_none_payload(), "candidate_digest": work_digest}
            )

    def test_none_to_work_stale_digest_rejected(self) -> None:
        none_digest = content_digest(_none_payload())
        with pytest.raises(ValidationError):
            DecisionCandidate.model_validate(
                {**_work_payload(), "candidate_digest": none_digest}
            )

    def test_help_to_none_stale_digest_rejected(self) -> None:
        help_digest = content_digest(_help_payload())
        with pytest.raises(ValidationError):
            DecisionCandidate.model_validate(
                {**_none_payload(), "candidate_digest": help_digest}
            )

    def test_none_to_help_stale_digest_rejected(self) -> None:
        none_digest = content_digest(_none_payload())
        with pytest.raises(ValidationError):
            DecisionCandidate.model_validate(
                {**_help_payload(), "candidate_digest": none_digest}
            )

    def test_kind_only_change_stale_digest_rejected(self) -> None:
        """Changing only candidate_kind leaving shape invalid + stale digest."""
        work_payload = _work_payload()
        work_digest = content_digest(work_payload)
        bad_payload = dict(work_payload)
        bad_payload["candidate_kind"] = "HELP"
        with pytest.raises(ValidationError):
            DecisionCandidate.model_validate(
                {**bad_payload, "candidate_digest": work_digest}
            )

    def test_each_transition_produces_distinct_digests(self) -> None:
        """WORK/HELP/NONE all produce different canonical digests."""
        w = content_digest(_work_payload())
        h = content_digest(_help_payload())
        n = content_digest(_none_payload())
        assert w != h
        assert h != n
        assert w != n
