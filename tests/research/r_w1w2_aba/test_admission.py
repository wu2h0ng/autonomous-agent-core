from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path

import pytest

from aac.r_w1w2_aba.canonical import CanonicalizationError, canonical_json_bytes, sha256_hex
from aac.r_w1w2_aba.contracts import (
    BundleAcceptanceReceiptV1,
    BundleId,
    BundleManifestV1,
    PublicQualificationV1,
)
from aac.r_w1w2_aba.validators import (
    PublicContractError,
    parse_bundle_acceptance,
    parse_bundle_manifest,
    qualify_public_bundles,
)


def _digest(index: int) -> str:
    return f"{index:064x}"


_CHILD_IDS = {
    BundleId.B1: ("DESIGN", "STAGE_SPEC", "PREREGISTRATION", "ROLE_SEPARATION"),
    BundleId.B2: ("SAMPLING", "INFORMATION", "CONSTRUCTION", "BLOCK_SET"),
    BundleId.B3: ("ARMS", "PARITY", "LIVENESS"),
    BundleId.B4: ("CUSTODY", "EGRESS", "GLOBAL_SEAL", "SCORER_SUBJECT"),
    BundleId.B5: ("EXECUTION", "C7", "FREEZE_RUN", "OUTPUT_SLOT_SET"),
}


def _manifest_payload(bundle_id: BundleId) -> dict[str, object]:
    offset = list(BundleId).index(bundle_id) * 20
    return {
        "schema_version": "1",
        "package_id": "aba-stage1-public",
        "bundle_id": bundle_id.value,
        "owner_subject_digest": _digest(100 + offset),
        "reviewer_subject_digest": _digest(101 + offset),
        "children": [
            {"child_id": child_id, "digest": _digest(102 + offset + index)}
            for index, child_id in enumerate(_CHILD_IDS[bundle_id])
        ],
    }


def _acceptance_payload(bundle_id: BundleId, manifest_digest: str) -> dict[str, object]:
    offset = list(BundleId).index(bundle_id) * 20
    return {
        "schema_version": "1",
        "package_id": "aba-stage1-public",
        "bundle_id": bundle_id.value,
        "manifest_digest": manifest_digest,
        "decision": "ACCEPTED",
        "accepted_by_subject_digest": _digest(101 + offset),
        "review_digest": _digest(110 + offset),
    }


def _valid_public_bundles() -> tuple[
    list[BundleManifestV1], list[BundleAcceptanceReceiptV1]
]:
    manifests = [parse_bundle_manifest(_manifest_payload(bundle_id)) for bundle_id in BundleId]
    acceptances = [
        parse_bundle_acceptance(
            _acceptance_payload(manifest.bundle_id, sha256_hex(manifest.to_mapping()))
        )
        for manifest in manifests
    ]
    return manifests, acceptances


def _external_acceptance_root(
    manifests: list[BundleManifestV1],
    acceptances: list[BundleAcceptanceReceiptV1],
) -> str:
    manifests_by_id = {manifest.bundle_id: manifest for manifest in manifests}
    acceptances_by_id = {receipt.bundle_id: receipt for receipt in acceptances}
    return sha256_hex(
        {
            "package_id": manifests[0].package_id,
            "manifests": [
                {
                    "bundle_id": bundle_id.value,
                    "manifest_digest": sha256_hex(manifests_by_id[bundle_id].to_mapping()),
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


def test_manifest_rejects_unknown_field() -> None:
    payload = _manifest_payload(BundleId.B1)
    payload["run_authorized"] = True

    with pytest.raises(PublicContractError) as error:
        parse_bundle_manifest(payload)

    assert (error.value.code, error.value.path) == ("UNKNOWN_FIELD", "$.run_authorized")


def test_qualification_rejects_missing_b5_acceptance() -> None:
    manifests, acceptances = _valid_public_bundles()

    result = qualify_public_bundles(
        manifests,
        acceptances[:-1],
        expected_external_acceptance_root_digest=_external_acceptance_root(
            manifests, acceptances
        ),
    )

    assert result.qualification is None
    assert "MISSING_ACCEPTANCE:B5" in {issue.code for issue in result.issues}


def test_qualification_rejects_tampered_child_digest() -> None:
    manifests, acceptances = _valid_public_bundles()
    tampered_payload = _manifest_payload(BundleId.B4)
    tampered_payload["children"][0]["digest"] = _digest(999)  # type: ignore[index]
    manifests[3] = parse_bundle_manifest(tampered_payload)

    result = qualify_public_bundles(
        manifests,
        acceptances,
        expected_external_acceptance_root_digest=_external_acceptance_root(
            _valid_public_bundles()[0], acceptances
        ),
    )

    assert result.qualification is None
    assert "RECEIPT_MANIFEST_DIGEST_MISMATCH:B4" in {
        issue.code for issue in result.issues
    }


def test_qualification_rejects_owner_reviewer_collision() -> None:
    payload = _manifest_payload(BundleId.B1)
    payload["reviewer_subject_digest"] = payload["owner_subject_digest"]
    manifests, acceptances = _valid_public_bundles()
    manifests[0] = parse_bundle_manifest(payload)

    result = qualify_public_bundles(
        manifests,
        acceptances,
        expected_external_acceptance_root_digest=_external_acceptance_root(
            _valid_public_bundles()[0], acceptances
        ),
    )

    assert result.qualification is None
    assert "ROLE_COLLISION:B1" in {issue.code for issue in result.issues}


def test_manifest_rejects_private_path_reference() -> None:
    payload = _manifest_payload(BundleId.B4)
    payload["children"][0]["child_id"] = "scorer-private/x"  # type: ignore[index]

    with pytest.raises(PublicContractError) as error:
        parse_bundle_manifest(payload)

    assert error.value.code == "INVALID_PUBLIC_TOKEN"
    assert "scorer-private/x" not in str(error.value)


def test_green_qualification_cannot_mint_freeze_or_run() -> None:
    manifests, acceptances = _valid_public_bundles()
    result = qualify_public_bundles(
        manifests,
        acceptances,
        expected_external_acceptance_root_digest=_external_acceptance_root(
            manifests, acceptances
        ),
    )
    payload = _acceptance_payload(BundleId.B1, _digest(1))
    payload["freeze_receipt"] = _digest(2)

    assert result.qualification is not None
    assert {field.name for field in fields(PublicQualificationV1)}.isdisjoint(
        {"freeze", "run", "permit", "signer", "authority"}
    )
    with pytest.raises(PublicContractError) as error:
        parse_bundle_acceptance(payload)
    assert error.value.code == "UNKNOWN_FIELD"


def test_required_bundle_children_have_no_public_escape_hatch() -> None:
    payload = _manifest_payload(BundleId.B1)
    payload["children"] = payload["children"][:1]  # type: ignore[index]

    with pytest.raises(PublicContractError) as error:
        parse_bundle_manifest(payload)
    assert error.value.code == "REQUIRED_CHILD_SET_MISMATCH"
    with pytest.raises(TypeError):
        parse_bundle_manifest(payload, enforce_required_children=False)  # type: ignore[call-arg]


def test_qualification_revalidates_required_children_for_direct_dataclass_input() -> None:
    manifests, acceptances = _valid_public_bundles()
    valid = manifests[0]
    manifests[0] = BundleManifestV1(
        schema_version=valid.schema_version,
        package_id=valid.package_id,
        bundle_id=valid.bundle_id,
        owner_subject_digest=valid.owner_subject_digest,
        reviewer_subject_digest=valid.reviewer_subject_digest,
        children=valid.children[:1],
    )

    result = qualify_public_bundles(
        manifests,
        acceptances,
        expected_external_acceptance_root_digest=_external_acceptance_root(
            _valid_public_bundles()[0], acceptances
        ),
    )

    assert result.qualification is None
    assert "REQUIRED_CHILD_SET_MISMATCH:B1" in {
        issue.code for issue in result.issues
    }


def test_qualification_rejects_malformed_direct_bundle_dataclasses() -> None:
    manifests, acceptances = _valid_public_bundles()
    manifests = [
        replace(
            manifest,
            schema_version="999",
            package_id="bad/package",
            owner_subject_digest="BAD_OWNER",
            reviewer_subject_digest="BAD_REVIEWER",
        )
        for manifest in manifests
    ]
    acceptances = [
        replace(
            receipt,
            schema_version="999",
            package_id="bad/package",
            manifest_digest=sha256_hex(manifest.to_mapping()),
            accepted_by_subject_digest="BAD_REVIEWER",
            review_digest="BAD_REVIEW",
        )
        for manifest, receipt in zip(manifests, acceptances, strict=True)
    ]

    result = qualify_public_bundles(
        manifests,
        acceptances,
        expected_external_acceptance_root_digest=_external_acceptance_root(
            manifests, acceptances
        ),
    )

    assert result.qualification is None
    assert "INVALID_MANIFEST_CONTRACT:B1" in {
        issue.code for issue in result.issues
    }


def test_qualification_requires_external_acceptance_pin() -> None:
    manifests, acceptances = _valid_public_bundles()

    result = qualify_public_bundles(manifests, acceptances)

    assert result.qualification is None
    assert "EXTERNAL_ACCEPTANCE_ROOT_REQUIRED" in {
        issue.code for issue in result.issues
    }


def test_acceptance_review_tamper_moves_root_and_fails_external_pin() -> None:
    manifests, acceptances = _valid_public_bundles()
    expected_root = _external_acceptance_root(manifests, acceptances)
    tampered_payload = acceptances[2].to_mapping()
    tampered_payload["review_digest"] = _digest(999)
    acceptances[2] = parse_bundle_acceptance(tampered_payload)

    result = qualify_public_bundles(
        manifests,
        acceptances,
        expected_external_acceptance_root_digest=expected_root,
    )

    assert result.qualification is None
    assert "EXTERNAL_ACCEPTANCE_ROOT_MISMATCH" in {
        issue.code for issue in result.issues
    }


def test_manifest_child_order_is_canonicalized() -> None:
    payload = _manifest_payload(BundleId.B2)
    reordered = {**payload, "children": list(reversed(payload["children"]))}  # type: ignore[arg-type]

    first = parse_bundle_manifest(payload)
    second = parse_bundle_manifest(reordered)

    assert first.children == second.children
    assert sha256_hex(first.to_mapping()) == sha256_hex(second.to_mapping())


def test_canonical_digest_is_order_invariant_and_tamper_sensitive() -> None:
    first = {"b": [2, 3], "a": "value"}
    reordered = {"a": "value", "b": [2, 3]}
    tampered = {"a": "value", "b": [2, 4]}

    assert canonical_json_bytes(first) == canonical_json_bytes(reordered)
    assert sha256_hex(first) == sha256_hex(reordered)
    assert sha256_hex(first) != sha256_hex(tampered)


@pytest.mark.parametrize("value", [1.0, Path("private"), b"private"])
def test_canonical_json_rejects_float_path_and_bytes(value: object) -> None:
    with pytest.raises(CanonicalizationError, match="UNSUPPORTED_CANONICAL_TYPE"):
        canonical_json_bytes(value)
