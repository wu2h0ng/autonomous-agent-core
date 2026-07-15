from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    CandidatePromotionCommand,
    CandidatePromotionDecision,
    CandidatePromotionDisposition,
    CandidatePromotionResult,
    CandidateProvenance,
    CorrectionEpochVector,
    DomainPriorArtifact,
    RepresentationPatch,
    RepresentationPatchOperation,
    RepresentationRelationClass,
    candidate_promotion_decision_digest,
    domain_prior_artifact_digest,
)


NOW = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64
DIGEST_E = "e" * 64


def _epochs(**updates: Any) -> CorrectionEpochVector:
    values: dict[str, Any] = {
        "task_epoch": 1,
        "run_epoch": 2,
        "capability_epoch": 3,
    }
    values.update(updates)
    return CorrectionEpochVector(**values)


def _patch() -> RepresentationPatch:
    return RepresentationPatch(
        operations=(
            RepresentationPatchOperation(
                operation_id="op:company-kind",
                operation="UPSERT",
                assertion_id="assertion:company-kind",
                subject_ref="entity:acme",
                predicate="rdf:type",
                object_ref="type:Company",
                relation_class=RepresentationRelationClass.ASSERTED,
                evidence_refs=("evidence:filing",),
            ),
        )
    )


def _provenance(patch: RepresentationPatch) -> CandidateProvenance:
    return CandidateProvenance(
        source_id="source:filing",
        source_ref="artifact:filing",
        source_type="regulatory-filing",
        source_digest=DIGEST_A,
        accessed_at=NOW,
        effective_at=NOW - timedelta(days=1),
        license_or_terms_id="terms:public-filing",
        permitted_use="analysis",
        redistribution_allowed=False,
        output_patch_digest=patch.patch_digest(),
        expires_at=NOW + timedelta(days=1),
    )


def _command_values() -> dict[str, Any]:
    return {
        "candidate_digest": DIGEST_A,
        "candidate_task_id": "task:candidate",
        "promotion_task_id": "task:promotion",
        "promotion_run_id": "run:promotion",
        "tenant_id": "tenant:1",
        "workspace_id": "workspace:1",
        "expected_evaluation_head_digest": DIGEST_B,
        "expected_parent_promotion_digest": None,
    }


def _decision_payload(**updates: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "schema_version": "1.0",
        "promotion_id": "candidate-promotion:1",
        "promotion_version": 1,
        "payload_digest": DIGEST_C,
        "idempotency_key": DIGEST_D,
        "candidate_digest": DIGEST_A,
        "candidate_task_id": "task:candidate",
        "promotion_task_id": "task:promotion",
        "promotion_run_id": "run:promotion",
        "tenant_id": "tenant:1",
        "workspace_id": "workspace:1",
        "evaluation_head_digest": DIGEST_B,
        "evaluation_receipt_digests": (DIGEST_A, DIGEST_B),
        "receipt_chain_digest": DIGEST_C,
        "disposition": CandidatePromotionDisposition.PROMOTE,
        "reason_codes": ("PROOF_COMPLETE",),
        "policy_version": "test-policy-v1",
        "policy_digest": DIGEST_D,
        "decided_by": "principal:promoter",
        "decided_at": NOW,
        "observed_correction_epochs": _epochs(),
        "parent_promotion_digest": None,
        "prior_artifact_id": "domain-prior:1",
    }
    values.update(updates)
    return values


def _decision(**updates: Any) -> CandidatePromotionDecision:
    payload = _decision_payload(**updates)
    return CandidatePromotionDecision(
        **payload,
        promotion_digest=candidate_promotion_decision_digest(payload),
    )


def _prior_payload(
    decision: CandidatePromotionDecision | None = None,
    **updates: Any,
) -> dict[str, Any]:
    bound_decision = decision or _decision()
    patch = _patch()
    values: dict[str, Any] = {
        "schema_version": "1.0",
        "prior_artifact_id": "domain-prior:1",
        "prior_version": 1,
        "payload_digest": DIGEST_E,
        "parent_prior_digest": None,
        "candidate_digest": bound_decision.candidate_digest,
        "candidate_payload_digest": DIGEST_B,
        "promotion_digest": bound_decision.promotion_digest,
        "evaluation_head_digest": bound_decision.evaluation_head_digest,
        "evaluation_receipt_digests": bound_decision.evaluation_receipt_digests,
        "receipt_chain_digest": bound_decision.receipt_chain_digest,
        "tenant_id": bound_decision.tenant_id,
        "workspace_id": bound_decision.workspace_id,
        "representation_patch": patch,
        "provenance": (_provenance(patch),),
        "policy_digest": bound_decision.policy_digest,
        "published_by": bound_decision.decided_by,
        "published_at": bound_decision.decided_at,
        "observed_correction_epochs": bound_decision.observed_correction_epochs,
        "state": "INERT",
        "activation_authority": "NONE",
        "uncertainty_behavior": "PRESERVE",
    }
    values.update(updates)
    return values


def _prior(
    decision: CandidatePromotionDecision | None = None,
    **updates: Any,
) -> DomainPriorArtifact:
    payload = _prior_payload(decision, **updates)
    return DomainPriorArtifact(
        **payload,
        prior_digest=domain_prior_artifact_digest(payload),
    )


def test_promotion_disposition_is_closed() -> None:
    assert {item.value for item in CandidatePromotionDisposition} == {
        "REJECT",
        "DEFER",
        "PROMOTE",
    }


@pytest.mark.parametrize(
    "forbidden",
    (
        {"disposition": "PROMOTE"},
        {"threshold": 0.9},
        {"evaluation_receipt_digests": (DIGEST_A,)},
        {"reason_codes": ("CALLER_REASON",)},
        {"policy_version": "caller-policy"},
        {"prior": {"state": "ACTIVE"}},
        {"activate": True},
    ),
)
def test_promotion_command_forbids_caller_decision_fields(
    forbidden: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        CandidatePromotionCommand.model_validate({**_command_values(), **forbidden})


def test_promotion_command_validates_identifiers_and_digest_heads() -> None:
    command = CandidatePromotionCommand(**_command_values())
    assert command.expected_evaluation_head_digest == DIGEST_B

    with pytest.raises(ValidationError):
        CandidatePromotionCommand(**{**_command_values(), "promotion_task_id": ""})
    with pytest.raises(ValidationError):
        CandidatePromotionCommand(
            **{**_command_values(), "expected_evaluation_head_digest": "not-sha256"}
        )


def test_decision_requires_ordered_unique_complete_chain_and_matching_head() -> None:
    with pytest.raises(ValidationError, match="unique"):
        _decision(evaluation_receipt_digests=(DIGEST_A, DIGEST_A))
    with pytest.raises(ValidationError, match="latest receipt"):
        _decision(evaluation_head_digest=DIGEST_C)
    with pytest.raises(ValidationError, match="empty receipt chain"):
        _decision(
            disposition="DEFER",
            evaluation_head_digest=DIGEST_B,
            evaluation_receipt_digests=(),
            prior_artifact_id=None,
        )


def test_empty_chain_promote_is_forbidden_and_prior_id_shape_is_closed() -> None:
    with pytest.raises(ValidationError, match="PROMOTE requires"):
        _decision(
            evaluation_head_digest=None,
            evaluation_receipt_digests=(),
        )
    with pytest.raises(ValidationError, match="prior_artifact_id"):
        _decision(prior_artifact_id=None)

    for disposition in (
        CandidatePromotionDisposition.REJECT,
        CandidatePromotionDisposition.DEFER,
    ):
        with pytest.raises(ValidationError, match="forbid prior_artifact_id"):
            _decision(disposition=disposition)


def test_decision_digest_excludes_only_itself_and_is_mutation_sensitive() -> None:
    payload = _decision_payload()
    decision = CandidatePromotionDecision(
        **payload,
        promotion_digest=candidate_promotion_decision_digest(payload),
    )
    assert decision.promotion_digest == candidate_promotion_decision_digest(
        decision.model_dump(mode="json", exclude={"promotion_digest"})
    )

    changed = {**payload, "decided_by": "principal:other"}
    assert candidate_promotion_decision_digest(changed) != decision.promotion_digest
    with pytest.raises(ValidationError, match="promotion_digest"):
        CandidatePromotionDecision(**payload, promotion_digest=DIGEST_A)


def test_prior_is_permanently_inert_and_binds_patch_provenance() -> None:
    prior = _prior()
    assert prior.state == "INERT"
    assert prior.activation_authority == "NONE"
    assert prior.uncertainty_behavior == "PRESERVE"

    for field, value in {
        "state": "ACTIVE",
        "activation_authority": "SYSTEM",
        "uncertainty_behavior": "OVERWRITE",
    }.items():
        with pytest.raises(ValidationError):
            payload = _prior_payload()
            payload[field] = value
            DomainPriorArtifact.model_validate(
                {
                    **payload,
                    "prior_digest": domain_prior_artifact_digest(payload),
                }
            )

    foreign_patch = _patch()
    with pytest.raises(ValidationError, match="output_patch_digest"):
        _prior(
            provenance=(
                _provenance(foreign_patch).model_copy(
                    update={"output_patch_digest": DIGEST_A}
                ),
            )
        )


def test_prior_digest_excludes_only_itself_and_is_mutation_sensitive() -> None:
    payload = _prior_payload()
    prior = DomainPriorArtifact(
        **payload,
        prior_digest=domain_prior_artifact_digest(payload),
    )
    changed = {**payload, "published_by": "principal:other"}
    assert domain_prior_artifact_digest(changed) != prior.prior_digest
    with pytest.raises(ValidationError, match="prior_digest"):
        DomainPriorArtifact(**payload, prior_digest=DIGEST_A)


def test_result_requires_exact_prior_for_promote_and_forbids_other_priors() -> None:
    decision = _decision()
    prior = _prior(decision)
    result = CandidatePromotionResult(decision=decision, prior=prior)
    assert result.prior == prior

    with pytest.raises(ValidationError, match="PROMOTE result requires"):
        CandidatePromotionResult(decision=decision)

    defer = _decision(disposition="DEFER", prior_artifact_id=None)
    with pytest.raises(ValidationError, match="forbids a prior"):
        CandidatePromotionResult(decision=defer, prior=prior)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("prior_artifact_id", "domain-prior:other", "prior_artifact_id"),
        ("candidate_digest", DIGEST_E, "candidate"),
        ("promotion_digest", DIGEST_E, "promotion"),
        ("receipt_chain_digest", DIGEST_E, "receipt chain"),
        ("tenant_id", "tenant:other", "scope"),
        ("policy_digest", DIGEST_E, "policy"),
        ("published_by", "principal:other", "actor"),
        ("observed_correction_epochs", _epochs(run_epoch=9), "correction"),
    ),
)
def test_result_rejects_prior_binding_mismatch(
    field: str,
    value: object,
    message: str,
) -> None:
    decision = _decision()
    with pytest.raises(ValidationError, match=message):
        CandidatePromotionResult(
            decision=decision, prior=_prior(decision, **{field: value})
        )


def test_digest_helpers_reject_self_inclusion() -> None:
    decision_payload = _decision_payload()
    decision_payload["promotion_digest"] = DIGEST_A
    with pytest.raises(ValueError, match="excluded"):
        candidate_promotion_decision_digest(decision_payload)

    prior_payload = _prior_payload()
    prior_payload["prior_digest"] = DIGEST_A
    with pytest.raises(ValueError, match="excluded"):
        domain_prior_artifact_digest(prior_payload)


def test_prior_schema_cannot_smuggle_activation_or_capability() -> None:
    payload = _prior_payload()
    payload["capability_grant"] = {"capability_id": "forbidden"}
    with pytest.raises(ValidationError, match="Extra inputs"):
        DomainPriorArtifact(
            **payload,
            prior_digest=domain_prior_artifact_digest(payload),
        )
