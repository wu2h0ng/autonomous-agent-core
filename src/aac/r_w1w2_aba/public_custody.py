"""Public-boundary verifier; this is not a private custody or scoring service."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from .canonical import sha256_hex
from .contracts import (
    BlockComparisonV1,
    BlockRelationV1,
    ClosedStage1ReceiptV1,
    ComparatorId,
    ComparisonRelation,
    FeasibilityState,
    GlobalArmOutputSealV1,
    IntegrityState,
    PublicQualificationV1,
    SafetyState,
    SealState,
    SealedOutputCommitmentV1,
)


_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_PACKAGE_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class PublicReceiptError(ValueError):
    def __init__(self, code: str, path: str) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code} at {path}")


@dataclass(frozen=True)
class ValidatedStage1EvidenceV1:
    package_id: str
    bundle_root_digest: str
    exact_subject_digest: str
    integrity: IntegrityState
    safety: SafetyState
    feasibility: FeasibilityState
    blocks: tuple[BlockComparisonV1, ...]


def _closed(payload: Mapping[str, object], allowed: frozenset[str], path: str = "$") -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise PublicReceiptError("UNKNOWN_FIELD", f"{path}.{unknown[0]}")
    missing = sorted(allowed - set(payload))
    if missing:
        raise PublicReceiptError("MISSING_FIELD", f"{path}.{missing[0]}")


def _digest(value: object, path: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise PublicReceiptError("INVALID_DIGEST", path)
    return value


def _token(value: object, path: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise PublicReceiptError("INVALID_PUBLIC_TOKEN", path)
    return value


def _package(value: object, path: str) -> str:
    if not isinstance(value, str) or _PACKAGE_ID.fullmatch(value) is None:
        raise PublicReceiptError("INVALID_PACKAGE_ID", path)
    return value


def parse_global_seal(payload: Mapping[str, object]) -> GlobalArmOutputSealV1:
    _closed(
        payload,
        frozenset(
            (
                "schema_version",
                "package_id",
                "stage_id",
                "bundle_root_digest",
                "stage_spec_digest",
                "seal_state",
                "outputs",
                "missing_output_count",
            )
        ),
    )
    if payload["schema_version"] != "1":
        raise PublicReceiptError("SCHEMA_VERSION_MISMATCH", "$.schema_version")
    if payload["stage_id"] != "STAGE1":
        raise PublicReceiptError("STAGE_MISMATCH", "$.stage_id")
    try:
        seal_state = SealState(payload["seal_state"])
    except (TypeError, ValueError) as exc:
        raise PublicReceiptError("UNKNOWN_SEAL_STATE", "$.seal_state") from exc
    raw_outputs = payload["outputs"]
    if not isinstance(raw_outputs, list):
        raise PublicReceiptError("STAGE1_OUTPUT_CARDINALITY", "$.outputs")
    outputs: list[SealedOutputCommitmentV1] = []
    for index, raw_output in enumerate(raw_outputs):
        path = f"$.outputs[{index}]"
        if not isinstance(raw_output, Mapping):
            raise PublicReceiptError("INVALID_OUTPUT", path)
        _closed(raw_output, frozenset(("slot_id", "output_digest")), path)
        outputs.append(
            SealedOutputCommitmentV1(
                slot_id=_token(raw_output["slot_id"], f"{path}.slot_id"),
                output_digest=_digest(raw_output["output_digest"], f"{path}.output_digest"),
            )
        )
    missing_output_count = payload["missing_output_count"]
    if not isinstance(missing_output_count, int) or isinstance(missing_output_count, bool):
        raise PublicReceiptError("INVALID_MISSING_COUNT", "$.missing_output_count")
    slot_ids = [output.slot_id for output in outputs]
    if len(outputs) != 15 or len(set(slot_ids)) != 15:
        raise PublicReceiptError("STAGE1_OUTPUT_CARDINALITY", "$.outputs")
    if missing_output_count != 0:
        raise PublicReceiptError("STAGE1_OUTPUT_CARDINALITY", "$.missing_output_count")
    return GlobalArmOutputSealV1(
        schema_version="1",
        package_id=_package(payload["package_id"], "$.package_id"),
        stage_id="STAGE1",
        bundle_root_digest=_digest(payload["bundle_root_digest"], "$.bundle_root_digest"),
        stage_spec_digest=_digest(payload["stage_spec_digest"], "$.stage_spec_digest"),
        seal_state=seal_state,
        outputs=tuple(outputs),
        missing_output_count=0,
    )


def parse_closed_stage1_receipt(payload: Mapping[str, object]) -> ClosedStage1ReceiptV1:
    _closed(
        payload,
        frozenset(
            (
                "schema_version",
                "package_id",
                "stage_id",
                "global_seal_digest",
                "exact_subject_digest",
                "integrity",
                "safety",
                "feasibility",
                "blocks",
            )
        ),
    )
    if payload["schema_version"] != "1":
        raise PublicReceiptError("SCHEMA_VERSION_MISMATCH", "$.schema_version")
    if payload["stage_id"] != "STAGE1":
        raise PublicReceiptError("STAGE_MISMATCH", "$.stage_id")
    try:
        integrity = IntegrityState(payload["integrity"])
        safety = SafetyState(payload["safety"])
        feasibility = FeasibilityState(payload["feasibility"])
    except (TypeError, ValueError) as exc:
        raise PublicReceiptError("UNKNOWN_CLOSED_STATE", "$") from exc
    raw_blocks = payload["blocks"]
    if not isinstance(raw_blocks, list):
        raise PublicReceiptError("STAGE1_BLOCK_CARDINALITY", "$.blocks")
    blocks: list[BlockComparisonV1] = []
    for block_index, raw_block in enumerate(raw_blocks):
        block_path = f"$.blocks[{block_index}]"
        if not isinstance(raw_block, Mapping):
            raise PublicReceiptError("INVALID_BLOCK", block_path)
        _closed(raw_block, frozenset(("block_id", "relations")), block_path)
        raw_relations = raw_block["relations"]
        if not isinstance(raw_relations, list):
            raise PublicReceiptError("COMPARATOR_SET_MISMATCH", f"{block_path}.relations")
        relations: list[BlockRelationV1] = []
        for relation_index, raw_relation in enumerate(raw_relations):
            relation_path = f"{block_path}.relations[{relation_index}]"
            if not isinstance(raw_relation, Mapping):
                raise PublicReceiptError("INVALID_RELATION", relation_path)
            _closed(raw_relation, frozenset(("comparator_id", "relation")), relation_path)
            try:
                comparator = ComparatorId(raw_relation["comparator_id"])
                relation = ComparisonRelation(raw_relation["relation"])
            except (TypeError, ValueError) as exc:
                raise PublicReceiptError("COMPARATOR_SET_MISMATCH", relation_path) from exc
            relations.append(BlockRelationV1(comparator, relation))
        if {relation.comparator_id for relation in relations} != set(ComparatorId) or len(
            relations
        ) != len(ComparatorId):
            raise PublicReceiptError("COMPARATOR_SET_MISMATCH", f"{block_path}.relations")
        blocks.append(
            BlockComparisonV1(
                block_id=_token(raw_block["block_id"], f"{block_path}.block_id"),
                relations=tuple(relations),
            )
        )
    block_ids = [block.block_id for block in blocks]
    if len(blocks) != 3 or len(set(block_ids)) != 3:
        raise PublicReceiptError("STAGE1_BLOCK_CARDINALITY", "$.blocks")
    return ClosedStage1ReceiptV1(
        schema_version="1",
        package_id=_package(payload["package_id"], "$.package_id"),
        stage_id="STAGE1",
        global_seal_digest=_digest(payload["global_seal_digest"], "$.global_seal_digest"),
        exact_subject_digest=_digest(payload["exact_subject_digest"], "$.exact_subject_digest"),
        integrity=integrity,
        safety=safety,
        feasibility=feasibility,
        blocks=tuple(blocks),
    )


def validate_post_seal_receipt(
    qualification: PublicQualificationV1,
    seal: GlobalArmOutputSealV1,
    receipt: ClosedStage1ReceiptV1,
) -> ValidatedStage1EvidenceV1:
    if seal.seal_state is not SealState.SEALED:
        raise PublicReceiptError("GLOBAL_SEAL_REQUIRED", "$.seal_state")
    if qualification.package_id != seal.package_id or seal.package_id != receipt.package_id:
        raise PublicReceiptError("PACKAGE_MISMATCH", "$.package_id")
    if qualification.bundle_root_digest != seal.bundle_root_digest:
        raise PublicReceiptError("BUNDLE_ROOT_MISMATCH", "$.bundle_root_digest")
    if qualification.stage_spec_digest != seal.stage_spec_digest:
        raise PublicReceiptError("STAGE_SPEC_MISMATCH", "$.stage_spec_digest")
    output_slot_set_digest = sha256_hex(
        {"slot_ids": sorted(output.slot_id for output in seal.outputs)}
    )
    if qualification.output_slot_set_digest != output_slot_set_digest:
        raise PublicReceiptError("OUTPUT_SLOT_SET_MISMATCH", "$.outputs")
    block_set_digest = sha256_hex(
        {"block_ids": sorted(block.block_id for block in receipt.blocks)}
    )
    if qualification.block_set_digest != block_set_digest:
        raise PublicReceiptError("BLOCK_SET_MISMATCH", "$.blocks")
    if qualification.scorer_subject_digest != receipt.exact_subject_digest:
        raise PublicReceiptError("EXACT_SUBJECT_MISMATCH", "$.exact_subject_digest")
    if receipt.global_seal_digest != sha256_hex(seal.to_mapping()):
        raise PublicReceiptError("GLOBAL_SEAL_DIGEST_MISMATCH", "$.global_seal_digest")
    return ValidatedStage1EvidenceV1(
        package_id=receipt.package_id,
        bundle_root_digest=seal.bundle_root_digest,
        exact_subject_digest=receipt.exact_subject_digest,
        integrity=receipt.integrity,
        safety=receipt.safety,
        feasibility=receipt.feasibility,
        blocks=receipt.blocks,
    )


__all__ = [
    "PublicReceiptError",
    "ValidatedStage1EvidenceV1",
    "parse_closed_stage1_receipt",
    "parse_global_seal",
    "validate_post_seal_receipt",
]
