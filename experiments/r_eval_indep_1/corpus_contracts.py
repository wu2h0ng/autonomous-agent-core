"""Closed, digest-bound corpus manifests for R-EVAL-INDEP-1 Batch-2A/2B."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .contracts import (
    CaseTruth,
    ContractValidationError,
    MutationClass,
    ReviewDisposition,
    canonical_digest,
)


SCHEMA_VERSION = "r-eval-indep-corpus-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CASE_ID = re.compile(r"^case-[0-9a-f]{16}$")
_PRIVATE_COMPACT_TOKENS = (
    "casetruth",
    "mutationclass",
    "oraclepath",
    "oraclerelpath",
    "hiddenoracle",
    "expectedverdict",
    "expecteddisposition",
    "refereemanifest",
)


def _closed(
    value: Mapping[str, Any], expected: set[str], contract_name: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{contract_name} requires an object")
    actual = set(value)
    if actual != expected:
        raise ContractValidationError(
            f"{contract_name} field mismatch: "
            f"unknown={sorted(actual - expected)}, missing={sorted(expected - actual)}"
        )
    return dict(value)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field} requires a non-empty string")
    return value


def _sha(value: Any, field: str) -> str:
    text = _text(value, field)
    if not _SHA256.fullmatch(text):
        raise ContractValidationError(f"{field} requires lowercase sha256")
    return text


def _case_id(value: Any) -> str:
    text = _text(value, "case_id")
    if not _CASE_ID.fullmatch(text):
        raise ContractValidationError("case_id must be opaque case-<16 lowercase hex>")
    return text


def _relpath(value: Any, field: str) -> str:
    text = _text(value, field)
    if "\\" in text or "\x00" in text:
        raise ContractValidationError(f"{field} must use normalized POSIX separators")
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or not path.parts
        or path.as_posix() != text
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ContractValidationError(f"{field} must be a normalized relative path")
    return path.as_posix()


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ContractValidationError(f"{field} requires a non-empty array")
    return tuple(_text(item, field) for item in value)


def _support_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ContractValidationError("support_sha256 requires an object")
    return {
        _relpath(path, "support_sha256 path"): _sha(digest, "support_sha256 digest")
        for path, digest in value.items()
    }


def _reject_public_leakage(payload: Mapping[str, Any]) -> None:
    text = str(payload).lower().replace("\\", "/")
    compact = re.sub(r"[^a-z0-9]+", "", text)
    leaked = [token for token in _PRIVATE_COMPACT_TOKENS if token in compact]
    if "referee/" in text:
        leaked.append("referee/")
    if leaked:
        raise ContractValidationError(
            f"public manifest leaks referee metadata: {sorted(set(leaked))}"
        )


@dataclass(frozen=True, slots=True)
class PublicCaseManifest:
    case_id: str
    source_relpath: str
    source_sha256: str
    test_relpath: str
    test_sha256: str
    support_sha256: Mapping[str, str]
    candidate_sha256: str
    patch_sha256: str
    candidate_patch: str
    public_checks: tuple[str, ...]
    public_manifest_sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PublicCaseManifest:
        expected = {
            "case_id",
            "source_relpath",
            "source_sha256",
            "test_relpath",
            "test_sha256",
            "support_sha256",
            "candidate_sha256",
            "patch_sha256",
            "candidate_patch",
            "public_checks",
            "public_manifest_sha256",
        }
        payload = _closed(value, expected, cls.__name__)
        instance = cls(
            case_id=_case_id(payload["case_id"]),
            source_relpath=_relpath(payload["source_relpath"], "source_relpath"),
            source_sha256=_sha(payload["source_sha256"], "source_sha256"),
            test_relpath=_relpath(payload["test_relpath"], "test_relpath"),
            test_sha256=_sha(payload["test_sha256"], "test_sha256"),
            support_sha256=MappingProxyType(
                _support_mapping(payload["support_sha256"])
            ),
            candidate_sha256=_sha(payload["candidate_sha256"], "candidate_sha256"),
            patch_sha256=_sha(payload["patch_sha256"], "patch_sha256"),
            candidate_patch=_text(payload["candidate_patch"], "candidate_patch"),
            public_checks=_string_tuple(payload["public_checks"], "public_checks"),
            public_manifest_sha256=_sha(
                payload["public_manifest_sha256"], "public_manifest_sha256"
            ),
        )
        unsigned = instance.to_mapping()
        unsigned.pop("public_manifest_sha256")
        _reject_public_leakage(unsigned)
        if canonical_digest(unsigned) != instance.public_manifest_sha256:
            raise ContractValidationError("public manifest digest mismatch")
        return instance

    def to_mapping(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "source_relpath": self.source_relpath,
            "source_sha256": self.source_sha256,
            "test_relpath": self.test_relpath,
            "test_sha256": self.test_sha256,
            "support_sha256": dict(sorted(self.support_sha256.items())),
            "candidate_sha256": self.candidate_sha256,
            "patch_sha256": self.patch_sha256,
            "candidate_patch": self.candidate_patch,
            "public_checks": list(self.public_checks),
            "public_manifest_sha256": self.public_manifest_sha256,
        }


@dataclass(frozen=True, slots=True)
class RefereeCaseManifest:
    case_id: str
    public_manifest_sha256: str
    case_truth: CaseTruth
    mutation_class: MutationClass | None
    expected_disposition: ReviewDisposition
    oracle_relpath: str
    oracle_sha256: str
    referee_manifest_sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RefereeCaseManifest:
        expected = {
            "case_id",
            "public_manifest_sha256",
            "case_truth",
            "mutation_class",
            "expected_disposition",
            "oracle_relpath",
            "oracle_sha256",
            "referee_manifest_sha256",
        }
        payload = _closed(value, expected, cls.__name__)
        try:
            truth = CaseTruth(payload["case_truth"])
            disposition = ReviewDisposition(payload["expected_disposition"])
            mutation_class = (
                None
                if payload["mutation_class"] is None
                else MutationClass(payload["mutation_class"])
            )
        except (TypeError, ValueError) as error:
            raise ContractValidationError("invalid referee enum value") from error
        if truth is CaseTruth.CLEAN:
            if mutation_class is not None or disposition is not ReviewDisposition.ACCEPT:
                raise ContractValidationError(
                    "clean control requires null mutation_class and ACCEPT"
                )
        elif mutation_class is None or disposition is not ReviewDisposition.REJECT:
            raise ContractValidationError(
                "harmful case requires mutation_class and REJECT"
            )
        instance = cls(
            case_id=_case_id(payload["case_id"]),
            public_manifest_sha256=_sha(
                payload["public_manifest_sha256"], "public_manifest_sha256"
            ),
            case_truth=truth,
            mutation_class=mutation_class,
            expected_disposition=disposition,
            oracle_relpath=_relpath(payload["oracle_relpath"], "oracle_relpath"),
            oracle_sha256=_sha(payload["oracle_sha256"], "oracle_sha256"),
            referee_manifest_sha256=_sha(
                payload["referee_manifest_sha256"], "referee_manifest_sha256"
            ),
        )
        unsigned = instance.to_mapping()
        unsigned.pop("referee_manifest_sha256")
        if canonical_digest(unsigned) != instance.referee_manifest_sha256:
            raise ContractValidationError("referee manifest digest mismatch")
        return instance

    def to_mapping(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "public_manifest_sha256": self.public_manifest_sha256,
            "case_truth": self.case_truth.value,
            "mutation_class": (
                None if self.mutation_class is None else self.mutation_class.value
            ),
            "expected_disposition": self.expected_disposition.value,
            "oracle_relpath": self.oracle_relpath,
            "oracle_sha256": self.oracle_sha256,
            "referee_manifest_sha256": self.referee_manifest_sha256,
        }


@dataclass(frozen=True, slots=True)
class CorpusManifest:
    schema_version: str
    corpus_id: str
    runner_sha256: str
    public_cases: tuple[PublicCaseManifest, ...]
    referee_cases: tuple[RefereeCaseManifest, ...]
    public_cases_sha256: str
    referee_cases_sha256: str
    corpus_manifest_sha256: str

    @classmethod
    def build(
        cls,
        *,
        corpus_id: str,
        runner_sha256: str,
        public_cases: Sequence[PublicCaseManifest],
        referee_cases: Sequence[RefereeCaseManifest],
    ) -> CorpusManifest:
        validated_public = tuple(
            PublicCaseManifest.from_mapping(item.to_mapping()) for item in public_cases
        )
        validated_referee = tuple(
            RefereeCaseManifest.from_mapping(item.to_mapping()) for item in referee_cases
        )
        ordered_public = tuple(
            sorted(validated_public, key=lambda item: item.case_id)
        )
        ordered_referee = tuple(
            sorted(validated_referee, key=lambda item: item.case_id)
        )
        public_ids = [item.case_id for item in ordered_public]
        referee_ids = [item.case_id for item in ordered_referee]
        if not public_ids or len(set(public_ids)) != len(public_ids):
            raise ContractValidationError("public case ids must be non-empty and unique")
        if not referee_ids or len(set(referee_ids)) != len(referee_ids):
            raise ContractValidationError("referee case ids must be non-empty and unique")
        if public_ids != referee_ids:
            raise ContractValidationError("public and referee case sets must match exactly")
        by_public = {item.case_id: item for item in ordered_public}
        for referee in ordered_referee:
            if (
                referee.public_manifest_sha256
                != by_public[referee.case_id].public_manifest_sha256
            ):
                raise ContractValidationError(
                    f"referee/public digest mismatch for {referee.case_id}"
                )
        public_digest = canonical_digest(
            [item.to_mapping() for item in ordered_public]
        )
        referee_digest = canonical_digest(
            [item.to_mapping() for item in ordered_referee]
        )
        unsigned = {
            "schema_version": SCHEMA_VERSION,
            "corpus_id": _text(corpus_id, "corpus_id"),
            "runner_sha256": _sha(runner_sha256, "runner_sha256"),
            "public_cases": [item.to_mapping() for item in ordered_public],
            "referee_cases": [item.to_mapping() for item in ordered_referee],
            "public_cases_sha256": public_digest,
            "referee_cases_sha256": referee_digest,
        }
        return cls(
            schema_version=SCHEMA_VERSION,
            corpus_id=unsigned["corpus_id"],
            runner_sha256=unsigned["runner_sha256"],
            public_cases=ordered_public,
            referee_cases=ordered_referee,
            public_cases_sha256=public_digest,
            referee_cases_sha256=referee_digest,
            corpus_manifest_sha256=canonical_digest(unsigned),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CorpusManifest:
        expected = {
            "schema_version",
            "corpus_id",
            "runner_sha256",
            "public_cases",
            "referee_cases",
            "public_cases_sha256",
            "referee_cases_sha256",
            "corpus_manifest_sha256",
        }
        payload = _closed(value, expected, cls.__name__)
        if payload["schema_version"] != SCHEMA_VERSION:
            raise ContractValidationError("unsupported corpus schema")
        if not isinstance(payload["public_cases"], (list, tuple)) or not isinstance(
            payload["referee_cases"], (list, tuple)
        ):
            raise ContractValidationError("corpus cases require arrays")
        built = cls.build(
            corpus_id=payload["corpus_id"],
            runner_sha256=payload["runner_sha256"],
            public_cases=tuple(
                PublicCaseManifest.from_mapping(item)
                for item in payload["public_cases"]
            ),
            referee_cases=tuple(
                RefereeCaseManifest.from_mapping(item)
                for item in payload["referee_cases"]
            ),
        )
        supplied = (
            _sha(payload["public_cases_sha256"], "public_cases_sha256"),
            _sha(payload["referee_cases_sha256"], "referee_cases_sha256"),
            _sha(payload["corpus_manifest_sha256"], "corpus_manifest_sha256"),
        )
        expected_digests = (
            built.public_cases_sha256,
            built.referee_cases_sha256,
            built.corpus_manifest_sha256,
        )
        if supplied != expected_digests:
            raise ContractValidationError("corpus manifest digest mismatch")
        return built

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "corpus_id": self.corpus_id,
            "runner_sha256": self.runner_sha256,
            "public_cases": [item.to_mapping() for item in self.public_cases],
            "referee_cases": [item.to_mapping() for item in self.referee_cases],
            "public_cases_sha256": self.public_cases_sha256,
            "referee_cases_sha256": self.referee_cases_sha256,
            "corpus_manifest_sha256": self.corpus_manifest_sha256,
        }

    def to_public_mapping(self) -> dict[str, Any]:
        unsigned = {
            "schema_version": self.schema_version,
            "corpus_id": self.corpus_id,
            "runner_sha256": self.runner_sha256,
            "public_cases": [item.to_mapping() for item in self.public_cases],
            "public_cases_sha256": self.public_cases_sha256,
        }
        public = dict(unsigned)
        public["public_projection_sha256"] = canonical_digest(unsigned)
        _reject_public_leakage(public)
        return public


__all__ = (
    "CorpusManifest",
    "PublicCaseManifest",
    "RefereeCaseManifest",
    "SCHEMA_VERSION",
)
