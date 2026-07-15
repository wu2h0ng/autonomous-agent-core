"""Fail-closed native preregistration readiness checks for R-EVAL-INDEP-1.

The committed candidate intentionally carries no live provider, oracle-custody,
C7, independent-review, freezer, or run-authority binding.  This module can
verify exact bytes and report those omissions, but cannot freeze or run an
experiment and cannot manufacture an external acceptance.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

from .contracts import ContractValidationError, canonical_digest
from .native_protocol import ReviewerEndpointBinding


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_HEAD = re.compile(r"^[0-9a-f]{40}$")
_SCHEMA_VERSION = "r-eval-indep-1-native-prereg-v1"
_CHANNEL_CLAIM = "other(research-evaluator-independence)"
_REQUIRED_ROLES = (
    "mutation_builder",
    "oracle_author",
    "oracle_custodian",
    "collection_operator",
    "model_reviewer",
    "independent_code_reviewer",
    "result_adjudicator",
    "c7_authority",
    "freezer",
    "run_authority",
)
_BLOCKERS = (
    "PROVIDER_BINDINGS_UNBOUND",
    "ORACLE_CUSTODY_UNBOUND",
    "C7_AUTHORITY_UNBOUND",
    "INDEPENDENT_REVIEW_UNBOUND",
    "FREEZER_IDENTITY_UNBOUND",
    "RUN_AUTHORITY_UNBOUND",
)


class ReadinessError(ValueError):
    """The candidate is malformed, drifted, role-collapsed, or not ready."""


def _closed(
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


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field} requires a non-empty string")
    return value


def _literal(value: Any, field: str, expected: str) -> str:
    text = _text(value, field)
    if text != expected:
        raise ContractValidationError(f"{field} must be {expected}")
    return text


def _sha(value: Any, field: str) -> str:
    text = _text(value, field)
    if not _SHA256.fullmatch(text):
        raise ContractValidationError(f"{field} requires lowercase sha256")
    return text


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ContractValidationError(f"{field} requires a boolean")
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractValidationError(f"{field} requires a positive integer")
    return value


def _strings(value: Any, field: str, *, nonempty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ContractValidationError(f"{field} requires an array")
    result = tuple(_text(item, field) for item in value)
    if nonempty and not result:
        raise ContractValidationError(f"{field} cannot be empty")
    if len(set(result)) != len(result):
        raise ContractValidationError(f"{field} cannot contain duplicates")
    return result


def _optional_mapping(value: Any, field: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field} requires an object or null")
    return value


@dataclass(frozen=True, slots=True)
class MechanismRecord:
    channel_claim: str
    files: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> MechanismRecord:
        payload = _closed(value, {"channel_claim", "files"}, cls.__name__)
        return cls(
            channel_claim=_literal(
                payload["channel_claim"], "mechanism.channel_claim", _CHANNEL_CLAIM
            ),
            files=_strings(payload["files"], "mechanism.files"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {"channel_claim": self.channel_claim, "files": list(self.files)}


@dataclass(frozen=True, slots=True)
class ExactManifest:
    algorithm: str
    files: Mapping[str, str]
    sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ExactManifest:
        payload = _closed(value, {"algorithm", "files", "sha256"}, cls.__name__)
        algorithm = _literal(payload["algorithm"], "exact_manifest.algorithm", "sha256")
        raw_files = payload["files"]
        if not isinstance(raw_files, Mapping) or not raw_files:
            raise ContractValidationError("exact_manifest.files requires a non-empty object")
        files: dict[str, str] = {}
        for raw_path, raw_hash in raw_files.items():
            path = _text(raw_path, "exact_manifest.files path")
            posix = PurePosixPath(path)
            if (
                posix.is_absolute()
                or ".." in posix.parts
                or "." in posix.parts
                or "\\" in path
                or path != posix.as_posix()
            ):
                raise ContractValidationError(f"unsafe manifest path: {path}")
            files[path] = _sha(raw_hash, f"exact_manifest.files[{path}]")
        manifest_sha = _sha(payload["sha256"], "exact_manifest.sha256")
        if canonical_digest(files) != manifest_sha:
            raise ContractValidationError("exact manifest digest does not bind its file map")
        return cls(
            algorithm=algorithm,
            files=MappingProxyType(dict(sorted(files.items()))),
            sha256=manifest_sha,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "files": dict(self.files),
            "sha256": self.sha256,
        }

    def verify(self, repository_root: Path) -> None:
        root = repository_root.resolve(strict=True)
        for relpath, expected in self.files.items():
            candidate = root / relpath
            cursor = root
            for part in PurePosixPath(relpath).parts:
                cursor = cursor / part
                if cursor.is_symlink():
                    raise ReadinessError(f"manifest path traverses symlink: {relpath}")
            try:
                resolved = candidate.resolve(strict=True)
            except OSError as error:
                raise ReadinessError(f"manifest file missing: {relpath}") from error
            if not resolved.is_relative_to(root) or not resolved.is_file():
                raise ReadinessError(f"manifest path is not a repository file: {relpath}")
            actual = hashlib.sha256(resolved.read_bytes()).hexdigest()
            if actual != expected:
                raise ReadinessError(
                    f"manifest drift for {relpath}: expected={expected}, actual={actual}"
                )


@dataclass(frozen=True, slots=True)
class CorpusRecord:
    harmful_cases: int
    clean_cases: int
    corpus_manifest_sha256: str
    public_cases_sha256: str
    referee_cases_sha256: str
    runner_sha256: str
    truth_join: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CorpusRecord:
        payload = _closed(
            value,
            {
                "harmful_cases",
                "clean_cases",
                "corpus_manifest_sha256",
                "public_cases_sha256",
                "referee_cases_sha256",
                "runner_sha256",
                "truth_join",
            },
            cls.__name__,
        )
        return cls(
            harmful_cases=_positive_int(payload["harmful_cases"], "harmful_cases"),
            clean_cases=_positive_int(payload["clean_cases"], "clean_cases"),
            corpus_manifest_sha256=_sha(
                payload["corpus_manifest_sha256"], "corpus_manifest_sha256"
            ),
            public_cases_sha256=_sha(
                payload["public_cases_sha256"], "public_cases_sha256"
            ),
            referee_cases_sha256=_sha(
                payload["referee_cases_sha256"], "referee_cases_sha256"
            ),
            runner_sha256=_sha(payload["runner_sha256"], "runner_sha256"),
            truth_join=_literal(
                payload["truth_join"], "truth_join", "MECHANICAL_BY_OPAQUE_CASE_ID"
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "harmful_cases": self.harmful_cases,
            "clean_cases": self.clean_cases,
            "corpus_manifest_sha256": self.corpus_manifest_sha256,
            "public_cases_sha256": self.public_cases_sha256,
            "referee_cases_sha256": self.referee_cases_sha256,
            "runner_sha256": self.runner_sha256,
            "truth_join": self.truth_join,
        }


@dataclass(frozen=True, slots=True)
class ControlsRecord:
    one_result_bearing_run: bool
    provider_transport: str
    provider_fallback: str
    rerun: str
    rescue: str
    rethreshold: str
    rearm: str
    refill: str
    c7_external: bool
    c7_writable_by_runtime: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ControlsRecord:
        fields = {
            "one_result_bearing_run",
            "provider_transport",
            "provider_fallback",
            "rerun",
            "rescue",
            "rethreshold",
            "rearm",
            "refill",
            "c7_external",
            "c7_writable_by_runtime",
        }
        payload = _closed(value, fields, cls.__name__)
        record = cls(
            one_result_bearing_run=_bool(
                payload["one_result_bearing_run"], "one_result_bearing_run"
            ),
            provider_transport=_literal(
                payload["provider_transport"], "provider_transport", "API_ONLY"
            ),
            provider_fallback=_literal(
                payload["provider_fallback"], "provider_fallback", "FORBIDDEN"
            ),
            rerun=_literal(payload["rerun"], "rerun", "FORBIDDEN"),
            rescue=_literal(payload["rescue"], "rescue", "FORBIDDEN"),
            rethreshold=_literal(
                payload["rethreshold"], "rethreshold", "FORBIDDEN"
            ),
            rearm=_literal(payload["rearm"], "rearm", "FORBIDDEN"),
            refill=_literal(payload["refill"], "refill", "FORBIDDEN"),
            c7_external=_bool(payload["c7_external"], "c7_external"),
            c7_writable_by_runtime=_bool(
                payload["c7_writable_by_runtime"], "c7_writable_by_runtime"
            ),
        )
        if not record.one_result_bearing_run:
            raise ContractValidationError("one_result_bearing_run must be true")
        if not record.c7_external or record.c7_writable_by_runtime:
            raise ContractValidationError("C7 must be external and non-writable")
        return record

    def to_mapping(self) -> dict[str, Any]:
        return {
            "one_result_bearing_run": self.one_result_bearing_run,
            "provider_transport": self.provider_transport,
            "provider_fallback": self.provider_fallback,
            "rerun": self.rerun,
            "rescue": self.rescue,
            "rethreshold": self.rethreshold,
            "rearm": self.rearm,
            "refill": self.refill,
            "c7_external": self.c7_external,
            "c7_writable_by_runtime": self.c7_writable_by_runtime,
        }


@dataclass(frozen=True, slots=True)
class RolePolicy:
    required_roles: tuple[str, ...]
    pairwise_distinct_sovereign_roles: bool
    model_reviewer_reuse_across_arms_allowed: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RolePolicy:
        payload = _closed(
            value,
            {
                "required_roles",
                "pairwise_distinct_sovereign_roles",
                "model_reviewer_reuse_across_arms_allowed",
            },
            cls.__name__,
        )
        roles = _strings(payload["required_roles"], "required_roles")
        if roles != _REQUIRED_ROLES:
            raise ContractValidationError("required sovereign role set/order drifted")
        distinct = _bool(
            payload["pairwise_distinct_sovereign_roles"],
            "pairwise_distinct_sovereign_roles",
        )
        if not distinct:
            raise ContractValidationError("sovereign roles must remain pairwise distinct")
        return cls(
            required_roles=roles,
            pairwise_distinct_sovereign_roles=distinct,
            model_reviewer_reuse_across_arms_allowed=_bool(
                payload["model_reviewer_reuse_across_arms_allowed"],
                "model_reviewer_reuse_across_arms_allowed",
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "required_roles": list(self.required_roles),
            "pairwise_distinct_sovereign_roles": self.pairwise_distinct_sovereign_roles,
            "model_reviewer_reuse_across_arms_allowed": self.model_reviewer_reuse_across_arms_allowed,
        }


@dataclass(frozen=True, slots=True)
class OracleCustody:
    custodian_id: str
    sealed_referee_sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> OracleCustody:
        payload = _closed(value, {"custodian_id", "sealed_referee_sha256"}, cls.__name__)
        return cls(
            custodian_id=_text(payload["custodian_id"], "custodian_id"),
            sealed_referee_sha256=_sha(
                payload["sealed_referee_sha256"], "sealed_referee_sha256"
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "custodian_id": self.custodian_id,
            "sealed_referee_sha256": self.sealed_referee_sha256,
        }


@dataclass(frozen=True, slots=True)
class C7Authority:
    authority_id: str
    writable_by_runtime: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> C7Authority:
        payload = _closed(value, {"authority_id", "writable_by_runtime"}, cls.__name__)
        writable = _bool(payload["writable_by_runtime"], "writable_by_runtime")
        if writable:
            raise ContractValidationError("C7 authority cannot be runtime-writable")
        return cls(
            authority_id=_text(payload["authority_id"], "authority_id"),
            writable_by_runtime=writable,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "authority_id": self.authority_id,
            "writable_by_runtime": self.writable_by_runtime,
        }


@dataclass(frozen=True, slots=True)
class ReviewGateRecord:
    builder_id: str
    reviewer_id: str
    target_head: str
    prereg_candidate_sha256: str
    exact_manifest_sha256: str
    verdict: str
    review_record_sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ReviewGateRecord:
        payload = _closed(
            value,
            {
                "builder_id",
                "reviewer_id",
                "target_head",
                "prereg_candidate_sha256",
                "exact_manifest_sha256",
                "verdict",
                "review_record_sha256",
            },
            cls.__name__,
        )
        builder = _text(payload["builder_id"], "builder_id")
        reviewer = _text(payload["reviewer_id"], "reviewer_id")
        if builder == reviewer:
            raise ContractValidationError("builder and independent reviewer must differ")
        head = _text(payload["target_head"], "target_head")
        if not _GIT_HEAD.fullmatch(head):
            raise ContractValidationError("target_head requires a 40-character Git hash")
        return cls(
            builder_id=builder,
            reviewer_id=reviewer,
            target_head=head,
            prereg_candidate_sha256=_sha(
                payload["prereg_candidate_sha256"], "prereg_candidate_sha256"
            ),
            exact_manifest_sha256=_sha(
                payload["exact_manifest_sha256"], "exact_manifest_sha256"
            ),
            verdict=_literal(payload["verdict"], "verdict", "ACCEPT"),
            review_record_sha256=_sha(
                payload["review_record_sha256"], "review_record_sha256"
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "builder_id": self.builder_id,
            "reviewer_id": self.reviewer_id,
            "target_head": self.target_head,
            "prereg_candidate_sha256": self.prereg_candidate_sha256,
            "exact_manifest_sha256": self.exact_manifest_sha256,
            "verdict": self.verdict,
            "review_record_sha256": self.review_record_sha256,
        }


@dataclass(frozen=True, slots=True)
class RunAuthority:
    authority_id: str
    single_run_sequence: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RunAuthority:
        payload = _closed(value, {"authority_id", "single_run_sequence"}, cls.__name__)
        sequence = _positive_int(payload["single_run_sequence"], "single_run_sequence")
        if sequence != 1:
            raise ContractValidationError("only one predeclared result-bearing run is allowed")
        return cls(
            authority_id=_text(payload["authority_id"], "authority_id"),
            single_run_sequence=sequence,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "authority_id": self.authority_id,
            "single_run_sequence": self.single_run_sequence,
        }


@dataclass(frozen=True, slots=True)
class ExternalBindings:
    provider_bindings: tuple[ReviewerEndpointBinding, ...]
    oracle_custody: OracleCustody | None
    c7_authority: C7Authority | None
    independent_review: ReviewGateRecord | None
    freezer_identity: str | None
    run_authority: RunAuthority | None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ExternalBindings:
        payload = _closed(
            value,
            {
                "provider_bindings",
                "oracle_custody",
                "c7_authority",
                "independent_review",
                "freezer_identity",
                "run_authority",
            },
            cls.__name__,
        )
        raw_providers = payload["provider_bindings"]
        if not isinstance(raw_providers, list):
            raise ContractValidationError("provider_bindings requires an array")
        providers = tuple(ReviewerEndpointBinding.from_mapping(item) for item in raw_providers)
        arm_ids = [binding.arm_id for binding in providers]
        if len(set(arm_ids)) != len(arm_ids):
            raise ContractValidationError("provider arm bindings must be unique")
        custody_value = _optional_mapping(payload["oracle_custody"], "oracle_custody")
        c7_value = _optional_mapping(payload["c7_authority"], "c7_authority")
        review_value = _optional_mapping(
            payload["independent_review"], "independent_review"
        )
        run_value = _optional_mapping(payload["run_authority"], "run_authority")
        freezer_raw = payload["freezer_identity"]
        if freezer_raw is not None and not isinstance(freezer_raw, str):
            raise ContractValidationError("freezer_identity requires a string or null")
        freezer = None if freezer_raw is None else _text(freezer_raw, "freezer_identity")
        return cls(
            provider_bindings=providers,
            oracle_custody=(
                None if custody_value is None else OracleCustody.from_mapping(custody_value)
            ),
            c7_authority=(
                None if c7_value is None else C7Authority.from_mapping(c7_value)
            ),
            independent_review=(
                None
                if review_value is None
                else ReviewGateRecord.from_mapping(review_value)
            ),
            freezer_identity=freezer,
            run_authority=(
                None if run_value is None else RunAuthority.from_mapping(run_value)
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "provider_bindings": [item.to_mapping() for item in self.provider_bindings],
            "oracle_custody": (
                None if self.oracle_custody is None else self.oracle_custody.to_mapping()
            ),
            "c7_authority": (
                None if self.c7_authority is None else self.c7_authority.to_mapping()
            ),
            "independent_review": (
                None
                if self.independent_review is None
                else self.independent_review.to_mapping()
            ),
            "freezer_identity": self.freezer_identity,
            "run_authority": (
                None if self.run_authority is None else self.run_authority.to_mapping()
            ),
        }


@dataclass(frozen=True, slots=True)
class GateState:
    freeze_status: str
    run_status: str
    evidence_status: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> GateState:
        payload = _closed(
            value, {"freeze_status", "run_status", "evidence_status"}, cls.__name__
        )
        return cls(
            freeze_status=_literal(
                payload["freeze_status"], "freeze_status", "NOT_FROZEN"
            ),
            run_status=_literal(payload["run_status"], "run_status", "NOT_RUN"),
            evidence_status=_literal(
                payload["evidence_status"], "evidence_status", "NOT_EVIDENCE"
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "freeze_status": self.freeze_status,
            "run_status": self.run_status,
            "evidence_status": self.evidence_status,
        }


@dataclass(frozen=True, slots=True)
class NativePreregCandidate:
    prereg_id: str
    schema_version: str
    candidate_status: str
    track: str
    mechanism: MechanismRecord
    exact_manifest: ExactManifest
    corpus: CorpusRecord
    scoring_metrics: tuple[str, ...]
    controls: ControlsRecord
    role_policy: RolePolicy
    external_bindings: ExternalBindings
    gates: GateState
    result_schema_path: str
    raw_result_status: str
    verdict_before_adjudication: None
    claim_ceiling: str
    excluded_claims: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> NativePreregCandidate:
        payload = _closed(
            value,
            {
                "prereg_id",
                "schema_version",
                "candidate_status",
                "track",
                "mechanism",
                "exact_manifest",
                "corpus",
                "scoring_metrics",
                "controls",
                "role_policy",
                "external_bindings",
                "gates",
                "result_contract",
                "claim_boundary",
            },
            cls.__name__,
        )
        mechanism = MechanismRecord.from_mapping(payload["mechanism"])
        manifest = ExactManifest.from_mapping(payload["exact_manifest"])
        if set(mechanism.files) != set(manifest.files):
            raise ContractValidationError(
                "mechanism.files must equal exact_manifest.files keys"
            )
        result = _closed(
            payload["result_contract"],
            {"schema_path", "raw_status", "verdict_before_adjudication"},
            "result_contract",
        )
        if result["verdict_before_adjudication"] is not None:
            raise ContractValidationError("raw result verdict must remain null")
        claim = _closed(
            payload["claim_boundary"], {"ceiling", "excluded"}, "claim_boundary"
        )
        return cls(
            prereg_id=_literal(payload["prereg_id"], "prereg_id", "R-EVAL-INDEP-1"),
            schema_version=_literal(
                payload["schema_version"], "schema_version", _SCHEMA_VERSION
            ),
            candidate_status=_literal(
                payload["candidate_status"],
                "candidate_status",
                "READINESS_CANDIDATE_BLOCKED_UNBOUND",
            ),
            track=_literal(payload["track"], "track", "Research"),
            mechanism=mechanism,
            exact_manifest=manifest,
            corpus=CorpusRecord.from_mapping(payload["corpus"]),
            scoring_metrics=_strings(payload["scoring_metrics"], "scoring_metrics"),
            controls=ControlsRecord.from_mapping(payload["controls"]),
            role_policy=RolePolicy.from_mapping(payload["role_policy"]),
            external_bindings=ExternalBindings.from_mapping(payload["external_bindings"]),
            gates=GateState.from_mapping(payload["gates"]),
            result_schema_path=_text(result["schema_path"], "result_contract.schema_path"),
            raw_result_status=_literal(
                result["raw_status"], "result_contract.raw_status", "RAW_NOT_ADJUDICATED"
            ),
            verdict_before_adjudication=None,
            claim_ceiling=_literal(
                claim["ceiling"],
                "claim_boundary.ceiling",
                "MEASURED_REVIEWER_ROUTING_ON_FROZEN_MUTATION_CORPUS",
            ),
            excluded_claims=_strings(claim["excluded"], "claim_boundary.excluded"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "prereg_id": self.prereg_id,
            "schema_version": self.schema_version,
            "candidate_status": self.candidate_status,
            "track": self.track,
            "mechanism": self.mechanism.to_mapping(),
            "exact_manifest": self.exact_manifest.to_mapping(),
            "corpus": self.corpus.to_mapping(),
            "scoring_metrics": list(self.scoring_metrics),
            "controls": self.controls.to_mapping(),
            "role_policy": self.role_policy.to_mapping(),
            "external_bindings": self.external_bindings.to_mapping(),
            "gates": self.gates.to_mapping(),
            "result_contract": {
                "schema_path": self.result_schema_path,
                "raw_status": self.raw_result_status,
                "verdict_before_adjudication": self.verdict_before_adjudication,
            },
            "claim_boundary": {
                "ceiling": self.claim_ceiling,
                "excluded": list(self.excluded_claims),
            },
        }

    def review_subject_sha256(self) -> str:
        """Bind the exact unbound candidate that external review must inspect."""
        payload = self.to_mapping()
        payload["external_bindings"] = {
            "provider_bindings": [],
            "oracle_custody": None,
            "c7_authority": None,
            "independent_review": None,
            "freezer_identity": None,
            "run_authority": None,
        }
        return canonical_digest(payload)


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    status: str
    blockers: tuple[str, ...]
    prereg_candidate_sha256: str
    exact_manifest_sha256: str


def load_native_prereg(path: Path) -> NativePreregCandidate:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReadinessError(f"cannot load JSON-compatible prereg YAML: {path}") from error
    if not isinstance(payload, Mapping):
        raise ReadinessError("prereg document must be an object")
    try:
        return NativePreregCandidate.from_mapping(payload)
    except ContractValidationError as error:
        raise ReadinessError(str(error)) from error


def _validate_role_separation(candidate: NativePreregCandidate) -> None:
    bindings = candidate.external_bindings
    reviewer_ids = {
        binding.reviewer_identity.reviewer_id for binding in bindings.provider_bindings
    }
    sovereign_ids: list[str] = []
    if bindings.oracle_custody is not None:
        sovereign_ids.append(bindings.oracle_custody.custodian_id)
    if bindings.c7_authority is not None:
        sovereign_ids.append(bindings.c7_authority.authority_id)
    if bindings.independent_review is not None:
        sovereign_ids.extend(
            [
                bindings.independent_review.builder_id,
                bindings.independent_review.reviewer_id,
            ]
        )
    if bindings.freezer_identity is not None:
        sovereign_ids.append(bindings.freezer_identity)
    if bindings.run_authority is not None:
        sovereign_ids.append(bindings.run_authority.authority_id)
    if len(set(sovereign_ids)) != len(sovereign_ids):
        raise ReadinessError("sovereign role identity collapse")
    overlap = sorted(reviewer_ids & set(sovereign_ids))
    if overlap:
        raise ReadinessError(f"model reviewer overlaps sovereign role: {overlap}")


def assess_native_readiness(
    candidate: NativePreregCandidate, repository_root: Path
) -> ReadinessReport:
    try:
        candidate.exact_manifest.verify(repository_root)
    except (ContractValidationError, OSError) as error:
        raise ReadinessError(str(error)) from error
    bindings = candidate.external_bindings
    blockers: list[str] = []
    if not bindings.provider_bindings:
        blockers.append(_BLOCKERS[0])
    if bindings.oracle_custody is None:
        blockers.append(_BLOCKERS[1])
    if bindings.c7_authority is None:
        blockers.append(_BLOCKERS[2])
    if bindings.independent_review is None:
        blockers.append(_BLOCKERS[3])
    if bindings.freezer_identity is None:
        blockers.append(_BLOCKERS[4])
    if bindings.run_authority is None:
        blockers.append(_BLOCKERS[5])
    if bindings.provider_bindings:
        public_hashes = {
            binding.public_cases_sha256 for binding in bindings.provider_bindings
        }
        if public_hashes != {candidate.corpus.public_cases_sha256}:
            raise ReadinessError("provider bindings do not bind the exact public corpus")
    if bindings.oracle_custody is not None and (
        bindings.oracle_custody.sealed_referee_sha256
        != candidate.corpus.referee_cases_sha256
    ):
        raise ReadinessError("oracle custody does not bind the exact referee corpus")
    if bindings.independent_review is not None:
        review = bindings.independent_review
        if review.exact_manifest_sha256 != candidate.exact_manifest.sha256:
            raise ReadinessError("independent review exact-manifest binding drift")
        if review.prereg_candidate_sha256 != candidate.review_subject_sha256():
            raise ReadinessError("independent review prereg-candidate binding drift")
    _validate_role_separation(candidate)
    status = "BLOCKED_UNBOUND" if blockers else "READY_FOR_EXTERNAL_FREEZE"
    return ReadinessReport(
        status=status,
        blockers=tuple(blockers),
        prereg_candidate_sha256=candidate.review_subject_sha256(),
        exact_manifest_sha256=candidate.exact_manifest.sha256,
    )


def assert_native_readiness(
    candidate: NativePreregCandidate, repository_root: Path
) -> ReadinessReport:
    report = assess_native_readiness(candidate, repository_root)
    if report.blockers:
        raise ReadinessError(f"native readiness blocked: {list(report.blockers)}")
    return report


__all__ = (
    "ExactManifest",
    "NativePreregCandidate",
    "ReadinessError",
    "ReadinessReport",
    "ReviewGateRecord",
    "assert_native_readiness",
    "assess_native_readiness",
    "load_native_prereg",
)
