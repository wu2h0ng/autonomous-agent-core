"""Fail-closed validation of public B1-B5 qualification commitments."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence

from .canonical import sha256_hex
from .contracts import (
    AcceptanceDecision,
    BundleAcceptanceReceiptV1,
    BundleId,
    BundleManifestV1,
    ChildDigestV1,
    PublicQualificationV1,
    QualificationIssueV1,
    QualificationResultV1,
)


_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_PUBLIC_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_PACKAGE_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_REQUIRED_CHILD_IDS = {
    BundleId.B1: frozenset(("DESIGN", "PREREGISTRATION", "ROLE_SEPARATION")),
    BundleId.B2: frozenset(("SAMPLING", "INFORMATION", "CONSTRUCTION")),
    BundleId.B3: frozenset(("ARMS", "PARITY", "LIVENESS")),
    BundleId.B4: frozenset(("CUSTODY", "EGRESS", "GLOBAL_SEAL")),
    BundleId.B5: frozenset(("EXECUTION", "C7", "FREEZE_RUN")),
}


class PublicContractError(ValueError):
    def __init__(self, code: str, path: str) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code} at {path}")


def _closed(payload: Mapping[str, object], allowed: frozenset[str], path: str = "$") -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise PublicContractError("UNKNOWN_FIELD", f"{path}.{unknown[0]}")
    missing = sorted(allowed - set(payload))
    if missing:
        raise PublicContractError("MISSING_FIELD", f"{path}.{missing[0]}")


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise PublicContractError("INVALID_STRING", path)
    return value


def _digest(value: object, path: str) -> str:
    text = _string(value, path)
    if _DIGEST.fullmatch(text) is None:
        raise PublicContractError("INVALID_DIGEST", path)
    return text


def _package_id(value: object, path: str) -> str:
    text = _string(value, path)
    if _PACKAGE_ID.fullmatch(text) is None:
        raise PublicContractError("INVALID_PACKAGE_ID", path)
    return text


def parse_bundle_manifest(
    payload: Mapping[str, object], *, enforce_required_children: bool = True
) -> BundleManifestV1:
    _closed(
        payload,
        frozenset(
            (
                "schema_version",
                "package_id",
                "bundle_id",
                "owner_subject_digest",
                "reviewer_subject_digest",
                "children",
            )
        ),
    )
    if payload["schema_version"] != "1":
        raise PublicContractError("SCHEMA_VERSION_MISMATCH", "$.schema_version")
    try:
        bundle_id = BundleId(payload["bundle_id"])
    except (TypeError, ValueError) as exc:
        raise PublicContractError("UNKNOWN_BUNDLE", "$.bundle_id") from exc
    raw_children = payload["children"]
    if not isinstance(raw_children, list) or not raw_children:
        raise PublicContractError("INVALID_CHILD_SET", "$.children")
    children: list[ChildDigestV1] = []
    for index, raw_child in enumerate(raw_children):
        path = f"$.children[{index}]"
        if not isinstance(raw_child, Mapping):
            raise PublicContractError("INVALID_CHILD", path)
        _closed(raw_child, frozenset(("child_id", "digest")), path)
        child_id = _string(raw_child["child_id"], f"{path}.child_id")
        if _PUBLIC_TOKEN.fullmatch(child_id) is None:
            raise PublicContractError("INVALID_PUBLIC_TOKEN", f"{path}.child_id")
        children.append(
            ChildDigestV1(
                child_id=child_id,
                digest=_digest(raw_child["digest"], f"{path}.digest"),
            )
        )
    child_ids = [child.child_id for child in children]
    if len(set(child_ids)) != len(child_ids):
        raise PublicContractError("DUPLICATE_CHILD", "$.children")
    if enforce_required_children and set(child_ids) != _REQUIRED_CHILD_IDS[bundle_id]:
        raise PublicContractError("REQUIRED_CHILD_SET_MISMATCH", "$.children")
    return BundleManifestV1(
        schema_version="1",
        package_id=_package_id(payload["package_id"], "$.package_id"),
        bundle_id=bundle_id,
        owner_subject_digest=_digest(
            payload["owner_subject_digest"], "$.owner_subject_digest"
        ),
        reviewer_subject_digest=_digest(
            payload["reviewer_subject_digest"], "$.reviewer_subject_digest"
        ),
        children=tuple(children),
    )


def parse_bundle_acceptance(payload: Mapping[str, object]) -> BundleAcceptanceReceiptV1:
    _closed(
        payload,
        frozenset(
            (
                "schema_version",
                "package_id",
                "bundle_id",
                "manifest_digest",
                "decision",
                "accepted_by_subject_digest",
                "review_digest",
            )
        ),
    )
    if payload["schema_version"] != "1":
        raise PublicContractError("SCHEMA_VERSION_MISMATCH", "$.schema_version")
    try:
        bundle_id = BundleId(payload["bundle_id"])
    except (TypeError, ValueError) as exc:
        raise PublicContractError("UNKNOWN_BUNDLE", "$.bundle_id") from exc
    try:
        decision = AcceptanceDecision(payload["decision"])
    except (TypeError, ValueError) as exc:
        raise PublicContractError("UNKNOWN_DECISION", "$.decision") from exc
    return BundleAcceptanceReceiptV1(
        schema_version="1",
        package_id=_package_id(payload["package_id"], "$.package_id"),
        bundle_id=bundle_id,
        manifest_digest=_digest(payload["manifest_digest"], "$.manifest_digest"),
        decision=decision,
        accepted_by_subject_digest=_digest(
            payload["accepted_by_subject_digest"], "$.accepted_by_subject_digest"
        ),
        review_digest=_digest(payload["review_digest"], "$.review_digest"),
    )


def qualify_public_bundles(
    manifests: Sequence[BundleManifestV1],
    acceptances: Sequence[BundleAcceptanceReceiptV1],
) -> QualificationResultV1:
    issues: list[QualificationIssueV1] = []
    manifest_counts = Counter(manifest.bundle_id for manifest in manifests)
    acceptance_counts = Counter(receipt.bundle_id for receipt in acceptances)
    manifests_by_id = {manifest.bundle_id: manifest for manifest in manifests}
    acceptances_by_id = {receipt.bundle_id: receipt for receipt in acceptances}

    for bundle_id in BundleId:
        if manifest_counts[bundle_id] == 0:
            issues.append(QualificationIssueV1(f"MISSING_MANIFEST:{bundle_id.value}", "$"))
            continue
        if manifest_counts[bundle_id] != 1:
            issues.append(QualificationIssueV1(f"DUPLICATE_MANIFEST:{bundle_id.value}", "$"))
        manifest = manifests_by_id[bundle_id]
        if manifest.owner_subject_digest == manifest.reviewer_subject_digest:
            issues.append(QualificationIssueV1(f"ROLE_COLLISION:{bundle_id.value}", "$"))
        if acceptance_counts[bundle_id] == 0:
            issues.append(QualificationIssueV1(f"MISSING_ACCEPTANCE:{bundle_id.value}", "$"))
            continue
        if acceptance_counts[bundle_id] != 1:
            issues.append(QualificationIssueV1(f"DUPLICATE_ACCEPTANCE:{bundle_id.value}", "$"))
        receipt = acceptances_by_id[bundle_id]
        if receipt.package_id != manifest.package_id:
            issues.append(QualificationIssueV1(f"PACKAGE_MISMATCH:{bundle_id.value}", "$"))
        if receipt.decision is not AcceptanceDecision.ACCEPTED:
            issues.append(QualificationIssueV1(f"BUNDLE_NOT_ACCEPTED:{bundle_id.value}", "$"))
        if receipt.accepted_by_subject_digest != manifest.reviewer_subject_digest:
            issues.append(QualificationIssueV1(f"REVIEWER_MISMATCH:{bundle_id.value}", "$"))
        if receipt.manifest_digest != sha256_hex(manifest.to_mapping()):
            issues.append(
                QualificationIssueV1(
                    f"RECEIPT_MANIFEST_DIGEST_MISMATCH:{bundle_id.value}", "$"
                )
            )

    package_ids = {manifest.package_id for manifest in manifests}
    if len(package_ids) != 1:
        issues.append(QualificationIssueV1("PACKAGE_SET_MISMATCH", "$"))
    if issues:
        return QualificationResultV1(None, tuple(issues))

    package_id = next(iter(package_ids))
    manifest_digests = tuple(
        sha256_hex(manifests_by_id[bundle_id].to_mapping()) for bundle_id in BundleId
    )
    bundle_root_digest = sha256_hex(
        {
            "package_id": package_id,
            "manifests": [
                {"bundle_id": bundle_id.value, "manifest_digest": digest}
                for bundle_id, digest in zip(BundleId, manifest_digests, strict=True)
            ],
        }
    )
    return QualificationResultV1(
        PublicQualificationV1(package_id, bundle_root_digest, manifest_digests), ()
    )


__all__ = [
    "PublicContractError",
    "parse_bundle_acceptance",
    "parse_bundle_manifest",
    "qualify_public_bundles",
]
