from __future__ import annotations

from dataclasses import fields

import pytest

from aac.r_w1w2_aba.canonical import sha256_hex
from aac.r_w1w2_aba.contracts import (
    BundleAcceptanceReceiptV1,
    BundleId,
    BundleManifestV1,
    ComparatorId,
    GlobalArmOutputSealV1,
    PublicQualificationV1,
    Stage1AdjudicationV1,
    Stage1Disposition,
)
from aac.r_w1w2_aba.public_custody import (
    PublicReceiptError,
    ValidatedStage1EvidenceV1,
    parse_closed_stage1_receipt,
    parse_global_seal,
    validate_post_seal_receipt,
)
from aac.r_w1w2_aba.stage1_state import adjudicate_stage1
from aac.r_w1w2_aba.validators import (
    parse_bundle_acceptance,
    parse_bundle_manifest,
    qualify_public_bundles,
)


def _digest(index: int) -> str:
    return f"{index:064x}"


_SLOT_IDS = tuple(f"SLOT_{index:02d}" for index in range(15))
_BLOCK_IDS = ("BLOCK_0", "BLOCK_1", "BLOCK_2")
_STAGE_SPEC_DIGEST = _digest(500)
_SCORER_SUBJECT_DIGEST = _digest(700)


def _children(bundle_id: BundleId) -> list[dict[str, str]]:
    children = {
        BundleId.B1: {
            "DESIGN": _digest(1),
            "STAGE_SPEC": _STAGE_SPEC_DIGEST,
            "PREREGISTRATION": _digest(2),
            "ROLE_SEPARATION": _digest(3),
        },
        BundleId.B2: {
            "SAMPLING": _digest(4),
            "INFORMATION": _digest(5),
            "CONSTRUCTION": _digest(6),
            "BLOCK_SET": sha256_hex({"block_ids": list(_BLOCK_IDS)}),
        },
        BundleId.B3: {
            "ARMS": _digest(7),
            "PARITY": _digest(8),
            "LIVENESS": _digest(9),
        },
        BundleId.B4: {
            "CUSTODY": _digest(10),
            "EGRESS": _digest(11),
            "GLOBAL_SEAL": _digest(12),
            "SCORER_SUBJECT": _SCORER_SUBJECT_DIGEST,
        },
        BundleId.B5: {
            "EXECUTION": _digest(13),
            "C7": _digest(14),
            "FREEZE_RUN": _digest(15),
            "OUTPUT_SLOT_SET": sha256_hex({"slot_ids": list(_SLOT_IDS)}),
        },
    }[bundle_id]
    return [
        {"child_id": child_id, "digest": digest}
        for child_id, digest in children.items()
    ]


def _external_acceptance_root(
    manifests: list[BundleManifestV1],
    acceptances: list[BundleAcceptanceReceiptV1],
) -> str:
    manifests_by_id = {manifest.bundle_id: manifest for manifest in manifests}
    acceptances_by_id = {receipt.bundle_id: receipt for receipt in acceptances}
    return sha256_hex(
        {
            "package_id": "aba-stage1-public",
            "manifests": [
                {
                    "bundle_id": bundle_id.value,
                    "manifest_digest": sha256_hex(
                        manifests_by_id[bundle_id].to_mapping()
                    ),
                }
                for bundle_id in BundleId
            ],
            "acceptances": [
                {
                    "bundle_id": bundle_id.value,
                    "acceptance_digest": sha256_hex(
                        acceptances_by_id[bundle_id].to_mapping()
                    ),
                }
                for bundle_id in BundleId
            ],
        }
    )


def _qualification() -> PublicQualificationV1:
    manifests = []
    acceptances = []
    for offset, bundle_id in enumerate(BundleId):
        manifest = parse_bundle_manifest(
            {
                "schema_version": "1",
                "package_id": "aba-stage1-public",
                "bundle_id": bundle_id.value,
                "owner_subject_digest": _digest(100 + offset * 10),
                "reviewer_subject_digest": _digest(101 + offset * 10),
                "children": _children(bundle_id),
            }
        )
        manifests.append(manifest)
        acceptances.append(
            parse_bundle_acceptance(
                {
                    "schema_version": "1",
                    "package_id": "aba-stage1-public",
                    "bundle_id": bundle_id.value,
                    "manifest_digest": sha256_hex(manifest.to_mapping()),
                    "decision": "ACCEPTED",
                    "accepted_by_subject_digest": _digest(101 + offset * 10),
                    "review_digest": _digest(103 + offset * 10),
                }
            )
        )
    qualification = qualify_public_bundles(
        manifests,
        acceptances,
        expected_external_acceptance_root_digest=_external_acceptance_root(
            manifests, acceptances
        ),
    ).qualification
    assert qualification is not None
    return qualification


def _seal_payload(*, state: str = "SEALED", output_count: int = 15) -> dict[str, object]:
    return {
        "schema_version": "1",
        "package_id": "aba-stage1-public",
        "stage_id": "STAGE1",
        "bundle_root_digest": _qualification().bundle_root_digest,
        "stage_spec_digest": _STAGE_SPEC_DIGEST,
        "seal_state": state,
        "outputs": [
            {"slot_id": slot_id, "output_digest": _digest(600 + index)}
            for index, slot_id in enumerate(_SLOT_IDS[:output_count])
        ],
        "missing_output_count": 15 - output_count,
    }


def _relations(relation: str = "CANDIDATE_STRICT_WIN") -> list[dict[str, str]]:
    return [
        {"comparator_id": comparator.value, "relation": relation}
        for comparator in ComparatorId
    ]


def _receipt_payload(seal: GlobalArmOutputSealV1) -> dict[str, object]:
    return {
        "schema_version": "1",
        "package_id": "aba-stage1-public",
        "stage_id": "STAGE1",
        "global_seal_digest": sha256_hex(seal.to_mapping()),
        "exact_subject_digest": _SCORER_SUBJECT_DIGEST,
        "integrity": "PASS",
        "safety": "NO_REGRESSION",
        "feasibility": "QUALIFIED",
        "blocks": [
            {"block_id": block_id, "relations": _relations()}
            for block_id in _BLOCK_IDS
        ],
    }


def _validated_evidence(
    *,
    integrity: str = "PASS",
    safety: str = "NO_REGRESSION",
    feasibility: str = "QUALIFIED",
    matches: tuple[tuple[int, ComparatorId], ...] = (),
) -> ValidatedStage1EvidenceV1:
    qualification = _qualification()
    seal = parse_global_seal(_seal_payload())
    payload = _receipt_payload(seal)
    payload["integrity"] = integrity
    payload["safety"] = safety
    payload["feasibility"] = feasibility
    for block_index, comparator in matches:
        relations = payload["blocks"][block_index]["relations"]  # type: ignore[index]
        relation = next(item for item in relations if item["comparator_id"] == comparator.value)
        relation["relation"] = "COMPARATOR_MATCH_OR_WIN"
    receipt = parse_closed_stage1_receipt(payload)
    return validate_post_seal_receipt(qualification, seal, receipt)


def test_closed_receipt_rejected_before_global_seal() -> None:
    qualification = _qualification()
    seal = parse_global_seal(_seal_payload(state="OPEN"))
    receipt = parse_closed_stage1_receipt(_receipt_payload(seal))

    with pytest.raises(PublicReceiptError) as error:
        validate_post_seal_receipt(qualification, seal, receipt)
    assert error.value.code == "GLOBAL_SEAL_REQUIRED"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("raw_scores", [0.1]),
        ("selected_strongest_killer", "VERSION_KEYED_CACHE"),
        ("disposition", "MET"),
    ],
)
def test_closed_receipt_rejects_unknown_output_field(field: str, value: object) -> None:
    seal = parse_global_seal(_seal_payload())
    payload = _receipt_payload(seal)
    payload[field] = value

    with pytest.raises(PublicReceiptError) as error:
        parse_closed_stage1_receipt(payload)
    assert error.value.code == "UNKNOWN_FIELD"


@pytest.mark.parametrize("count", [14, 16])
def test_global_seal_requires_exactly_15_unique_outputs(count: int) -> None:
    with pytest.raises(PublicReceiptError) as error:
        parse_global_seal(_seal_payload(output_count=count))
    assert error.value.code == "STAGE1_OUTPUT_CARDINALITY"


def test_global_seal_rejects_duplicate_output_slots() -> None:
    payload = _seal_payload()
    payload["outputs"][1]["slot_id"] = payload["outputs"][0]["slot_id"]  # type: ignore[index]

    with pytest.raises(PublicReceiptError) as error:
        parse_global_seal(payload)
    assert error.value.code == "STAGE1_OUTPUT_CARDINALITY"


def test_closed_receipt_requires_three_unique_blocks() -> None:
    seal = parse_global_seal(_seal_payload())
    payload = _receipt_payload(seal)
    payload["blocks"] = payload["blocks"][:2]  # type: ignore[index]

    with pytest.raises(PublicReceiptError) as error:
        parse_closed_stage1_receipt(payload)
    assert error.value.code == "STAGE1_BLOCK_CARDINALITY"


def test_each_block_requires_exact_comparator_set() -> None:
    seal = parse_global_seal(_seal_payload())
    payload = _receipt_payload(seal)
    payload["blocks"][0]["relations"] = payload["blocks"][0]["relations"][:-1]  # type: ignore[index]

    with pytest.raises(PublicReceiptError) as error:
        parse_closed_stage1_receipt(payload)
    assert error.value.code == "COMPARATOR_SET_MISMATCH"


def test_closed_receipt_cannot_be_relabelled_as_stage2() -> None:
    seal = parse_global_seal(_seal_payload())
    payload = _receipt_payload(seal)
    payload["stage_id"] = "STAGE2"

    with pytest.raises(PublicReceiptError) as error:
        parse_closed_stage1_receipt(payload)
    assert error.value.code == "STAGE_MISMATCH"


def test_stage_spec_must_match_externally_pinned_qualification() -> None:
    qualification = _qualification()
    seal = parse_global_seal({**_seal_payload(), "stage_spec_digest": _digest(999)})
    receipt = parse_closed_stage1_receipt(_receipt_payload(seal))

    with pytest.raises(PublicReceiptError) as error:
        validate_post_seal_receipt(qualification, seal, receipt)
    assert error.value.code == "STAGE_SPEC_MISMATCH"


def test_seal_slots_must_match_externally_pinned_slot_set() -> None:
    qualification = _qualification()
    payload = _seal_payload()
    payload["outputs"][0]["slot_id"] = "OTHER_SLOT"  # type: ignore[index]
    seal = parse_global_seal(payload)
    receipt = parse_closed_stage1_receipt(_receipt_payload(seal))

    with pytest.raises(PublicReceiptError) as error:
        validate_post_seal_receipt(qualification, seal, receipt)
    assert error.value.code == "OUTPUT_SLOT_SET_MISMATCH"


def test_receipt_blocks_must_match_externally_pinned_block_set() -> None:
    qualification = _qualification()
    seal = parse_global_seal(_seal_payload())
    payload = _receipt_payload(seal)
    payload["blocks"][0]["block_id"] = "OTHER_BLOCK"  # type: ignore[index]
    receipt = parse_closed_stage1_receipt(payload)

    with pytest.raises(PublicReceiptError) as error:
        validate_post_seal_receipt(qualification, seal, receipt)
    assert error.value.code == "BLOCK_SET_MISMATCH"


def test_receipt_subject_must_match_externally_pinned_scorer_subject() -> None:
    qualification = _qualification()
    seal = parse_global_seal(_seal_payload())
    payload = _receipt_payload(seal)
    payload["exact_subject_digest"] = _digest(999)
    receipt = parse_closed_stage1_receipt(payload)

    with pytest.raises(PublicReceiptError) as error:
        validate_post_seal_receipt(qualification, seal, receipt)
    assert error.value.code == "EXACT_SUBJECT_MISMATCH"


def test_any_killer_match_or_win_parks_and_retains_all_observations() -> None:
    evidence = _validated_evidence(
        matches=((0, ComparatorId.VERSION_KEYED_CACHE), (1, ComparatorId.SAVED_WORKFLOW))
    )

    result = adjudicate_stage1(evidence)

    assert result.disposition is Stage1Disposition.PARK_STAGE1_NONDOMINANCE
    assert {(item.block_id, item.comparator_id) for item in result.observations} == {
        ("BLOCK_0", ComparatorId.VERSION_KEYED_CACHE),
        ("BLOCK_1", ComparatorId.SAVED_WORKFLOW),
    }


def test_w1_only_match_or_win_parks() -> None:
    result = adjudicate_stage1(
        _validated_evidence(matches=((2, ComparatorId.W1_ONLY),))
    )

    assert result.disposition is Stage1Disposition.PARK_STAGE1_NONDOMINANCE


def test_all_twelve_strict_wins_only_advance_with_no_met_boundary() -> None:
    result = adjudicate_stage1(_validated_evidence())

    assert result.disposition is Stage1Disposition.ADVANCE_TO_STAGE2_DESIGN
    assert result.claim_boundary == ("NO_MET", "NEW_PREREG_REQUIRED")
    assert result.observations == ()


def test_safety_regression_has_highest_precedence() -> None:
    result = adjudicate_stage1(
        _validated_evidence(
            safety="REGRESSION",
            integrity="FAIL",
            feasibility="INSUFFICIENT",
            matches=((0, ComparatorId.W1_ONLY),),
        )
    )

    assert result.disposition is Stage1Disposition.KILL_CURRENT_IMPLEMENTATION


def test_integrity_failure_precedes_nondominance() -> None:
    result = adjudicate_stage1(
        _validated_evidence(
            integrity="FAIL", matches=((0, ComparatorId.VERSION_KEYED_CACHE),)
        )
    )

    assert result.disposition is Stage1Disposition.INVALID


def test_insufficient_feasibility_precedes_scientific_comparison() -> None:
    result = adjudicate_stage1(
        _validated_evidence(
            feasibility="INSUFFICIENT", matches=((0, ComparatorId.SAVED_WORKFLOW),)
        )
    )

    assert result.disposition is Stage1Disposition.PARK_INSUFFICIENT_FEASIBILITY


def test_disposition_enum_contains_no_met_or_reduces_claim() -> None:
    forbidden = ("MET", "NARROW_MET", "REDUCES_TO")

    assert all(not any(token == value.value for token in forbidden) for value in Stage1Disposition)


def test_adjudication_surface_has_no_authority_fields() -> None:
    names = {field.name for field in fields(Stage1AdjudicationV1)}

    assert names.isdisjoint({"freeze", "run", "permit", "signer", "provider", "authority"})
