from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from agent_os_contracts import CorrectionEpochVector, content_digest
from agent_os_contracts.materialization import (
    CandidateProvenance,
    CandidateWriteChannel,
    DomainCandidate,
    DomainCandidateDraft,
    MaterializationOutcome,
    RepresentationPatch,
    RepresentationPatchOperation,
    RepresentationRelationClass,
    domain_candidate_digest,
)


NOW = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def _patch(**updates: Any) -> RepresentationPatch:
    values: dict[str, Any] = {
        "base_artifact_digest": None,
        "operations": (
            RepresentationPatchOperation(
                operation_id="op:company-kind",
                operation="UPSERT",
                assertion_id="assertion:company-kind",
                subject_ref="entity:acme",
                predicate="rdf:type",
                object_ref="type:Company",
                relation_class=RepresentationRelationClass.ASSERTED,
                evidence_refs=("evidence:z", "evidence:a", "evidence:z"),
                expected_prior_digest=None,
            ),
        ),
    }
    values.update(updates)
    return RepresentationPatch(**values)


def _provenance(
    patch: RepresentationPatch,
    **updates: Any,
) -> CandidateProvenance:
    values: dict[str, Any] = {
        "source_id": "source:filing",
        "source_ref": "artifact:filing",
        "source_type": "regulatory-filing",
        "source_digest": DIGEST_A,
        "accessed_at": NOW,
        "effective_at": NOW - timedelta(days=1),
        "license_or_terms_id": "terms:public-filing",
        "permitted_use": "analysis",
        "redistribution_allowed": False,
        "custodian_verified_by": "principal:reviewer",
        "derivation_input_digests": (DIGEST_C, DIGEST_B, DIGEST_C),
        "output_patch_digest": patch.patch_digest(),
        "expires_at": NOW + timedelta(days=1),
    }
    values.update(updates)
    return CandidateProvenance(**values)


def _draft(**updates: Any) -> DomainCandidateDraft:
    patch = _patch()
    values: dict[str, Any] = {
        "task_id": "task:1",
        "materialization_run_id": "run:1",
        "tenant_id": "tenant:1",
        "workspace_id": "workspace:1",
        "submitted_by": "principal:1",
        "mechanism_digest": DIGEST_B,
        "source_snapshot_digest": DIGEST_C,
        "parent_candidate_digest": None,
        "requested_channel": CandidateWriteChannel.R,
        "outcome": MaterializationOutcome.CANDIDATE,
        "representation_patch": patch,
        "provenance": (_provenance(patch),),
        "submitted_at": NOW,
    }
    values.update(updates)
    return DomainCandidateDraft(**values)


def _candidate_payload(
    draft: DomainCandidateDraft,
    **updates: Any,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "schema_version": "1.0",
        "candidate_id": "domain-candidate:abc",
        "candidate_version": 1,
        "payload_digest": content_digest(draft),
        "idempotency_key": DIGEST_B,
        "sealed_by": "system:domain-candidate-sealer:v1",
        "sealed_at": NOW,
        "observed_correction_epochs": CorrectionEpochVector(
            task_epoch=1,
            run_epoch=2,
            capability_epoch=3,
        ),
        "draft": draft,
    }
    values.update(updates)
    return values


def test_materialization_enums_are_closed() -> None:
    assert {channel.value for channel in CandidateWriteChannel} == {"B", "R", "T", "P"}
    assert {outcome.value for outcome in MaterializationOutcome} == {
        "CANDIDATE",
        "ASK",
        "UNKNOWN",
        "NOT_SUPPORTED",
    }


def test_representation_patch_digest_is_canonical_and_evidence_is_normalized() -> None:
    patch = _patch()

    assert patch.channel is CandidateWriteChannel.R
    assert patch.operations[0].evidence_refs == ("evidence:a", "evidence:z")
    assert len(patch.patch_digest()) == 64
    assert patch.patch_digest() == _patch().patch_digest()


@pytest.mark.parametrize("channel", ["B", "T", "P", "K", "S", "UNKNOWN"])
def test_representation_patch_rejects_non_r_channels(channel: str) -> None:
    values = _patch().model_dump(mode="json")
    values["channel"] = channel

    with pytest.raises(ValidationError):
        RepresentationPatch.model_validate(values)


def test_provenance_normalizes_derivation_inputs_and_checks_time_order() -> None:
    provenance = _provenance(_patch())

    assert provenance.derivation_input_digests == (DIGEST_B, DIGEST_C)
    with pytest.raises(ValidationError, match="effective_at"):
        _provenance(_patch(), effective_at=NOW + timedelta(seconds=1))
    with pytest.raises(ValidationError, match="expires_at"):
        _provenance(_patch(), expires_at=NOW)


def test_candidate_outcome_requires_exact_patch_shape() -> None:
    with pytest.raises(ValidationError, match="CANDIDATE requires"):
        _draft(representation_patch=None)
    with pytest.raises(ValidationError, match="must not carry"):
        _draft(
            outcome=MaterializationOutcome.UNKNOWN,
            representation_patch=_patch(),
        )


@pytest.mark.parametrize(
    "channel",
    [CandidateWriteChannel.B, CandidateWriteChannel.T, CandidateWriteChannel.P],
)
def test_unimplemented_channels_are_only_typed_not_supported(
    channel: CandidateWriteChannel,
) -> None:
    abstention = _draft(
        requested_channel=channel,
        outcome=MaterializationOutcome.NOT_SUPPORTED,
        representation_patch=None,
        provenance=(),
    )

    assert abstention.requested_channel is channel
    with pytest.raises(ValidationError, match="only R"):
        _draft(requested_channel=channel)


@pytest.mark.parametrize("channel", ["K", "S", "UNKNOWN"])
def test_candidate_draft_rejects_forbidden_channels(channel: str) -> None:
    values = _draft().model_dump(mode="json")
    values["requested_channel"] = channel

    with pytest.raises(ValidationError):
        DomainCandidateDraft.model_validate(values)


def test_candidate_draft_rejects_patch_digest_mismatch() -> None:
    patch = _patch()

    with pytest.raises(ValidationError, match="output_patch_digest"):
        _draft(
            representation_patch=patch,
            provenance=(_provenance(patch, output_patch_digest=DIGEST_A),),
        )


def test_abstention_cannot_smuggle_policy_or_active_authority() -> None:
    values = _draft(
        outcome=MaterializationOutcome.ASK,
        representation_patch=None,
        provenance=(),
    ).model_dump(mode="json")
    values["capability_grant"] = {"capability_id": "forbidden"}

    with pytest.raises(ValidationError, match="Extra inputs"):
        DomainCandidateDraft.model_validate(values)


def test_candidate_digest_excludes_only_itself_and_binds_version_and_c7_epochs() -> None:
    draft = _draft()
    payload = _candidate_payload(draft)
    candidate = DomainCandidate(
        **payload,
        candidate_digest=domain_candidate_digest(payload),
    )

    assert candidate.candidate_digest == domain_candidate_digest(
        candidate.model_dump(mode="json", exclude={"candidate_digest"})
    )
    version_two = {**payload, "candidate_version": 2}
    changed_epochs = {
        **payload,
        "observed_correction_epochs": CorrectionEpochVector(
            task_epoch=1,
            run_epoch=3,
            capability_epoch=3,
        ),
    }
    assert domain_candidate_digest(version_two) != candidate.candidate_digest
    assert domain_candidate_digest(changed_epochs) != candidate.candidate_digest


def test_candidate_rejects_tampered_digest() -> None:
    payload = _candidate_payload(_draft())

    with pytest.raises(ValidationError, match="candidate_digest"):
        DomainCandidate(**payload, candidate_digest=DIGEST_A)
