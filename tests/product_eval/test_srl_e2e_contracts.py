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
from pydantic import BaseModel, ValidationError

from agent_os_contracts import canonical_json, content_digest
from product_evals.srl_e2e_falsifier.contracts import (
    BudgetFeedback,
    CandidateKind,
    ControllerBindingReceipt,
    DecisionCandidate,
    MissingInputKind,
    PublicContentManifest,
    PublicContentManifestEntry,
    PublicContentMediaType,
    PublicContentRole,
    PublicResponsibilityState,
    PublicResponsibilityStateVerifier,
    StaticBudgetConfiguration,
    decision_candidate_digest,
    public_content_entry_digest,
    public_content_manifest_digest,
    public_responsibility_state_digest,
    static_budget_configuration_bytes,
    static_budget_configuration_digest,
)
from product_evals.srl_e2e_falsifier import contracts as srl_e2e_contracts


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
# PublicResponsibilityState helpers (content-addressed manifest only)
# ---------------------------------------------------------------------------


MISSION_BYTES = b"mission-v1"
EVENT_BYTES = b'{"event":"new failure"}'
PROJECTION_BYTES = b'{"projection":"tests red"}'
EVIDENCE_BYTES = b'{"evidence":"pytest receipt"}'


def _entry(
    role: PublicContentRole,
    raw: bytes,
    *,
    media_type: PublicContentMediaType = PublicContentMediaType.APPLICATION_JSON,
    **overrides: Any,
) -> PublicContentManifestEntry:
    payload: dict[str, Any] = {
        "role": role,
        "media_type": media_type,
        "content_digest": hashlib.sha256(raw).hexdigest(),
    }
    payload["entry_digest"] = public_content_entry_digest(payload)
    payload.update(overrides)
    return PublicContentManifestEntry.model_validate(payload)


def _budget(**overrides: Any) -> StaticBudgetConfiguration:
    payload: dict[str, Any] = {
        "max_llm_calls": 1,
        "max_input_tokens": 100,
        "max_output_tokens": 100,
        "max_retries": 1,
        "max_tool_invocations": 2,
        "max_wall_seconds": 60,
    }
    supplied_digest = overrides.pop("configuration_digest", None)
    payload.update(overrides)
    payload["configuration_digest"] = (
        supplied_digest or static_budget_configuration_digest(payload)
    )
    return StaticBudgetConfiguration.model_validate(payload)


def _manifest_fixture() -> tuple[
    PublicContentManifest,
    dict[str, bytes],
    StaticBudgetConfiguration,
]:
    budget = _budget()
    budget_bytes = static_budget_configuration_bytes(budget)
    entries = (
        _entry(PublicContentRole.MISSION, MISSION_BYTES),
        _entry(PublicContentRole.EVENT, EVENT_BYTES),
        _entry(PublicContentRole.PROJECTION, PROJECTION_BYTES),
        _entry(PublicContentRole.EVIDENCE, EVIDENCE_BYTES),
        _entry(PublicContentRole.STATIC_BUDGET, budget_bytes),
    )
    payload: dict[str, Any] = {"entries": entries}
    payload["manifest_root_digest"] = public_content_manifest_digest(payload)
    manifest = PublicContentManifest.model_validate(payload)
    contents = {
        entry.entry_digest: raw
        for entry, raw in zip(
            entries,
            (MISSION_BYTES, EVENT_BYTES, PROJECTION_BYTES, EVIDENCE_BYTES, budget_bytes),
            strict=True,
        )
    }
    return manifest, contents, budget


def _verified_state() -> PublicResponsibilityState:
    manifest, contents, budget = _manifest_fixture()
    return PublicResponsibilityStateVerifier.build(
        manifest=manifest,
        content_by_entry_digest=contents,
        static_budget_configuration=budget,
        mandate_digest=MANDATE_DIGEST,
        environment_binding_digest=BINDING_DIGEST,
        correction_epoch=0,
        mission_entry_digest=manifest.entries[0].entry_digest,
        event_entry_digests=(manifest.entries[1].entry_digest,),
        projection_entry_digests=(manifest.entries[2].entry_digest,),
        evidence_entry_digests=(manifest.entries[3].entry_digest,),
        static_budget_entry_digest=manifest.entries[4].entry_digest,
    )


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
    def test_trusted_builder_constructs_content_addressed_state(self) -> None:
        state = _verified_state()
        assert state.correction_epoch == 0
        assert state.state_digest == public_responsibility_state_digest(
            state.model_dump(mode="json", exclude={"state_digest"})
        )

    def test_state_has_only_digests_epoch_and_digest_tuples(self) -> None:
        fields = set(PublicResponsibilityState.model_fields)
        assert fields == {
            "schema_version",
            "manifest_root_digest",
            "mandate_digest",
            "environment_binding_digest",
            "correction_epoch",
            "mission_entry_digest",
            "event_entry_digests",
            "projection_entry_digests",
            "evidence_entry_digests",
            "static_budget_entry_digest",
            "state_digest",
        }
        for forbidden in (
            "state_id",
            "event_id",
            "projection_id",
            "evidence_id",
            "mission_statement",
            "media_type",
            "payload",
            "value_channel",
        ):
            assert forbidden not in fields

    def test_self_minted_entry_digest_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _entry(
                PublicContentRole.EVENT,
                EVENT_BYTES,
                entry_digest=_digest_of("self-minted-entry"),
            )

    def test_content_class_or_media_omission_is_not_defaulted(self) -> None:
        payload = {
            "role": "EVENT",
            "content_digest": hashlib.sha256(EVENT_BYTES).hexdigest(),
        }
        payload["entry_digest"] = public_content_entry_digest(payload)
        with pytest.raises(ValidationError):
            PublicContentManifestEntry.model_validate(payload)

    def test_manifest_rejects_self_minted_root_duplicate_and_reorder(self) -> None:
        manifest, _, _ = _manifest_fixture()
        with pytest.raises(ValidationError):
            PublicContentManifest.model_validate(
                {"entries": manifest.entries, "manifest_root_digest": _digest_of("fake")}
            )
        duplicate = (manifest.entries[0], manifest.entries[0])
        payload: dict[str, Any] = {"entries": duplicate}
        payload["manifest_root_digest"] = public_content_manifest_digest(payload)
        with pytest.raises(ValidationError):
            PublicContentManifest.model_validate(payload)
        reordered: dict[str, Any] = {"entries": tuple(reversed(manifest.entries))}
        reordered["manifest_root_digest"] = manifest.manifest_root_digest
        with pytest.raises(ValidationError):
            PublicContentManifest.model_validate(reordered)

    def test_trusted_builder_rejects_wrong_content_bytes_and_missing_entry(self) -> None:
        manifest, contents, budget = _manifest_fixture()
        wrong = dict(contents)
        wrong[manifest.entries[1].entry_digest] = b"different event bytes"
        with pytest.raises(ValueError, match="content bytes"):
            PublicResponsibilityStateVerifier.build(
                manifest=manifest,
                content_by_entry_digest=wrong,
                static_budget_configuration=budget,
                mandate_digest=MANDATE_DIGEST,
                environment_binding_digest=BINDING_DIGEST,
                correction_epoch=0,
                mission_entry_digest=manifest.entries[0].entry_digest,
                event_entry_digests=(manifest.entries[1].entry_digest,),
                projection_entry_digests=(manifest.entries[2].entry_digest,),
                evidence_entry_digests=(manifest.entries[3].entry_digest,),
                static_budget_entry_digest=manifest.entries[4].entry_digest,
            )
        missing = dict(contents)
        del missing[manifest.entries[2].entry_digest]
        with pytest.raises(ValueError, match="missing content bytes"):
            PublicResponsibilityStateVerifier.build(
                manifest=manifest,
                content_by_entry_digest=missing,
                static_budget_configuration=budget,
                mandate_digest=MANDATE_DIGEST,
                environment_binding_digest=BINDING_DIGEST,
                correction_epoch=0,
                mission_entry_digest=manifest.entries[0].entry_digest,
                event_entry_digests=(manifest.entries[1].entry_digest,),
                projection_entry_digests=(manifest.entries[2].entry_digest,),
                evidence_entry_digests=(manifest.entries[3].entry_digest,),
                static_budget_entry_digest=manifest.entries[4].entry_digest,
            )

    def test_wrong_role_and_different_manifest_root_fail_closed(self) -> None:
        manifest, contents, budget = _manifest_fixture()
        state = _verified_state()
        wrong_role_entries = list(manifest.entries)
        wrong_role_entries[1] = _entry(PublicContentRole.EVIDENCE, EVENT_BYTES)
        payload: dict[str, Any] = {"entries": tuple(wrong_role_entries)}
        payload["manifest_root_digest"] = public_content_manifest_digest(payload)
        wrong_manifest = PublicContentManifest.model_validate(payload)
        wrong_contents = dict(contents)
        wrong_contents[wrong_role_entries[1].entry_digest] = EVENT_BYTES
        with pytest.raises(ValueError):
            PublicResponsibilityStateVerifier.build(
                manifest=wrong_manifest,
                content_by_entry_digest=wrong_contents,
                static_budget_configuration=budget,
                mandate_digest=MANDATE_DIGEST,
                environment_binding_digest=BINDING_DIGEST,
                correction_epoch=0,
                mission_entry_digest=wrong_manifest.entries[0].entry_digest,
                event_entry_digests=(wrong_manifest.entries[1].entry_digest,),
                projection_entry_digests=(wrong_manifest.entries[2].entry_digest,),
                evidence_entry_digests=(wrong_manifest.entries[3].entry_digest,),
                static_budget_entry_digest=wrong_manifest.entries[4].entry_digest,
            )
        with pytest.raises(ValueError, match="manifest root"):
            PublicResponsibilityStateVerifier.verify(
                state=state,
                manifest=wrong_manifest,
                content_by_entry_digest=wrong_contents,
                static_budget_configuration=budget,
            )

    def test_random_budget_digest_and_budget_bytes_fail_closed(self) -> None:
        with pytest.raises(ValidationError):
            _budget(configuration_digest=_digest_of("random-budget"))
        manifest, contents, budget = _manifest_fixture()
        wrong_budget = _budget(max_wall_seconds=61)
        with pytest.raises(ValueError, match="static budget"):
            PublicResponsibilityStateVerifier.build(
                manifest=manifest,
                content_by_entry_digest=contents,
                static_budget_configuration=wrong_budget,
                mandate_digest=MANDATE_DIGEST,
                environment_binding_digest=BINDING_DIGEST,
                correction_epoch=0,
                mission_entry_digest=manifest.entries[0].entry_digest,
                event_entry_digests=(manifest.entries[1].entry_digest,),
                projection_entry_digests=(manifest.entries[2].entry_digest,),
                evidence_entry_digests=(manifest.entries[3].entry_digest,),
                static_budget_entry_digest=manifest.entries[4].entry_digest,
            )

    def test_same_manifest_inputs_have_identical_bytes_and_no_arm_parameter(self) -> None:
        first = _verified_state()
        second = _verified_state()
        assert canonical_json(first) == canonical_json(second)
        assert first.state_digest == second.state_digest
        assert "arm" not in PublicResponsibilityStateVerifier.build.__annotations__

    def test_raw_state_is_syntax_only_until_verified(self) -> None:
        state = _verified_state()
        forged_payload = state.model_dump(mode="json", exclude={"state_digest"})
        forged_payload["manifest_root_digest"] = _digest_of("unknown-root")
        forged_payload["state_digest"] = public_responsibility_state_digest(
            forged_payload
        )
        syntactically_valid = PublicResponsibilityState.model_validate(forged_payload)
        manifest, contents, budget = _manifest_fixture()
        with pytest.raises(ValueError, match="manifest root"):
            PublicResponsibilityStateVerifier.verify(
                state=syntactically_valid,
                manifest=manifest,
                content_by_entry_digest=contents,
                static_budget_configuration=budget,
            )

    def test_missing_root_and_forged_state_digest_are_rejected(self) -> None:
        state = _verified_state()
        payload = state.model_dump(mode="json")
        del payload["manifest_root_digest"]
        with pytest.raises(ValidationError):
            PublicResponsibilityState.model_validate(payload)
        with pytest.raises(ValidationError):
            PublicResponsibilityState.model_validate(
                {**state.model_dump(mode="json"), "state_digest": _digest_of("fake")}
            )

    @pytest.mark.parametrize(
        "field_name",
        (
            "event_entry_digests",
            "projection_entry_digests",
            "evidence_entry_digests",
        ),
    )
    def test_raw_state_rejects_duplicate_public_entry_references(
        self, field_name: str
    ) -> None:
        state = _verified_state()
        payload = state.model_dump(mode="json", exclude={"state_digest"})
        entry_digest = payload[field_name][0]
        payload[field_name] = (entry_digest, entry_digest)
        payload["state_digest"] = public_responsibility_state_digest(payload)

        with pytest.raises(ValidationError, match="unique"):
            PublicResponsibilityState.model_validate(payload)

    @pytest.mark.parametrize(
        ("field_name", "builder_argument"),
        (
            ("event_entry_digests", "event_entry_digests"),
            ("projection_entry_digests", "projection_entry_digests"),
            ("evidence_entry_digests", "evidence_entry_digests"),
        ),
    )
    def test_trusted_builder_rejects_duplicate_public_entry_references(
        self, field_name: str, builder_argument: str
    ) -> None:
        manifest, contents, budget = _manifest_fixture()
        indexes = {
            "event_entry_digests": 1,
            "projection_entry_digests": 2,
            "evidence_entry_digests": 3,
        }
        duplicate = manifest.entries[indexes[field_name]].entry_digest
        arguments: dict[str, Any] = {
            "manifest": manifest,
            "content_by_entry_digest": contents,
            "static_budget_configuration": budget,
            "mandate_digest": MANDATE_DIGEST,
            "environment_binding_digest": BINDING_DIGEST,
            "correction_epoch": 0,
            "mission_entry_digest": manifest.entries[0].entry_digest,
            "event_entry_digests": (manifest.entries[1].entry_digest,),
            "projection_entry_digests": (manifest.entries[2].entry_digest,),
            "evidence_entry_digests": (manifest.entries[3].entry_digest,),
            "static_budget_entry_digest": manifest.entries[4].entry_digest,
        }
        arguments[builder_argument] = (duplicate, duplicate)

        with pytest.raises(ValueError, match="unique"):
            PublicResponsibilityStateVerifier.build(**arguments)

    @pytest.mark.parametrize(
        "field_name",
        (
            "event_entry_digests",
            "projection_entry_digests",
            "evidence_entry_digests",
        ),
    )
    def test_verifier_rejects_bypassed_duplicate_public_entry_references(
        self, field_name: str
    ) -> None:
        state = _verified_state()
        payload = state.model_dump(mode="json", exclude={"state_digest"})
        entry_digest = payload[field_name][0]
        payload[field_name] = (entry_digest, entry_digest)
        payload["state_digest"] = public_responsibility_state_digest(payload)
        bypassed = PublicResponsibilityState.model_construct(**payload)
        manifest, contents, budget = _manifest_fixture()

        with pytest.raises(ValueError, match="unique"):
            PublicResponsibilityStateVerifier.verify(
                state=bypassed,
                manifest=manifest,
                content_by_entry_digest=contents,
                static_budget_configuration=budget,
            )

    def test_ic0_digest_helpers_use_mapping_payloads_consistently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        observed_payloads: list[object] = []
        real_content_digest = content_digest

        def recording_content_digest(value: object) -> str:
            observed_payloads.append(value)
            assert isinstance(value, dict)
            assert not isinstance(value, BaseModel)
            return real_content_digest(value)

        monkeypatch.setattr(
            srl_e2e_contracts, "content_digest", recording_content_digest
        )

        _manifest_fixture()
        _verified_state()
        _sealed(_work_payload())
        ControllerBindingReceipt.model_validate(_receipt_payload())

        assert observed_payloads


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

    def test_digest_helper_binds_candidate_kind_in_isolation(self) -> None:
        payload = _work_payload()
        mutated = dict(payload)
        mutated["candidate_kind"] = "HELP"
        assert decision_candidate_digest(payload) != decision_candidate_digest(mutated)
