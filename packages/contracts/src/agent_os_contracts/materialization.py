from __future__ import annotations

from enum import Enum
from math import isfinite
from typing import Any, Literal, Mapping

from pydantic import Field, field_validator, model_validator

from .authority import CorrectionEpochVector
from .common import ContractModel, NonEmptyStr, UtcDateTime, content_digest
from .evidence import Sha256Digest


class MaterializationOutcome(str, Enum):
    CANDIDATE = "CANDIDATE"
    ASK = "ASK"
    UNKNOWN = "UNKNOWN"
    NOT_SUPPORTED = "NOT_SUPPORTED"


class CandidateWriteChannel(str, Enum):
    B = "B"
    R = "R"
    T = "T"
    P = "P"


class RepresentationRelationClass(str, Enum):
    OBSERVED = "OBSERVED"
    ASSERTED = "ASSERTED"
    INFERRED = "INFERRED"
    CORRELATIONAL = "CORRELATIONAL"
    CAUSAL_CANDIDATE = "CAUSAL_CANDIDATE"
    INTERVENTION_VERIFIED = "INTERVENTION_VERIFIED"


class RepresentationPatchOperation(ContractModel):
    operation_id: NonEmptyStr
    operation: Literal["UPSERT", "RETRACT"]
    assertion_id: NonEmptyStr
    subject_ref: NonEmptyStr
    predicate: NonEmptyStr
    object_ref: NonEmptyStr
    relation_class: RepresentationRelationClass
    evidence_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    expected_prior_digest: Sha256Digest | None = None

    @field_validator("evidence_refs", mode="after")
    @classmethod
    def _normalize_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class RepresentationPatch(ContractModel):
    channel: Literal[CandidateWriteChannel.R] = CandidateWriteChannel.R
    base_artifact_digest: Sha256Digest | None = None
    operations: tuple[RepresentationPatchOperation, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _require_unique_operation_ids(self) -> RepresentationPatch:
        operation_ids = tuple(operation.operation_id for operation in self.operations)
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("representation patch operation_id values must be unique")
        return self

    def patch_digest(self) -> str:
        return content_digest(self)


class CandidateProvenance(ContractModel):
    source_id: NonEmptyStr
    source_ref: NonEmptyStr
    source_type: NonEmptyStr
    source_digest: Sha256Digest
    accessed_at: UtcDateTime
    effective_at: UtcDateTime
    license_or_terms_id: NonEmptyStr
    permitted_use: NonEmptyStr
    redistribution_allowed: bool
    custodian_verified_by: NonEmptyStr | None = None
    derivation_input_digests: tuple[Sha256Digest, ...] = ()
    output_patch_digest: Sha256Digest
    expires_at: UtcDateTime

    @field_validator("derivation_input_digests", mode="after")
    @classmethod
    def _normalize_derivation_inputs(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def _validate_time_bounds(self) -> CandidateProvenance:
        if self.effective_at > self.accessed_at:
            raise ValueError("effective_at must not be after accessed_at")
        if self.expires_at <= self.accessed_at:
            raise ValueError("expires_at must be after accessed_at")
        return self


class DomainCandidateDraft(ContractModel):
    task_id: NonEmptyStr
    materialization_run_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    submitted_by: NonEmptyStr
    mechanism_digest: Sha256Digest
    source_snapshot_digest: Sha256Digest
    parent_candidate_digest: Sha256Digest | None = None
    requested_channel: CandidateWriteChannel
    outcome: MaterializationOutcome
    representation_patch: RepresentationPatch | None = None
    provenance: tuple[CandidateProvenance, ...] = ()
    submitted_at: UtcDateTime

    @model_validator(mode="after")
    def _validate_channel_and_outcome(self) -> DomainCandidateDraft:
        if self.requested_channel is not CandidateWriteChannel.R:
            if self.outcome is not MaterializationOutcome.NOT_SUPPORTED:
                raise ValueError("only R may produce a candidate in ADM-P1")
            if self.representation_patch is not None or self.provenance:
                raise ValueError(
                    "B/T/P NOT_SUPPORTED must not carry patch or provenance"
                )
            return self

        if self.outcome is MaterializationOutcome.CANDIDATE:
            if self.representation_patch is None or not self.provenance:
                raise ValueError(
                    "CANDIDATE requires one R representation_patch and provenance"
                )
            patch_digest = self.representation_patch.patch_digest()
            if any(
                item.output_patch_digest != patch_digest for item in self.provenance
            ):
                raise ValueError(
                    "provenance output_patch_digest must match representation patch"
                )
            return self

        if self.representation_patch is not None or self.provenance:
            raise ValueError(
                "ASK/UNKNOWN/NOT_SUPPORTED must not carry patch or provenance"
            )
        return self


def domain_candidate_digest(payload: Mapping[str, Any]) -> str:
    if "candidate_digest" in payload:
        raise ValueError(
            "candidate_digest must be excluded from its own digest payload"
        )
    return content_digest(payload)


class DomainCandidate(ContractModel):
    candidate_id: NonEmptyStr
    candidate_version: int = Field(ge=1)
    candidate_digest: Sha256Digest
    payload_digest: Sha256Digest
    idempotency_key: Sha256Digest
    sealed_by: NonEmptyStr
    sealed_at: UtcDateTime
    observed_correction_epochs: CorrectionEpochVector
    draft: DomainCandidateDraft

    @model_validator(mode="after")
    def _validate_candidate_digest(self) -> DomainCandidate:
        payload = self.model_dump(mode="json", exclude={"candidate_digest"})
        if self.candidate_digest != domain_candidate_digest(payload):
            raise ValueError(
                "candidate_digest does not match canonical candidate payload"
            )
        return self


class CandidateEvaluationDisposition(str, Enum):
    EVALUATOR_PASS = "EVALUATOR_PASS"
    EVALUATOR_FAIL = "EVALUATOR_FAIL"
    UNRESOLVED = "UNRESOLVED"
    INVALID = "INVALID"


class CandidateEvaluatorKind(str, Enum):
    PROGRAMMATIC = "PROGRAMMATIC"
    HUMAN = "HUMAN"
    MODEL = "MODEL"


class CandidateEvaluatorIdentity(ContractModel):
    evaluator_id: NonEmptyStr
    evaluator_kind: CandidateEvaluatorKind
    evaluator_type: NonEmptyStr
    evaluator_version: NonEmptyStr
    implementation_digest: Sha256Digest
    configuration_digest: Sha256Digest
    provider_id: NonEmptyStr | None = None
    model_id: NonEmptyStr | None = None
    checkpoint_digest: Sha256Digest | None = None
    prompt_digest: Sha256Digest | None = None
    fallback_policy: Literal["FORBIDDEN"] = "FORBIDDEN"

    @model_validator(mode="after")
    def _validate_kind_identity(self) -> CandidateEvaluatorIdentity:
        model_fields = (
            self.provider_id,
            self.model_id,
            self.checkpoint_digest,
            self.prompt_digest,
        )
        if self.evaluator_kind is CandidateEvaluatorKind.MODEL:
            if any(value is None for value in model_fields):
                raise ValueError("MODEL evaluator requires full model identity")
        elif any(value is not None for value in model_fields):
            raise ValueError("PROGRAMMATIC and HUMAN evaluators forbid model identity")
        return self


class CandidateEvaluationDraft(ContractModel):
    candidate_digest: Sha256Digest
    candidate_task_id: NonEmptyStr
    evaluation_task_id: NonEmptyStr
    evaluation_run_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    evaluator: CandidateEvaluatorIdentity
    evidence_bundle_digest: Sha256Digest
    evidence_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    disposition: CandidateEvaluationDisposition
    score: float | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    unresolved_gaps: tuple[NonEmptyStr, ...] = ()
    invalidity_reasons: tuple[NonEmptyStr, ...] = ()
    parent_evaluation_digest: Sha256Digest | None = None
    submitted_at: UtcDateTime

    @field_validator(
        "evidence_refs",
        "unresolved_gaps",
        "invalidity_reasons",
        mode="after",
    )
    @classmethod
    def _normalize_set_like_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def _validate_evaluation_shape(self) -> CandidateEvaluationDraft:
        if self.candidate_task_id == self.evaluation_task_id:
            raise ValueError("candidate and evaluation must use different tasks")
        if not isfinite(self.confidence) or (
            self.score is not None and not isfinite(self.score)
        ):
            raise ValueError("evaluation score and confidence must be finite")
        if self.disposition in {
            CandidateEvaluationDisposition.EVALUATOR_PASS,
            CandidateEvaluationDisposition.EVALUATOR_FAIL,
        }:
            if self.score is None:
                raise ValueError("evaluator pass/fail dispositions require score")
            if self.unresolved_gaps or self.invalidity_reasons:
                raise ValueError(
                    "decisive evaluator dispositions forbid gap/reason fields"
                )
        elif self.disposition is CandidateEvaluationDisposition.UNRESOLVED:
            if not self.unresolved_gaps or self.score is not None:
                raise ValueError(
                    "UNRESOLVED requires gaps and forbids a decisive score"
                )
            if self.invalidity_reasons:
                raise ValueError("UNRESOLVED forbids invalidity reasons")
        elif self.disposition is CandidateEvaluationDisposition.INVALID:
            if not self.invalidity_reasons or self.score is not None:
                raise ValueError("INVALID requires reasons and forbids a score")
            if self.unresolved_gaps:
                raise ValueError("INVALID forbids unresolved gaps")
        return self


def candidate_evaluation_receipt_digest(payload: Mapping[str, Any]) -> str:
    if "evaluation_digest" in payload:
        raise ValueError(
            "evaluation_digest must be excluded from its own digest payload"
        )
    return content_digest(payload)


class CandidateEvaluationReceipt(ContractModel):
    evaluation_id: NonEmptyStr
    evaluation_version: int = Field(ge=1)
    evaluation_digest: Sha256Digest
    payload_digest: Sha256Digest
    idempotency_key: Sha256Digest
    recorded_by: NonEmptyStr
    recorded_at: UtcDateTime
    observed_correction_epochs: CorrectionEpochVector
    evaluation_contract_digest: Sha256Digest
    draft: CandidateEvaluationDraft

    @model_validator(mode="after")
    def _validate_evaluation_digest(self) -> CandidateEvaluationReceipt:
        payload = self.model_dump(mode="json", exclude={"evaluation_digest"})
        if self.evaluation_digest != candidate_evaluation_receipt_digest(payload):
            raise ValueError(
                "evaluation_digest does not match canonical receipt payload"
            )
        return self


class CandidatePromotionDisposition(str, Enum):
    REJECT = "REJECT"
    DEFER = "DEFER"
    PROMOTE = "PROMOTE"


class CandidatePromotionCommand(ContractModel):
    candidate_digest: Sha256Digest
    candidate_task_id: NonEmptyStr
    promotion_task_id: NonEmptyStr
    promotion_run_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    expected_evaluation_head_digest: Sha256Digest | None = None
    expected_parent_promotion_digest: Sha256Digest | None = None

    @model_validator(mode="after")
    def _require_distinct_tasks(self) -> CandidatePromotionCommand:
        if self.candidate_task_id == self.promotion_task_id:
            raise ValueError("candidate and promotion must use different tasks")
        return self


def candidate_promotion_decision_digest(payload: Mapping[str, Any]) -> str:
    if "promotion_digest" in payload:
        raise ValueError(
            "promotion_digest must be excluded from its own digest payload"
        )
    return content_digest(payload)


class CandidatePromotionDecision(ContractModel):
    promotion_id: NonEmptyStr
    promotion_version: int = Field(ge=1)
    promotion_digest: Sha256Digest
    payload_digest: Sha256Digest
    idempotency_key: Sha256Digest
    candidate_digest: Sha256Digest
    candidate_task_id: NonEmptyStr
    promotion_task_id: NonEmptyStr
    promotion_run_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    evaluation_head_digest: Sha256Digest | None = None
    evaluation_receipt_digests: tuple[Sha256Digest, ...] = ()
    receipt_chain_digest: Sha256Digest
    disposition: CandidatePromotionDisposition
    reason_codes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    policy_version: NonEmptyStr
    policy_digest: Sha256Digest
    decided_by: NonEmptyStr
    decided_at: UtcDateTime
    observed_correction_epochs: CorrectionEpochVector
    parent_promotion_digest: Sha256Digest | None = None
    prior_artifact_id: NonEmptyStr | None = None

    @field_validator("reason_codes", mode="after")
    @classmethod
    def _normalize_reason_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("promotion reason codes must be unique")
        return values

    @model_validator(mode="after")
    def _validate_chain_disposition_and_digest(self) -> CandidatePromotionDecision:
        receipt_digests = self.evaluation_receipt_digests
        if len(receipt_digests) != len(set(receipt_digests)):
            raise ValueError("evaluation receipt digests must be unique")
        if receipt_digests:
            if self.evaluation_head_digest != receipt_digests[-1]:
                raise ValueError("evaluation head must equal the latest receipt digest")
        elif self.evaluation_head_digest is not None:
            raise ValueError("empty receipt chain requires a null evaluation head")

        if self.disposition is CandidatePromotionDisposition.PROMOTE:
            if not receipt_digests or self.evaluation_head_digest is None:
                raise ValueError("PROMOTE requires a non-empty receipt chain and head")
            if self.prior_artifact_id is None:
                raise ValueError("PROMOTE requires prior_artifact_id")
        elif self.prior_artifact_id is not None:
            raise ValueError("REJECT and DEFER forbid prior_artifact_id")

        payload = self.model_dump(mode="json", exclude={"promotion_digest"})
        if self.promotion_digest != candidate_promotion_decision_digest(payload):
            raise ValueError(
                "promotion_digest does not match canonical decision payload"
            )
        return self


def domain_prior_artifact_digest(payload: Mapping[str, Any]) -> str:
    if "prior_digest" in payload:
        raise ValueError("prior_digest must be excluded from its own digest payload")
    return content_digest(payload)


class DomainPriorArtifact(ContractModel):
    prior_artifact_id: NonEmptyStr
    prior_version: int = Field(ge=1)
    prior_digest: Sha256Digest
    payload_digest: Sha256Digest
    parent_prior_digest: Sha256Digest | None = None
    candidate_digest: Sha256Digest
    candidate_payload_digest: Sha256Digest
    promotion_digest: Sha256Digest
    evaluation_head_digest: Sha256Digest
    evaluation_receipt_digests: tuple[Sha256Digest, ...] = Field(min_length=1)
    receipt_chain_digest: Sha256Digest
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    representation_patch: RepresentationPatch
    provenance: tuple[CandidateProvenance, ...] = Field(min_length=1)
    policy_digest: Sha256Digest
    published_by: NonEmptyStr
    published_at: UtcDateTime
    observed_correction_epochs: CorrectionEpochVector
    state: Literal["INERT"] = "INERT"
    activation_authority: Literal["NONE"] = "NONE"
    uncertainty_behavior: Literal["PRESERVE"] = "PRESERVE"

    @model_validator(mode="after")
    def _validate_prior_bindings_and_digest(self) -> DomainPriorArtifact:
        receipt_digests = self.evaluation_receipt_digests
        if len(receipt_digests) != len(set(receipt_digests)):
            raise ValueError("evaluation receipt digests must be unique")
        if self.evaluation_head_digest != receipt_digests[-1]:
            raise ValueError("evaluation head must equal the latest receipt digest")
        patch_digest = self.representation_patch.patch_digest()
        if any(item.output_patch_digest != patch_digest for item in self.provenance):
            raise ValueError(
                "provenance output_patch_digest must match representation patch"
            )
        payload = self.model_dump(mode="json", exclude={"prior_digest"})
        if self.prior_digest != domain_prior_artifact_digest(payload):
            raise ValueError("prior_digest does not match canonical prior payload")
        return self


class CandidatePromotionResult(ContractModel):
    decision: CandidatePromotionDecision
    prior: DomainPriorArtifact | None = None

    @model_validator(mode="after")
    def _validate_result_bindings(self) -> CandidatePromotionResult:
        decision = self.decision
        prior = self.prior
        if decision.disposition is CandidatePromotionDisposition.PROMOTE:
            if prior is None:
                raise ValueError("PROMOTE result requires a prior")
        elif prior is not None:
            raise ValueError("REJECT or DEFER result forbids a prior")
        else:
            return self

        assert prior is not None
        if prior.prior_artifact_id != decision.prior_artifact_id:
            raise ValueError("prior_artifact_id does not match decision")
        if prior.candidate_digest != decision.candidate_digest:
            raise ValueError("prior candidate binding does not match decision")
        if prior.promotion_digest != decision.promotion_digest:
            raise ValueError("prior promotion binding does not match decision")
        if (
            prior.evaluation_head_digest != decision.evaluation_head_digest
            or prior.evaluation_receipt_digests != decision.evaluation_receipt_digests
            or prior.receipt_chain_digest != decision.receipt_chain_digest
        ):
            raise ValueError("prior receipt chain binding does not match decision")
        if (
            prior.tenant_id != decision.tenant_id
            or prior.workspace_id != decision.workspace_id
        ):
            raise ValueError("prior scope binding does not match decision")
        if prior.policy_digest != decision.policy_digest:
            raise ValueError("prior policy binding does not match decision")
        if prior.published_by != decision.decided_by:
            raise ValueError("prior actor binding does not match decision")
        if prior.published_at != decision.decided_at:
            raise ValueError("prior time binding does not match decision")
        if prior.observed_correction_epochs != decision.observed_correction_epochs:
            raise ValueError("prior correction binding does not match decision")
        return self
