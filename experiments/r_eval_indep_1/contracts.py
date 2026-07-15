"""Closed contracts and integrity guards for R-EVAL-INDEP-1."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CASE_ID = re.compile(r"^case-[0-9a-f]{16}$")
_ARM_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_PUBLIC_LEAK_TOKENS = (
    "hidden_oracle",
    "hidden-oracle",
    "gold_label",
    "gold-label",
    "expected_verdict",
    "oracle_path",
    "/referee/",
    "\\referee\\",
    ".agent_runs/referee",
    "mutation_class",
    "case_truth",
)


class ContractValidationError(ValueError):
    """A closed contract was malformed or carried an unknown field."""


class IdentityCollapseError(ValueError):
    """Builder, referee, reviewer, or adjudicator identities collapsed."""


class MatrixIntegrityError(ValueError):
    """A response matrix was duplicate, ragged, missing, or unexpected."""


class MutationClass(str, Enum):
    CONTRACT_RELAXATION = "contract_relaxation"
    DIGEST_PROVENANCE_DRIFT = "digest_provenance_drift"
    AUTHORITY_BYPASS = "authority_bypass"
    CONSTANT_RETURN_PSEUDO_TEST = "constant_return_pseudo_test"
    HIDDEN_POLICY = "hidden_policy"
    PHASE_NON_ATOMICITY = "phase_non_atomicity"
    STALE_EVIDENCE_IDENTITY = "stale_evidence_identity"


class ReviewDisposition(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    ABSTAIN = "ABSTAIN"


class CaseTruth(str, Enum):
    HARMFUL = "HARMFUL"
    CLEAN = "CLEAN"


def _closed_payload(
    value: Mapping[str, Any], expected: set[str], contract_name: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{contract_name} requires an object")
    actual = set(value)
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unknown or missing:
        raise ContractValidationError(
            f"{contract_name} field mismatch: unknown={unknown}, missing={missing}"
        )
    return dict(value)


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field} requires a non-empty string")
    return value


def _sha256(value: Any, field: str) -> str:
    text = _nonempty_string(value, field)
    if not _SHA256.fullmatch(text):
        raise ContractValidationError(f"{field} requires lowercase sha256")
    return text


def _case_id(value: Any) -> str:
    text = _nonempty_string(value, "case_id")
    if not _CASE_ID.fullmatch(text):
        raise ContractValidationError("case_id must be opaque case-<16 lowercase hex>")
    return text


def _arm_id(value: Any) -> str:
    text = _nonempty_string(value, "arm_id")
    if not _ARM_ID.fullmatch(text):
        raise ContractValidationError("arm_id has invalid characters")
    return text


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractValidationError(f"{field} requires a non-negative integer")
    return value


def _string_tuple(value: Any, field: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ContractValidationError(f"{field} requires an array")
    result = tuple(_nonempty_string(item, field) for item in value)
    if not allow_empty and not result:
        raise ContractValidationError(f"{field} cannot be empty")
    return result


def _normalize_json(value: Any, active: set[int]) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractValidationError("canonical JSON rejects non-finite floats")
        return value
    if isinstance(value, Enum):
        return _normalize_json(value.value, active)
    to_mapping = getattr(value, "to_mapping", None)
    if callable(to_mapping):
        return _normalize_json(to_mapping(), active)
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise ContractValidationError("canonical JSON rejects cycles")
        active.add(identity)
        try:
            normalized: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ContractValidationError("canonical JSON keys must be strings")
                normalized[key] = _normalize_json(item, active)
            return normalized
        finally:
            active.remove(identity)
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in active:
            raise ContractValidationError("canonical JSON rejects cycles")
        active.add(identity)
        try:
            return [_normalize_json(item, active) for item in value]
        finally:
            active.remove(identity)
    raise ContractValidationError(
        f"canonical JSON rejects type {type(value).__name__}"
    )


def canonical_json_bytes(value: Any) -> bytes:
    normalized = _normalize_json(value, set())
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class ReviewerIdentity:
    reviewer_id: str
    provider_family: str
    served_model_id: str
    model_version: str
    endpoint_class: str
    system_prompt_sha256: str
    task_prompt_sha256: str
    tool_profile_sha256: str
    context_manifest_sha256: str
    decoding_config_sha256: str
    fallback_policy: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ReviewerIdentity:
        expected = {
            "reviewer_id",
            "provider_family",
            "served_model_id",
            "model_version",
            "endpoint_class",
            "system_prompt_sha256",
            "task_prompt_sha256",
            "tool_profile_sha256",
            "context_manifest_sha256",
            "decoding_config_sha256",
            "fallback_policy",
        }
        payload = _closed_payload(value, expected, cls.__name__)
        fallback_policy = _nonempty_string(
            payload["fallback_policy"], "fallback_policy"
        )
        if fallback_policy != "FORBIDDEN":
            raise ContractValidationError("provider fallback must be FORBIDDEN")
        return cls(
            reviewer_id=_nonempty_string(payload["reviewer_id"], "reviewer_id"),
            provider_family=_nonempty_string(
                payload["provider_family"], "provider_family"
            ),
            served_model_id=_nonempty_string(
                payload["served_model_id"], "served_model_id"
            ),
            model_version=_nonempty_string(payload["model_version"], "model_version"),
            endpoint_class=_nonempty_string(
                payload["endpoint_class"], "endpoint_class"
            ),
            system_prompt_sha256=_sha256(
                payload["system_prompt_sha256"], "system_prompt_sha256"
            ),
            task_prompt_sha256=_sha256(
                payload["task_prompt_sha256"], "task_prompt_sha256"
            ),
            tool_profile_sha256=_sha256(
                payload["tool_profile_sha256"], "tool_profile_sha256"
            ),
            context_manifest_sha256=_sha256(
                payload["context_manifest_sha256"], "context_manifest_sha256"
            ),
            decoding_config_sha256=_sha256(
                payload["decoding_config_sha256"], "decoding_config_sha256"
            ),
            fallback_policy=fallback_policy,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "reviewer_id": self.reviewer_id,
            "provider_family": self.provider_family,
            "served_model_id": self.served_model_id,
            "model_version": self.model_version,
            "endpoint_class": self.endpoint_class,
            "system_prompt_sha256": self.system_prompt_sha256,
            "task_prompt_sha256": self.task_prompt_sha256,
            "tool_profile_sha256": self.tool_profile_sha256,
            "context_manifest_sha256": self.context_manifest_sha256,
            "decoding_config_sha256": self.decoding_config_sha256,
            "fallback_policy": self.fallback_policy,
        }

    def digest(self) -> str:
        return canonical_digest(self.to_mapping())


@dataclass(frozen=True, slots=True)
class PublicCaseBundle:
    case_id: str
    source_language: str
    base_snapshot_sha256: str
    candidate_patch: str
    public_requirements: tuple[str, ...]
    public_checks: tuple[str, ...]
    public_manifest_sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PublicCaseBundle:
        expected = {
            "case_id",
            "source_language",
            "base_snapshot_sha256",
            "candidate_patch",
            "public_requirements",
            "public_checks",
            "public_manifest_sha256",
        }
        payload = _closed_payload(value, expected, cls.__name__)
        bundle = cls(
            case_id=_case_id(payload["case_id"]),
            source_language=_nonempty_string(
                payload["source_language"], "source_language"
            ),
            base_snapshot_sha256=_sha256(
                payload["base_snapshot_sha256"], "base_snapshot_sha256"
            ),
            candidate_patch=_nonempty_string(
                payload["candidate_patch"], "candidate_patch"
            ),
            public_requirements=_string_tuple(
                payload["public_requirements"],
                "public_requirements",
                allow_empty=False,
            ),
            public_checks=_string_tuple(
                payload["public_checks"], "public_checks", allow_empty=False
            ),
            public_manifest_sha256=_sha256(
                payload["public_manifest_sha256"], "public_manifest_sha256"
            ),
        )
        bundle._reject_private_leakage()
        unsigned = bundle.to_mapping()
        unsigned.pop("public_manifest_sha256")
        if canonical_digest(unsigned) != bundle.public_manifest_sha256:
            raise ContractValidationError("public manifest digest mismatch")
        return bundle

    def _reject_private_leakage(self) -> None:
        public_text = "\n".join(
            (
                self.case_id,
                self.source_language,
                self.candidate_patch,
                *self.public_requirements,
                *self.public_checks,
            )
        ).lower()
        leaked = [token for token in _PUBLIC_LEAK_TOKENS if token in public_text]
        if leaked:
            raise ContractValidationError(
                f"public case bundle leaks private referee metadata: {leaked}"
            )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "source_language": self.source_language,
            "base_snapshot_sha256": self.base_snapshot_sha256,
            "candidate_patch": self.candidate_patch,
            "public_requirements": list(self.public_requirements),
            "public_checks": list(self.public_checks),
            "public_manifest_sha256": self.public_manifest_sha256,
        }


@dataclass(frozen=True, slots=True)
class ReviewResponse:
    case_id: str
    arm_id: str
    reviewer_identity_digest: str
    disposition: ReviewDisposition
    p_candidate_valid_micros: int
    blocking_findings: tuple[str, ...]
    generated_test_patch: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    raw_response_sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ReviewResponse:
        expected = {
            "case_id",
            "arm_id",
            "reviewer_identity_digest",
            "disposition",
            "p_candidate_valid_micros",
            "blocking_findings",
            "generated_test_patch",
            "input_tokens",
            "output_tokens",
            "latency_ms",
            "raw_response_sha256",
        }
        payload = _closed_payload(value, expected, cls.__name__)
        try:
            disposition = ReviewDisposition(payload["disposition"])
        except (TypeError, ValueError) as error:
            raise ContractValidationError("unsupported review disposition") from error
        probability = _nonnegative_int(
            payload["p_candidate_valid_micros"], "p_candidate_valid_micros"
        )
        if probability > 1_000_000:
            raise ContractValidationError(
                "p_candidate_valid_micros must be between 0 and 1000000"
            )
        generated = payload["generated_test_patch"]
        if generated is not None and not isinstance(generated, str):
            raise ContractValidationError("generated_test_patch must be string or null")
        return cls(
            case_id=_case_id(payload["case_id"]),
            arm_id=_arm_id(payload["arm_id"]),
            reviewer_identity_digest=_sha256(
                payload["reviewer_identity_digest"], "reviewer_identity_digest"
            ),
            disposition=disposition,
            p_candidate_valid_micros=probability,
            blocking_findings=_string_tuple(
                payload["blocking_findings"],
                "blocking_findings",
                allow_empty=True,
            ),
            generated_test_patch=generated,
            input_tokens=_nonnegative_int(payload["input_tokens"], "input_tokens"),
            output_tokens=_nonnegative_int(
                payload["output_tokens"], "output_tokens"
            ),
            latency_ms=_nonnegative_int(payload["latency_ms"], "latency_ms"),
            raw_response_sha256=_sha256(
                payload["raw_response_sha256"], "raw_response_sha256"
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "arm_id": self.arm_id,
            "reviewer_identity_digest": self.reviewer_identity_digest,
            "disposition": self.disposition.value,
            "p_candidate_valid_micros": self.p_candidate_valid_micros,
            "blocking_findings": list(self.blocking_findings),
            "generated_test_patch": self.generated_test_patch,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "raw_response_sha256": self.raw_response_sha256,
        }


def validate_identity_separation(
    *,
    mutation_builder_id: str,
    oracle_author_id: str,
    adjudicator_id: str,
    reviewers: Sequence[ReviewerIdentity],
) -> None:
    sovereign_roles = {
        _nonempty_string(mutation_builder_id, "mutation_builder_id"),
        _nonempty_string(oracle_author_id, "oracle_author_id"),
        _nonempty_string(adjudicator_id, "adjudicator_id"),
    }
    if len(sovereign_roles) != 3:
        raise IdentityCollapseError(
            "mutation builder, oracle author, and adjudicator must be distinct"
        )
    if not reviewers:
        raise IdentityCollapseError("at least one reviewer identity is required")
    collapsed = sorted(
        {reviewer.reviewer_id for reviewer in reviewers} & sovereign_roles
    )
    if collapsed:
        raise IdentityCollapseError(
            f"reviewer identity overlaps a sovereign role: {collapsed}"
        )


def validate_response_matrix(
    expected_case_ids: Sequence[str],
    expected_arm_ids: Sequence[str],
    responses: Sequence[ReviewResponse],
) -> tuple[ReviewResponse, ...]:
    case_ids = tuple(_case_id(case_id) for case_id in expected_case_ids)
    arm_ids = tuple(_arm_id(arm_id) for arm_id in expected_arm_ids)
    if not case_ids or len(set(case_ids)) != len(case_ids):
        raise MatrixIntegrityError("expected case ids must be non-empty and unique")
    if not arm_ids or len(set(arm_ids)) != len(arm_ids):
        raise MatrixIntegrityError("expected arm ids must be non-empty and unique")

    expected = {(case_id, arm_id) for case_id in case_ids for arm_id in arm_ids}
    seen: dict[tuple[str, str], ReviewResponse] = {}
    for response in responses:
        key = (response.case_id, response.arm_id)
        if key not in expected:
            raise MatrixIntegrityError(f"unexpected response cell: {key}")
        if key in seen:
            raise MatrixIntegrityError(f"duplicate response cell: {key}")
        seen[key] = response

    missing = sorted(expected - set(seen))
    if missing:
        raise MatrixIntegrityError(f"ragged response matrix; missing={missing}")

    identities_by_arm: dict[str, set[str]] = {arm_id: set() for arm_id in arm_ids}
    for response in seen.values():
        identities_by_arm[response.arm_id].add(response.reviewer_identity_digest)
    drifted_arms = sorted(
        arm_id for arm_id, digests in identities_by_arm.items() if len(digests) != 1
    )
    if drifted_arms:
        raise MatrixIntegrityError(
            f"reviewer identity drift within response arm: {drifted_arms}"
        )

    case_order = {case_id: index for index, case_id in enumerate(case_ids)}
    arm_order = {arm_id: index for index, arm_id in enumerate(arm_ids)}
    return tuple(
        sorted(
            seen.values(),
            key=lambda item: (case_order[item.case_id], arm_order[item.arm_id]),
        )
    )


__all__ = (
    "CaseTruth",
    "ContractValidationError",
    "IdentityCollapseError",
    "MatrixIntegrityError",
    "MutationClass",
    "PublicCaseBundle",
    "ReviewDisposition",
    "ReviewerIdentity",
    "ReviewResponse",
    "canonical_digest",
    "canonical_json_bytes",
    "validate_identity_separation",
    "validate_response_matrix",
)
