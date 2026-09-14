"""Contract inference types: mandate → typed success predicates + evidence bindings.

Spec: docs/contract-inferencer-spec.md v0.3 (§4 Data Model, §12 Correction Hook).

All types are frozen, content-addressed ContractModels. Semantic predicates
proposed by an LLM are never blocking until operator-confirmed (C7 gate,
spec §9.5).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime, content_digest
from .evidence import Sha256Digest

# ---------------------------------------------------------------------------
# Enumerations (spec §4.1)
# ---------------------------------------------------------------------------


class PredicateKind(str, Enum):
    STRUCTURAL = "STRUCTURAL"
    SEMANTIC = "SEMANTIC"
    CONFIRMED = "CONFIRMED"
    PROMOTED = "PROMOTED"


class CheckType(str, Enum):
    # deterministic, blocking-capable
    TYPE = "TYPE"
    RANGE = "RANGE"
    ENUM = "ENUM"
    REGEX = "REGEX"
    CARDINALITY = "CARDINALITY"
    FIELD_PRESENCE = "FIELD_PRESENCE"
    STATE_DELTA = "STATE_DELTA"
    TOOL_RESPONSE = "TOOL_RESPONSE"
    ARTIFACT_EXISTS = "ARTIFACT_EXISTS"
    ARTIFACT_CONTENT = "ARTIFACT_CONTENT"
    CROSS_CONSISTENCY = "CROSS_CONSISTENCY"
    # soft, advisory only
    LLM_JUDGE = "LLM_JUDGE"


class EvidenceSourceType(str, Enum):
    TOOL_RESPONSE = "TOOL_RESPONSE"
    ARTIFACT = "ARTIFACT"
    ENVIRONMENT_QUERY = "ENVIRONMENT_QUERY"
    ACTION_RECEIPT = "ACTION_RECEIPT"


# ---------------------------------------------------------------------------
# Evidence binding (spec §4.2)
# ---------------------------------------------------------------------------


class EvidenceBinding(ContractModel):
    binding_id: NonEmptyStr
    source_type: EvidenceSourceType
    # TOOL_RESPONSE: tool call selector (e.g. "send_email:last")
    # ARTIFACT: artifact path or pattern (e.g. "deliverables/report.json")
    # ENVIRONMENT_QUERY: query descriptor
    # ACTION_RECEIPT: action_id pattern
    source_selector: NonEmptyStr
    # JSONPath/jq into the source. None means "the entire source".
    extract_path: NonEmptyStr | None = None
    # Human-readable: what this evidence proves.
    relation: NonEmptyStr


# ---------------------------------------------------------------------------
# Success predicate (spec §4.3, §4.4)
# ---------------------------------------------------------------------------

# Required check_params keys per check_type (spec §4.4). Used by Quality Gate Q2.
CHECK_TYPE_REQUIRED_PARAMS: dict[CheckType, tuple[str, ...]] = {
    CheckType.TYPE: ("field", "expected_type"),
    CheckType.RANGE: ("field",),
    CheckType.ENUM: ("field", "allowed_values"),
    CheckType.REGEX: ("field", "pattern"),
    CheckType.CARDINALITY: ("target",),
    CheckType.FIELD_PRESENCE: ("field",),
    CheckType.STATE_DELTA: ("query", "expected_delta", "baseline_ref"),
    CheckType.TOOL_RESPONSE: ("tool_name", "condition"),
    CheckType.ARTIFACT_EXISTS: ("path",),
    CheckType.ARTIFACT_CONTENT: ("path", "content_assertions"),
    CheckType.CROSS_CONSISTENCY: ("refs", "relation"),
    CheckType.LLM_JUDGE: ("rubric", "evidence_refs"),
}

ALLOWED_META_TEMPLATES: frozenset[str] = frozenset(
    {
        "schema",
        "cardinality",
        "consistency",
        "evidence_anchor",
        "version_conflict",
        "coverage",
        "scope",
    }
)

class SuccessPredicate(ContractModel):
    predicate_id: NonEmptyStr  # content-derived: "pred:" + sha256[:12]
    kind: PredicateKind
    description: NonEmptyStr
    check_type: CheckType
    check_params: dict[str, Any]
    evidence_bindings: tuple[EvidenceBinding, ...] = Field(min_length=1)
    blocking: bool = True
    confidence: float = Field(ge=0.0, le=1.0)
    # Provenance (proposal origin; authorization is in PredicateConfirmation):
    #   "mechanical:<extractor_name>"
    #   "llm:<model_id>"
    #   "operator:<principal_id>"
    #   "promoted:<clause_id>"
    source: NonEmptyStr
    falsifiable: bool = False
    meta_template: NonEmptyStr | None = None
    scope_tags: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def _validate_meta_template(self) -> SuccessPredicate:
        if self.meta_template is not None and self.meta_template not in ALLOWED_META_TEMPLATES:
            raise ValueError(
                f"meta_template must be one of {sorted(ALLOWED_META_TEMPLATES)} "
                f"or null, got {self.meta_template!r}"
            )
        return self


def derive_predicate_id(
    kind: PredicateKind,
    check_type: CheckType,
    check_params: dict[str, Any],
    evidence_bindings: tuple[EvidenceBinding, ...],
) -> str:
    """Content-derived predicate ID: ``pred:<sha256[:12]>``.

    ID changes when params or bindings change (spec §16 open question 3:
    a changed predicate is a new predicate).
    """
    digest = content_digest(
        {
            "kind": kind.value,
            "check_type": check_type.value,
            "check_params": check_params,
            "evidence_bindings": [
                b.model_dump(mode="json") for b in evidence_bindings
            ],
        }
    )
    return f"pred:{digest[:12]}"


# ---------------------------------------------------------------------------
# Failure path (spec §4.5)
# ---------------------------------------------------------------------------


class FailurePath(ContractModel):
    failure_path_id: NonEmptyStr
    trigger: NonEmptyStr
    action: Literal["abort", "retry", "escalate", "compensate"]
    max_retries: int = Field(ge=0, default=0)
    escalation_target: NonEmptyStr = "human"


# ---------------------------------------------------------------------------
# Clarification & confirmation (spec §4.6)
# ---------------------------------------------------------------------------


class ClarificationQuestion(ContractModel):
    question_id: NonEmptyStr
    predicate_id: NonEmptyStr
    question: NonEmptyStr
    question_type: Literal["yes_no", "choice", "value"]
    options: tuple[NonEmptyStr, ...] = ()
    on_unanswered: Literal["drop", "downgrade"] = "downgrade"

    @model_validator(mode="after")
    def _choice_requires_options(self) -> ClarificationQuestion:
        if self.question_type == "choice" and not self.options:
            raise ValueError("choice question requires non-empty options")
        return self


class ClarificationAnswer(ContractModel):
    question_id: NonEmptyStr
    answer: NonEmptyStr
    # Operator authority for the clarification: required so that a
    # pre-endorsement is attributable and can back a confirmation record.
    answered_by: NonEmptyStr
    answered_at: UtcDateTime


class PredicateConfirmation(ContractModel):
    predicate_id: NonEmptyStr
    decision: Literal["approve", "reject", "adjust"]
    # Full replacement predicate when decision="adjust"; new content-derived id.
    adjusted_predicate: SuccessPredicate | None = None
    # Clarified "yes"/choice prior to batch confirm; default approve in batch.
    pre_endorsed: bool = False
    confirmed_by: NonEmptyStr
    confirmed_at: UtcDateTime

    @model_validator(mode="after")
    def _adjust_requires_predicate(self) -> PredicateConfirmation:
        if self.decision == "adjust" and self.adjusted_predicate is None:
            raise ValueError('decision="adjust" requires adjusted_predicate')
        return self


# ---------------------------------------------------------------------------
# Inferred task contract (spec §4.7)
# ---------------------------------------------------------------------------


class InferredTaskContract(ContractModel):
    contract_id: NonEmptyStr  # "itc:" + content_digest(excluding contract_id)
    mandate_id: NonEmptyStr
    mandate_digest: Sha256Digest
    task_id: NonEmptyStr
    inferred_at: UtcDateTime
    inferrer_version: NonEmptyStr
    model_id: NonEmptyStr  # "none" if mechanical-only
    deliverable_schema: dict[str, Any]
    preconditions: tuple[SuccessPredicate, ...] = ()
    success_predicates: tuple[SuccessPredicate, ...] = Field(min_length=1)
    failure_paths: tuple[FailurePath, ...] = ()
    clarification_questions: tuple[ClarificationQuestion, ...] = ()
    clarification_answers: tuple[ClarificationAnswer, ...] = ()
    confirmation_records: tuple[PredicateConfirmation, ...] = ()
    confirmation_status: Literal["PENDING", "CONFIRMED", "NOT_REQUIRED"] = "PENDING"
    unresolved_items: tuple[NonEmptyStr, ...] = ()
    warnings: tuple[NonEmptyStr, ...] = ()
    meta_templates_instantiated: tuple[NonEmptyStr, ...] = ()

    def contract_digest(self) -> str:
        """Digest over all fields except contract_id (spec §10 step 2)."""
        payload = self.model_dump(mode="json", exclude={"contract_id"})
        return content_digest(payload)


def derive_contract_id(contract: InferredTaskContract) -> str:
    return f"itc:{contract.contract_digest()}"


# ---------------------------------------------------------------------------
# Inference report (spec §4.8)
# ---------------------------------------------------------------------------


class InferenceReport(ContractModel):
    report_id: NonEmptyStr
    contract_id: NonEmptyStr
    mandate_id: NonEmptyStr
    pipeline_state: Literal[
        "QUESTIONS_PENDING",
        "CONFIRMATION_PENDING",
        "FROZEN",
        "REJECTED",
    ]
    mechanical_count: int = Field(ge=0)
    semantic_proposed_count: int = Field(ge=0)
    semantic_rejected_count: int = Field(ge=0)
    confirmed_count: int = Field(ge=0)
    blocking_count: int = Field(ge=0)
    advisory_count: int = Field(ge=0)
    clarification_raised: int = Field(ge=0)
    clarification_answered: int = Field(ge=0)
    coverage_gaps: tuple[NonEmptyStr, ...] = ()
    inference_latency_ms: int = Field(ge=0)
    model_id: NonEmptyStr
    created_at: UtcDateTime


# ---------------------------------------------------------------------------
# Quality gate result (returned by QualityGate.check, spec §8.2 / §13)
# ---------------------------------------------------------------------------


class QualityGateResult(ContractModel):
    accepted: tuple[SuccessPredicate, ...] = ()
    rejected: tuple[tuple[SuccessPredicate, NonEmptyStr], ...] = ()
    clarification_needed: tuple[SuccessPredicate, ...] = ()
    confirmation_needed: tuple[SuccessPredicate, ...] = ()
    warnings: tuple[NonEmptyStr, ...] = ()
    coverage_gaps: tuple[NonEmptyStr, ...] = ()


# ---------------------------------------------------------------------------
# Predicate set (frozen persistence unit, implementation-cast §1.3)
# ---------------------------------------------------------------------------


class PredicateSet(ContractModel):
    """Content-addressed, frozen set of predicates persisted at assembly time.

    Stored via SQLitePredicateSetStore; referenced by ExpectedOutcome via
    evaluator_version = content_digest(this).
    """

    set_id: NonEmptyStr  # "predset:" + digest[:16]
    contract_id: NonEmptyStr
    task_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    predicates: tuple[SuccessPredicate, ...] = Field(min_length=1)
    confirmation_records: tuple[PredicateConfirmation, ...] = ()
    frozen_at: UtcDateTime

    def content_key(self) -> str:
        """Full SHA256 digest used as the persistence key."""
        return content_digest(self.model_dump(mode="json", exclude={"set_id"}))


# ---------------------------------------------------------------------------
# Typed correction (spec §12)
# ---------------------------------------------------------------------------


class TypedPredicateCorrection(ContractModel):
    correction_id: NonEmptyStr
    contract_id: NonEmptyStr
    predicate_id: NonEmptyStr
    predicate_description: NonEmptyStr
    observed_value: dict[str, Any]
    expected_condition: dict[str, Any]
    failure_code: Literal[
        "CRITERIA_NOT_MET",
        "INSUFFICIENT_EVIDENCE",
        "UNSUPPORTED",
    ]
    evidence_refs: tuple[NonEmptyStr, ...]
    created_at: UtcDateTime


# ---------------------------------------------------------------------------
# HCW telemetry (automatically recorded at each three-call API boundary)
# ---------------------------------------------------------------------------


class InferenceTelemetry(ContractModel):
    """Automatic HCW instrumentation for one contract inference lifecycle.

    All timestamps and counts are stamped by the system at API call boundaries.
    No manual logging. operator_wall_seconds is an upper-bound proxy for human
    review time (presentation → response), used by M-1 kill criterion.
    """

    telemetry_id: NonEmptyStr
    contract_id: NonEmptyStr
    task_id: NonEmptyStr
    model_id: NonEmptyStr

    # Stage 0-3 (infer)
    infer_started_at: UtcDateTime
    infer_completed_at: UtcDateTime | None = None
    inference_latency_ms: int = Field(ge=0, default=0)

    # Stage 4 (clarification)
    clarification_presented_at: UtcDateTime | None = None
    clarification_received_at: UtcDateTime | None = None
    questions_raised: int = Field(ge=0, default=0)
    questions_answered_yes: int = Field(ge=0, default=0)
    questions_answered_no: int = Field(ge=0, default=0)
    questions_answered_choice: int = Field(ge=0, default=0)
    questions_unanswered_downgraded: int = Field(ge=0, default=0)
    questions_unanswered_dropped: int = Field(ge=0, default=0)

    # Stage 4.5 (confirmation)
    confirmation_presented_at: UtcDateTime | None = None
    confirmation_received_at: UtcDateTime | None = None
    predicates_presented: int = Field(ge=0, default=0)
    predicates_approved: int = Field(ge=0, default=0)
    predicates_rejected: int = Field(ge=0, default=0)
    predicates_adjusted: int = Field(ge=0, default=0)
    predicates_pre_endorsed: int = Field(ge=0, default=0)

    # Final
    pipeline_state: Literal[
        "QUESTIONS_PENDING",
        "CONFIRMATION_PENDING",
        "FROZEN",
        "REJECTED",
    ] = "QUESTIONS_PENDING"
    blocking_count: int = Field(ge=0, default=0)
    rejection_reason: str | None = None
    completed_at: UtcDateTime | None = None

    @property
    def clarification_wall_seconds(self) -> float:
        """Wall-clock seconds between clarification presented and received."""
        if self.clarification_presented_at and self.clarification_received_at:
            return (
                self.clarification_received_at - self.clarification_presented_at
            ).total_seconds()
        return 0.0

    @property
    def confirmation_wall_seconds(self) -> float:
        """Wall-clock seconds between confirmation presented and received."""
        if self.confirmation_presented_at and self.confirmation_received_at:
            return (
                self.confirmation_received_at - self.confirmation_presented_at
            ).total_seconds()
        return 0.0

    @property
    def operator_wall_seconds(self) -> float:
        """Total operator wall-clock seconds across all interaction points."""
        return self.clarification_wall_seconds + self.confirmation_wall_seconds

    @property
    def operator_intervention_count(self) -> int:
        """Number of distinct human interaction rounds (clarification + confirmation)."""
        count = 0
        if self.questions_raised > 0:
            count += 1
        if self.predicates_presented > 0:
            count += 1
        return count
