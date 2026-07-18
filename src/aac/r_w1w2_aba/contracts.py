"""Closed public contracts for the ABA Stage 1 qualification scaffold.

These objects carry no execution, scoring, signature, freeze, run or authority
capability. They are public commitments and post-seal projections only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BundleId(str, Enum):
    B1 = "B1"
    B2 = "B2"
    B3 = "B3"
    B4 = "B4"
    B5 = "B5"


class AcceptanceDecision(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ComparatorId(str, Enum):
    W1_ONLY = "W1_ONLY"
    VERSION_KEYED_CACHE = "VERSION_KEYED_CACHE"
    BOUNDED_FULL_LOG = "BOUNDED_FULL_LOG"
    SAVED_WORKFLOW = "SAVED_WORKFLOW"


class ComparisonRelation(str, Enum):
    CANDIDATE_STRICT_WIN = "CANDIDATE_STRICT_WIN"
    COMPARATOR_MATCH_OR_WIN = "COMPARATOR_MATCH_OR_WIN"


class SealState(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"


class IntegrityState(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SafetyState(str, Enum):
    NO_REGRESSION = "NO_REGRESSION"
    REGRESSION = "REGRESSION"


class FeasibilityState(str, Enum):
    QUALIFIED = "QUALIFIED"
    INSUFFICIENT = "INSUFFICIENT"


class Stage1Disposition(str, Enum):
    KILL_CURRENT_IMPLEMENTATION = "KILL_CURRENT_IMPLEMENTATION"
    INVALID = "INVALID"
    PARK_STAGE1_NONDOMINANCE = "PARK_STAGE1_NONDOMINANCE"
    PARK_INSUFFICIENT_FEASIBILITY = "PARK_INSUFFICIENT_FEASIBILITY"
    ADVANCE_TO_STAGE2_DESIGN = "ADVANCE_TO_STAGE2_DESIGN"


@dataclass(frozen=True)
class ChildDigestV1:
    child_id: str
    digest: str

    def to_mapping(self) -> dict[str, object]:
        return {"child_id": self.child_id, "digest": self.digest}


@dataclass(frozen=True)
class BundleManifestV1:
    schema_version: str
    package_id: str
    bundle_id: BundleId
    owner_subject_digest: str
    reviewer_subject_digest: str
    children: tuple[ChildDigestV1, ...]

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "package_id": self.package_id,
            "bundle_id": self.bundle_id.value,
            "owner_subject_digest": self.owner_subject_digest,
            "reviewer_subject_digest": self.reviewer_subject_digest,
            "children": [child.to_mapping() for child in self.children],
        }


@dataclass(frozen=True)
class BundleAcceptanceReceiptV1:
    schema_version: str
    package_id: str
    bundle_id: BundleId
    manifest_digest: str
    decision: AcceptanceDecision
    accepted_by_subject_digest: str
    review_digest: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "package_id": self.package_id,
            "bundle_id": self.bundle_id.value,
            "manifest_digest": self.manifest_digest,
            "decision": self.decision.value,
            "accepted_by_subject_digest": self.accepted_by_subject_digest,
            "review_digest": self.review_digest,
        }


@dataclass(frozen=True)
class QualificationIssueV1:
    code: str
    path: str


@dataclass(frozen=True)
class PublicQualificationV1:
    """Projection bound to a separately supplied, pre-existing acceptance root.

    This value carries no authority and does not authenticate the source of that
    root. A caller that computes its own expected root has not established
    independent acceptance or experiment admission.
    """

    package_id: str
    bundle_root_digest: str
    manifest_digests: tuple[str, ...]
    acceptance_digests: tuple[str, ...]
    stage_spec_digest: str
    block_set_digest: str
    output_slot_set_digest: str
    scorer_subject_digest: str


@dataclass(frozen=True)
class QualificationResultV1:
    qualification: PublicQualificationV1 | None
    issues: tuple[QualificationIssueV1, ...]


@dataclass(frozen=True)
class SealedOutputCommitmentV1:
    slot_id: str
    output_digest: str

    def to_mapping(self) -> dict[str, object]:
        return {"slot_id": self.slot_id, "output_digest": self.output_digest}


@dataclass(frozen=True)
class GlobalArmOutputSealV1:
    schema_version: str
    package_id: str
    stage_id: str
    bundle_root_digest: str
    stage_spec_digest: str
    seal_state: SealState
    outputs: tuple[SealedOutputCommitmentV1, ...]
    missing_output_count: int

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "package_id": self.package_id,
            "stage_id": self.stage_id,
            "bundle_root_digest": self.bundle_root_digest,
            "stage_spec_digest": self.stage_spec_digest,
            "seal_state": self.seal_state.value,
            "outputs": [output.to_mapping() for output in self.outputs],
            "missing_output_count": self.missing_output_count,
        }


@dataclass(frozen=True)
class BlockRelationV1:
    comparator_id: ComparatorId
    relation: ComparisonRelation

    def to_mapping(self) -> dict[str, object]:
        return {
            "comparator_id": self.comparator_id.value,
            "relation": self.relation.value,
        }


@dataclass(frozen=True)
class BlockComparisonV1:
    block_id: str
    relations: tuple[BlockRelationV1, ...]

    def to_mapping(self) -> dict[str, object]:
        return {
            "block_id": self.block_id,
            "relations": [relation.to_mapping() for relation in self.relations],
        }


@dataclass(frozen=True)
class ClosedStage1ReceiptV1:
    schema_version: str
    package_id: str
    stage_id: str
    global_seal_digest: str
    exact_subject_digest: str
    integrity: IntegrityState
    safety: SafetyState
    feasibility: FeasibilityState
    blocks: tuple[BlockComparisonV1, ...]

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "package_id": self.package_id,
            "stage_id": self.stage_id,
            "global_seal_digest": self.global_seal_digest,
            "exact_subject_digest": self.exact_subject_digest,
            "integrity": self.integrity.value,
            "safety": self.safety.value,
            "feasibility": self.feasibility.value,
            "blocks": [block.to_mapping() for block in self.blocks],
        }


@dataclass(frozen=True)
class NondominanceObservationV1:
    block_id: str
    comparator_id: ComparatorId


@dataclass(frozen=True)
class Stage1AdjudicationV1:
    disposition: Stage1Disposition
    observations: tuple[NondominanceObservationV1, ...]
    claim_boundary: tuple[str, ...]


__all__ = [
    "AcceptanceDecision",
    "BlockComparisonV1",
    "BlockRelationV1",
    "BundleAcceptanceReceiptV1",
    "BundleId",
    "BundleManifestV1",
    "ChildDigestV1",
    "ClosedStage1ReceiptV1",
    "ComparatorId",
    "ComparisonRelation",
    "FeasibilityState",
    "GlobalArmOutputSealV1",
    "IntegrityState",
    "NondominanceObservationV1",
    "PublicQualificationV1",
    "QualificationIssueV1",
    "QualificationResultV1",
    "SafetyState",
    "SealState",
    "SealedOutputCommitmentV1",
    "Stage1AdjudicationV1",
    "Stage1Disposition",
]
