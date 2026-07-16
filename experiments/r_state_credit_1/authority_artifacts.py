"""Authority artifact types for the R-STATE-CREDIT-1 non-self-minting freeze gate.

The artifact content layer is a deterministic JSON object (sorted keys, no
whitespace, UTF-8, LF line endings).  The envelope layer adds the signing
identity, detached signature, timestamps, and witness references.  A run must
present all five required artifact types in an ``AuthorityArtifactBundle``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping

from experiments.r_state_credit_1.contracts import canonical_json
from experiments.r_state_credit_1.signature_backend import SignatureBackend


class AuthorityArtifactError(ValueError):
    """Raised when an authority artifact is structurally invalid."""


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityArtifactError(f"{name} must be non-empty text")
    return value


def _require_sha256(name: str, value: object) -> str:
    text = _require_text(name, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise AuthorityArtifactError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _require_git_head(name: str, value: object) -> str:
    text = _require_text(name, value)
    if len(text) != 40 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise AuthorityArtifactError(f"{name} must be a lowercase Git commit id")
    return text


def _require_text_tuple(name: str, value: tuple[str, ...]) -> None:
    if not isinstance(value, tuple):
        raise AuthorityArtifactError(f"{name} must be a tuple")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise AuthorityArtifactError(f"{name} must contain non-empty text")
    if len(value) != len(set(value)):
        raise AuthorityArtifactError(f"{name} must not contain duplicates")


def _require_digest_mapping(name: str, value: Mapping[str, str]) -> None:
    if not isinstance(value, Mapping):
        raise AuthorityArtifactError(f"{name} must be a mapping")
    for key, digest in value.items():
        if not isinstance(key, str) or not key.strip():
            raise AuthorityArtifactError(f"{name} keys must be non-empty text")
        _require_sha256(f"{name}[{key}]", digest)


def compute_payload_digest(content: Mapping[str, Any]) -> str:
    """Return the SHA-256 digest of the canonical JSON content layer."""
    rendered = canonical_json(content)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class AuthorityArtifact:
    """Common envelope for an authority artifact.

    Subclasses add the typed content layer that is signed and digested.
    """

    artifact_id: str
    artifact_type: str
    payload_digest: str
    signer_principal_id: str
    signer_instance_id: str
    signature_bytes: bytes
    signed_at: str
    expires_at: str
    witness_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text("artifact_id", self.artifact_id)
        _require_text("artifact_type", self.artifact_type)
        _require_sha256("payload_digest", self.payload_digest)
        _require_text("signer_principal_id", self.signer_principal_id)
        _require_text("signer_instance_id", self.signer_instance_id)
        if not isinstance(self.signature_bytes, bytes):
            raise AuthorityArtifactError("signature_bytes must be bytes")
        _require_text("signed_at", self.signed_at)
        _require_text("expires_at", self.expires_at)
        _require_text_tuple("witness_refs", self.witness_refs)

    def identity_key(self) -> str:
        """Canonical identity string used by the signature backend."""
        return f"{self.signer_principal_id}:{self.signer_instance_id}"

    def content_mapping(self) -> dict[str, Any]:
        """Return the JSON-serializable content layer for this artifact type."""
        raise NotImplementedError

    def recompute_payload_digest(self) -> str:
        """Recompute the digest from the current content layer."""
        return compute_payload_digest(self.content_mapping())

    def sign(
        self,
        backend: SignatureBackend,
        identity_key: str,
        *,
        principal_id: str,
        instance_id: str,
        signed_at: str,
        expires_at: str,
        witness_refs: tuple[str, ...],
    ) -> None:
        """Compute the payload digest and create a detached signature.

        The artifact is mutated in place.  Callers must ensure the content
        layer already contains the intended values before signing.
        """
        self.signer_principal_id = _require_text("principal_id", principal_id)
        self.signer_instance_id = _require_text("instance_id", instance_id)
        self.signed_at = _require_text("signed_at", signed_at)
        self.expires_at = _require_text("expires_at", expires_at)
        _require_text_tuple("witness_refs", witness_refs)
        self.witness_refs = witness_refs
        self.payload_digest = self.recompute_payload_digest()
        self.signature_bytes = backend.sign(
            identity_key, bytes.fromhex(self.payload_digest)
        )


@dataclass(slots=True)
class PreregAcceptanceArtifact(AuthorityArtifact):
    """Independent preregistration reviewer acceptance artifact."""

    schema_version: str = "1.0"
    reviewer_id: str = ""
    reviewed_at: str = ""
    candidate_repo: str = ""
    candidate_branch: str = ""
    candidate_commit_sha: str = ""
    candidate_sha256: str = ""
    prereg_path: str = ""
    prereg_sha256: str = ""
    acceptance: bool = False
    conditions: tuple[str, ...] = ()
    notes: str = ""

    EXPECTED_ARTIFACT_TYPE: str = "prereg-acceptance"

    def __post_init__(self) -> None:
        AuthorityArtifact.__post_init__(self)
        if self.artifact_type != self.EXPECTED_ARTIFACT_TYPE:
            raise AuthorityArtifactError(
                f"artifact_type must be {self.EXPECTED_ARTIFACT_TYPE}"
            )
        _require_text("reviewer_id", self.reviewer_id)
        _require_text("reviewed_at", self.reviewed_at)
        _require_text("candidate_repo", self.candidate_repo)
        _require_text("candidate_branch", self.candidate_branch)
        _require_git_head("candidate_commit_sha", self.candidate_commit_sha)
        _require_sha256("candidate_sha256", self.candidate_sha256)
        _require_text("prereg_path", self.prereg_path)
        _require_sha256("prereg_sha256", self.prereg_sha256)
        if not isinstance(self.acceptance, bool):
            raise AuthorityArtifactError("acceptance must be bool")
        _require_text_tuple("conditions", self.conditions)

    def content_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_type": self.artifact_type,
            "reviewer_id": self.reviewer_id,
            "reviewed_at": self.reviewed_at,
            "candidate_repo": self.candidate_repo,
            "candidate_branch": self.candidate_branch,
            "candidate_commit_sha": self.candidate_commit_sha,
            "candidate_sha256": self.candidate_sha256,
            "prereg_path": self.prereg_path,
            "prereg_sha256": self.prereg_sha256,
            "acceptance": self.acceptance,
            "conditions": self.conditions,
            "notes": self.notes,
        }


@dataclass(slots=True)
class ArchitectureAcceptanceArtifact(AuthorityArtifact):
    """Independent architecture/RR-0029/RR-0031 reviewer acceptance artifact."""

    schema_version: str = "1.0"
    reviewer_id: str = ""
    reviewed_at: str = ""
    candidate_commit_sha: str = ""
    candidate_sha256: str = ""
    rr_0029_delta: str = ""
    rr_0031_delta: str = ""
    mechanism_file_hashes: dict[str, str] = None  # type: ignore[assignment]
    acceptance: bool = False
    notes: str = ""

    EXPECTED_ARTIFACT_TYPE: str = "architecture-acceptance"

    def __post_init__(self) -> None:
        AuthorityArtifact.__post_init__(self)
        if self.artifact_type != self.EXPECTED_ARTIFACT_TYPE:
            raise AuthorityArtifactError(
                f"artifact_type must be {self.EXPECTED_ARTIFACT_TYPE}"
            )
        _require_text("reviewer_id", self.reviewer_id)
        _require_text("reviewed_at", self.reviewed_at)
        _require_git_head("candidate_commit_sha", self.candidate_commit_sha)
        _require_sha256("candidate_sha256", self.candidate_sha256)
        _require_text("rr_0029_delta", self.rr_0029_delta)
        _require_text("rr_0031_delta", self.rr_0031_delta)
        if self.mechanism_file_hashes is None:
            raise AuthorityArtifactError("mechanism_file_hashes is required")
        _require_digest_mapping("mechanism_file_hashes", self.mechanism_file_hashes)
        if not isinstance(self.acceptance, bool):
            raise AuthorityArtifactError("acceptance must be bool")

    def __setattr__(self, name: str, value: object) -> None:
        if name == "mechanism_file_hashes" and value is None:
            # Allow the default-None sentinel to be replaced by a real mapping.
            object.__setattr__(self, name, value)
            return
        object.__setattr__(self, name, value)

    def content_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_type": self.artifact_type,
            "reviewer_id": self.reviewer_id,
            "reviewed_at": self.reviewed_at,
            "candidate_commit_sha": self.candidate_commit_sha,
            "candidate_sha256": self.candidate_sha256,
            "rr_0029_delta": self.rr_0029_delta,
            "rr_0031_delta": self.rr_0031_delta,
            "mechanism_file_hashes": self.mechanism_file_hashes,
            "acceptance": self.acceptance,
            "notes": self.notes,
        }


@dataclass(slots=True)
class NativeFreezeLockArtifact(AuthorityArtifact):
    """Native freeze lock created by an identity distinct from builder/reviewers."""

    schema_version: str = "1.0"
    freezer_id: str = ""
    frozen_at: str = ""
    candidate_commit_sha: str = ""
    candidate_sha256: str = ""
    prereg_acceptance_digest: str = ""
    architecture_acceptance_digest: str = ""
    review_record_digests: tuple[str, ...] = ()
    builder_id: str = ""
    builder_id_included_for_audit_only: bool = True

    EXPECTED_ARTIFACT_TYPE: str = "native-freeze-lock"

    def __post_init__(self) -> None:
        AuthorityArtifact.__post_init__(self)
        if self.artifact_type != self.EXPECTED_ARTIFACT_TYPE:
            raise AuthorityArtifactError(
                f"artifact_type must be {self.EXPECTED_ARTIFACT_TYPE}"
            )
        _require_text("freezer_id", self.freezer_id)
        _require_text("frozen_at", self.frozen_at)
        _require_git_head("candidate_commit_sha", self.candidate_commit_sha)
        _require_sha256("candidate_sha256", self.candidate_sha256)
        _require_sha256(
            "prereg_acceptance_digest", self.prereg_acceptance_digest
        )
        _require_sha256(
            "architecture_acceptance_digest", self.architecture_acceptance_digest
        )
        _require_text_tuple("review_record_digests", self.review_record_digests)
        _require_text("builder_id", self.builder_id)
        if not isinstance(self.builder_id_included_for_audit_only, bool):
            raise AuthorityArtifactError(
                "builder_id_included_for_audit_only must be bool"
            )

    def content_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_type": self.artifact_type,
            "freezer_id": self.freezer_id,
            "frozen_at": self.frozen_at,
            "candidate_commit_sha": self.candidate_commit_sha,
            "candidate_sha256": self.candidate_sha256,
            "prereg_acceptance_digest": self.prereg_acceptance_digest,
            "architecture_acceptance_digest": self.architecture_acceptance_digest,
            "review_record_digests": self.review_record_digests,
            "builder_id": self.builder_id,
            "builder_id_included_for_audit_only": (
                self.builder_id_included_for_audit_only
            ),
        }


@dataclass(slots=True)
class C7AcceptanceArtifact(AuthorityArtifact):
    """C7 owner acceptance artifact binding epoch, token digest, and stop path."""

    schema_version: str = "1.0"
    owner_id: str = ""
    epoch: str = ""
    capability_token_sha256: str = ""
    stop_path: str = ""
    freeze_lock_digest: str = ""
    issued_at: str = ""
    acceptance: bool = False

    EXPECTED_ARTIFACT_TYPE: str = "c7-acceptance"

    def __post_init__(self) -> None:
        AuthorityArtifact.__post_init__(self)
        if self.artifact_type != self.EXPECTED_ARTIFACT_TYPE:
            raise AuthorityArtifactError(
                f"artifact_type must be {self.EXPECTED_ARTIFACT_TYPE}"
            )
        _require_text("owner_id", self.owner_id)
        _require_text("epoch", self.epoch)
        _require_sha256("capability_token_sha256", self.capability_token_sha256)
        _require_text("stop_path", self.stop_path)
        _require_sha256("freeze_lock_digest", self.freeze_lock_digest)
        _require_text("issued_at", self.issued_at)
        if not isinstance(self.acceptance, bool):
            raise AuthorityArtifactError("acceptance must be bool")

    def content_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_type": self.artifact_type,
            "owner_id": self.owner_id,
            "epoch": self.epoch,
            "capability_token_sha256": self.capability_token_sha256,
            "stop_path": self.stop_path,
            "freeze_lock_digest": self.freeze_lock_digest,
            "issued_at": self.issued_at,
            "acceptance": self.acceptance,
        }


@dataclass(slots=True)
class RunAuthorizationArtifact(AuthorityArtifact):
    """Founder/CTO per-run authorization artifact."""

    schema_version: str = "1.0"
    authorizer_id: str = ""
    authorized_at: str = ""
    freeze_lock_digest: str = ""
    c7_acceptance_digest: str = ""
    max_runs: int = 0
    result_bearing: bool = False
    acceptance: bool = False
    notes: str = ""

    EXPECTED_ARTIFACT_TYPE: str = "run-authorization"

    def __post_init__(self) -> None:
        AuthorityArtifact.__post_init__(self)
        if self.artifact_type != self.EXPECTED_ARTIFACT_TYPE:
            raise AuthorityArtifactError(
                f"artifact_type must be {self.EXPECTED_ARTIFACT_TYPE}"
            )
        _require_text("authorizer_id", self.authorizer_id)
        _require_text("authorized_at", self.authorized_at)
        _require_sha256("freeze_lock_digest", self.freeze_lock_digest)
        _require_sha256("c7_acceptance_digest", self.c7_acceptance_digest)
        if not isinstance(self.max_runs, int) or isinstance(self.max_runs, bool):
            raise AuthorityArtifactError("max_runs must be int")
        if not isinstance(self.result_bearing, bool):
            raise AuthorityArtifactError("result_bearing must be bool")
        if not isinstance(self.acceptance, bool):
            raise AuthorityArtifactError("acceptance must be bool")

    def content_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_type": self.artifact_type,
            "authorizer_id": self.authorizer_id,
            "authorized_at": self.authorized_at,
            "freeze_lock_digest": self.freeze_lock_digest,
            "c7_acceptance_digest": self.c7_acceptance_digest,
            "max_runs": self.max_runs,
            "result_bearing": self.result_bearing,
            "acceptance": self.acceptance,
            "notes": self.notes,
        }


@dataclass(slots=True)
class AuthorityArtifactBundle:
    """All five authority artifacts required to authorize a result-bearing run."""

    prereg_acceptance: PreregAcceptanceArtifact
    architecture_acceptance: ArchitectureAcceptanceArtifact
    native_freeze_lock: NativeFreezeLockArtifact
    c7_acceptance: C7AcceptanceArtifact
    run_authorization: RunAuthorizationArtifact

    def __post_init__(self) -> None:
        for name, expected in (
            ("prereg_acceptance", PreregAcceptanceArtifact),
            ("architecture_acceptance", ArchitectureAcceptanceArtifact),
            ("native_freeze_lock", NativeFreezeLockArtifact),
            ("c7_acceptance", C7AcceptanceArtifact),
            ("run_authorization", RunAuthorizationArtifact),
        ):
            value = getattr(self, name)
            if not isinstance(value, expected):
                raise AuthorityArtifactError(
                    f"{name} must be {expected.__name__}"
                )

    def all_artifacts(self) -> tuple[AuthorityArtifact, ...]:
        return (
            self.prereg_acceptance,
            self.architecture_acceptance,
            self.native_freeze_lock,
            self.c7_acceptance,
            self.run_authorization,
        )
